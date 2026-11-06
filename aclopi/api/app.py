"""FastAPI application over the WorkerPool (L5.2).

Run it with `python -m aclopi.api` (one process, one uvicorn worker: every API process starts its
own pool of 7 NetLogo JVMs, see docs/api.md). The pool starts in the background when the API
starts; /health/live answers from the first second, and sessions are accepted once every worker
is ready.

The diagnostic worker operations ("command", "report") are never exposed and the pool is always
created with debug=False.
"""

from __future__ import annotations

import asyncio
import secrets
import logging
import os
import re
import time
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Callable

import anyio
from pathlib import Path as FilePath

from fastapi import Depends, FastAPI, File, Header, Path, Query, Request, Response, UploadFile, WebSocket
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse

from aclopi.api import errors
from aclopi.api.errors import (
    InvalidRunState, InvalidScenario, NoWorkerAvailable, PlatformStarting, ProductSetNotFound, RunNotFound, Unauthorized,
    WorkerUnavailable,
)
from aclopi.api.instance_lock import InstanceLock
from aclopi.api.models import (
    STEP_N_DESCRIPTION, CandidatesResult, Event, Health, Kpis, PlantLayout, PlantState, Probe, RunRequest,
    GeneratedProducts, GenerateRequest, NextMachineRequest, NextMachineResponse, ParsedCsv, ProductSet, ProductSetIn,
    ProductSetSummary, RunPage, RunRecord, ScenarioSpecOut, SessionCreate, SessionInfo, SessionMetrics, StepResult, WhatIfRequest,
    WhatIfResponse,
)
from aclopi.workers.protocol import NoFreeWorker
from aclopi.api.agent import AgentClient
from aclopi.contracts.agent import bearer_matches
from aclopi.api.product_sets import InMemoryProductSetStore, parse_csv, summary, to_csv
from aclopi.api.results import DynamoProductSetStore, DynamoResultsStore, InMemoryResultsStore
from aclopi.api.whatif import run_whatif
from aclopi.api.ws import stream_session
from aclopi.api.registry import SessionRegistry
from aclopi.api.settings import Settings
from aclopi.logjson import session_id_var
from aclopi.sim import scenarios
from aclopi.workers.pool import WorkerPool
from aclopi.workers.protocol import MAX_STEP_TICKS, set_timeout_scale

API_VERSION = "0.2.0"
THREAD_LIMIT = 32
SESSION_PATH = re.compile(r"^/sessions/([^/]+)")
QUIET_PATHS = ("/health",)
STATIC_DIR = FilePath(__file__).resolve().parent / "static"

logger = logging.getLogger(__name__)

PoolFactory = Callable[[Settings], WorkerPool]
FatalCallback = Callable[[BaseException], None]


def default_pool_factory(settings: Settings) -> WorkerPool:
    return WorkerPool(
        n_session=settings.n_session_workers,
        n_whatif=settings.n_whatif_workers,
        work_dir=settings.work_dir,
        jvm_args=settings.jvm_args,
        debug=False,
        warm=True,
        start_timeout_s=settings.startup_timeout_s,
        run_options=settings.run_options(),
    )


def exit_process(exc: BaseException) -> None:
    """Default reaction to a failed pool start when not run through `python -m aclopi.api`."""
    logging.shutdown()
    os._exit(3)


class Runtime:
    """Pool, registry and phase of the platform: starting -> ready (or failed); stopping at the end."""

    def __init__(self, settings: Settings, pool_factory: PoolFactory, on_fatal: FatalCallback) -> None:
        self.settings = settings
        self.pool_factory = pool_factory
        self.on_fatal = on_fatal
        self.phase = "starting"
        self.started_mono = time.monotonic()
        self.startup_s: float | None = None
        self.limiter = anyio.CapacityLimiter(THREAD_LIMIT)
        self.lock = InstanceLock(settings.work_dir)
        self.pool: WorkerPool | None = None
        self.registry: SessionRegistry | None = None
        self.agent: AgentClient | None = None
        self.product_sets: Any = InMemoryProductSetStore()
        self.results: Any = None
        self._tasks: list[asyncio.Task[Any]] = []

    async def start(self) -> None:
        self.lock.acquire()
        set_timeout_scale(self.settings.timeout_scale)
        self.pool = self.pool_factory(self.settings)
        if self.pool.debug:
            raise RuntimeError("the API must never run a pool with debug=True")
        self.registry = SessionRegistry(
            self.pool, self.settings.session_idle_timeout_s, self.limiter,
            max_fast_runs=self.settings.max_fast_runs, ws_queue=self.settings.ws_queue,
        )
        self.registry.attach(asyncio.get_running_loop())
        self.pool.set_session_callbacks(self.registry.push_from_thread, self.registry.lost_from_thread)
        self.agent = AgentClient(self.settings.agent_url, self.settings.agent_token,
                                 self.settings.agent_decide_timeout_s, self.settings.agent_health_interval_s)
        await self.agent.start()
        self.registry.agent = self.agent
        self.registry.fast_decision_timeout_s = self.settings.fast_decision_timeout_s
        self._open_stores()
        self.registry.results = self.results
        self._tasks = [
            asyncio.create_task(self._start_pool(), name="pool-start"),
            asyncio.create_task(self.registry.sweep_loop(), name="idle-sweeper"),
            asyncio.create_task(self.registry.watchdog_loop(), name="run-watchdog"),
            asyncio.create_task(self.agent.health_loop(), name="agent-health"),
        ]
        logger.info("API starting: %d session + %d what-if workers", self.settings.n_session_workers,
                    self.settings.n_whatif_workers, extra={"phase": self.phase})

    def _open_stores(self) -> None:
        """Results and product sets: DynamoDB when configured, else in memory."""
        s = self.settings
        if s.results_store == "dynamodb":
            self.results = DynamoResultsStore(s.dynamodb_endpoint, s.dynamodb_table_prefix, s.create_tables, s.aws_region)
            self.product_sets = DynamoProductSetStore(s.dynamodb_endpoint, s.dynamodb_table_prefix, False, s.aws_region)
            logger.info("Results store: DynamoDB (%s)", s.dynamodb_endpoint or f"AWS {s.aws_region}")
        else:
            self.results = InMemoryResultsStore()
            logger.info("Results store: in memory")

    async def _start_pool(self) -> None:
        assert self.pool is not None
        try:
            await anyio.to_thread.run_sync(self.pool.start, limiter=anyio.CapacityLimiter(1))
        except Exception as exc:  # noqa: BLE001
            if self.phase == "stopping":
                return
            self.phase = "failed"
            logger.error("Worker pool failed to start: %s; stopping the API", exc, extra={"phase": self.phase})
            self.on_fatal(exc)
            return
        if self.phase == "starting":
            self.phase = "ready"
            self.startup_s = self.pool.startup_s
            logger.info("Platform ready in %.1f s", time.monotonic() - self.started_mono, extra={"phase": self.phase})

    async def stop(self) -> None:
        self.phase = "stopping"
        for task in self._tasks[1:]:  # sweeper and watchdog
            task.cancel()
        if self.registry is not None:
            self.registry.close_all()
        if self.pool is not None:
            await anyio.to_thread.run_sync(self.pool.shutdown)
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        if self.agent is not None:
            await self.agent.close()
        self.lock.release()
        logger.info("API stopped", extra={"phase": self.phase})

    def health_phase(self, workers: list[dict[str, Any]]) -> str:
        if self.phase == "ready" and any(w["state"] in ("restarting", "failed", "starting") or not w["ready"]
                                         for w in workers):
            return "degraded"
        return self.phase

    def require_ready(self) -> SessionRegistry:
        if self.phase == "starting":
            raise PlatformStarting("plataforma iniciando")
        if self.phase != "ready" or self.registry is None:
            raise WorkerUnavailable(f"the platform is {self.phase}")
        return self.registry

    @property
    def sessions(self) -> SessionRegistry:
        if self.registry is None:
            raise PlatformStarting("plataforma iniciando")
        return self.registry


class RequestContextMiddleware:
    """Sets session_id for the request's log lines and writes one JSON access line per request."""

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path = scope["path"]
        match = SESSION_PATH.match(path)
        token = session_id_var.set(match.group(1) if match else None)
        status = 500
        t0 = time.perf_counter()

        async def send_wrapper(message: dict[str, Any]) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            session_id = (scope.get("state") or {}).get("session_id") or (match.group(1) if match else None)
            level = logging.DEBUG if path.startswith(QUIET_PATHS) and status < 500 else logging.INFO
            logger.log(level, "%s %s %d", scope["method"], path, status, extra={
                "session_id": session_id, "method": scope["method"], "path": path, "status_code": status,
                "elapsed_ms": round(1000 * (time.perf_counter() - t0), 2),
            })
            session_id_var.reset(token)


def create_app(
    settings: Settings | None = None,
    pool_factory: PoolFactory = default_pool_factory,
    on_fatal: FatalCallback = exit_process,
) -> FastAPI:
    settings = settings or Settings.from_env()
    runtime = Runtime(settings, pool_factory, on_fatal)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        await runtime.start()
        try:
            yield
        finally:
            await runtime.stop()

    app = FastAPI(
        title="ACLOPI simulation platform",
        version=API_VERSION,
        description=(
            "Sessions of the Paper.nlogo plant simulation, each one in its own worker process. "
            f"A step advances at most {MAX_STEP_TICKS} ticks per request."
        ),
        lifespan=lifespan,
    )
    app.state.runtime = runtime
    app.state.settings = settings
    app.add_middleware(RequestContextMiddleware)
    errors.install(app)

    def require_agent_token(authorization: str | None = Header(None)) -> None:
        """With ACLOPI_AGENT_TOKEN set, the agent's calls carry Authorization: Bearer <token>."""
        token = settings.agent_token
        if token is None:
            return
        if not bearer_matches(authorization, token):
            raise Unauthorized("missing or wrong Authorization: Bearer token")

    # ----- health -----

    @app.get("/health/live", response_model=Probe, tags=["health"],
             summary="Liveness: 200 while the process answers, also during startup")
    async def health_live() -> dict[str, str]:
        return {"status": "alive"}

    @app.get("/health/ready", response_model=Probe, tags=["health"],
             summary="Readiness: 200 when ready or degraded, 503 otherwise",
             responses={503: {"model": Probe, "description": "starting, failed or stopping"}})
    async def health_ready() -> Any:
        workers = await _pool_status(runtime)
        phase = runtime.health_phase(workers)
        if phase in ("ready", "degraded"):
            return {"status": phase}
        return JSONResponse({"status": phase}, status_code=503)

    @app.get("/health", response_model=Health, tags=["health"], summary="Platform phase, workers and sessions")
    async def health() -> dict[str, Any]:
        workers = await _pool_status(runtime)
        return {
            "status": runtime.health_phase(workers),
            "uptime_s": round(time.monotonic() - runtime.started_mono, 2),
            "startup_s": None if runtime.startup_s is None else round(runtime.startup_s, 2),
            "sessions": {"active": runtime.registry.active_count() if runtime.registry else 0,
                         "max": settings.n_session_workers},
            "workers": [{k: w[k] for k in ("slot", "role", "ready", "state", "pid", "rss_mib", "restarts", "session_id")}
                        for w in workers],
            "agent": runtime.agent.info() if runtime.agent else None,
        }

    # ----- sessions -----

    session_id_path = Path(description="Session id returned by POST /sessions")

    @app.post("/sessions", response_model=SessionInfo, status_code=201, tags=["sessions"],
              summary="Create a session on a free worker and run setup",
              responses=errors.responses(500, 503, 504))
    async def create_session(body: SessionCreate, request: Request) -> dict[str, Any]:
        scenario_id = body.scenario.id if body.scenario else "S0"
        try:
            scenario = {"id": scenario_id,
                        "params": scenarios.validate_params(scenario_id, body.scenario.params if body.scenario else None)}
        except ValueError as exc:
            raise InvalidScenario(str(exc)) from None
        registry = runtime.require_ready()
        seed, seed_source = (body.seed, "user") if body.seed is not None else (random_seed(), "random")
        products = None
        if body.product_set_id is not None:
            found = runtime.product_sets.get(body.product_set_id)
            if found is None:
                raise ProductSetNotFound(f"product set {body.product_set_id!r} does not exist")
            products = found["products"]
        elif body.products is not None:
            products = [p.model_dump() for p in body.products]
        record = await registry.create(seed, body.rule, body.modeling_type, body.horizon_ticks,
                                       strategy=body.strategy, seed_source=seed_source, product_list=products,
                                       product_set_id=body.product_set_id, scenario=scenario)
        request.state.session_id = record.session_id
        return record.info()

    @app.get("/scenarios", response_model=list[ScenarioSpecOut], tags=["sessions"],
             summary="Available scenarios and their parameters (to build the form)")
    async def list_scenarios() -> list[dict[str, Any]]:
        return [{"id": s.id, "name": s.name, "description": s.description,
                 "params": [vars(p) for p in s.params]} for s in scenarios.list_scenarios()]

    # ----- results (L5.7) -----

    @app.get("/runs", response_model=RunPage, tags=["runs-history"],
             summary="Saved runs, newest first; optional filters and simple paging (cursor)")
    async def list_runs(seed: int | None = None, strategy: str | None = None, rule: int | None = None,
                        product_set_id: str | None = None, scenario: str | None = Query(None, description="Scenario id"),
                        limit: int = Query(50, ge=1, le=500), cursor: str | None = None) -> Any:
        filters = {"seed": seed, "strategy": strategy, "rule": rule, "product_set_id": product_set_id,
                   "scenario_id": scenario}
        rows, next_cursor = await asyncio.to_thread(runtime.results.list_runs, filters, limit, cursor)
        return {"runs": rows, "next_cursor": next_cursor}

    @app.get("/runs/{run_id}", response_model=RunRecord, tags=["runs-history"], responses=errors.responses(404))
    async def get_run(run_id: str) -> Any:
        found = await asyncio.to_thread(runtime.results.get_run, run_id)
        if found is None:
            raise RunNotFound(f"run {run_id!r} does not exist")
        return found

    @app.get("/runs/{run_id}/decisions", response_model=list[dict[str, Any]], tags=["runs-history"],
             responses=errors.responses(404))
    async def get_run_decisions(run_id: str) -> Any:
        if await asyncio.to_thread(runtime.results.get_run, run_id) is None:
            raise RunNotFound(f"run {run_id!r} does not exist")
        return await asyncio.to_thread(runtime.results.get_decisions, run_id)

    # ----- product sets (L5.6) -----

    @app.post("/product-sets", response_model=ProductSet, status_code=201, tags=["product-sets"],
              summary="Save a product set (name and products in entry order, 1-1000)")
    async def create_product_set(body: ProductSetIn) -> Any:
        return runtime.product_sets.create(body.name, [p.model_dump() for p in body.products])

    @app.get("/product-sets", response_model=list[ProductSetSummary], tags=["product-sets"],
             summary="Saved product sets (without their products)")
    async def list_product_sets() -> Any:
        return runtime.product_sets.list()

    @app.post("/product-sets/parse-csv", response_model=ParsedCsv, tags=["product-sets"],
              summary="Turn a CSV (type, priority; , or ;; UTF-8, BOM allowed) into a validated list (not saved)",
              responses={422: {"description": "Errors by line: {code: csv_invalid, errors: [{line, error}]}"}})
    async def parse_product_csv(file: UploadFile = File(...)) -> Any:
        products, problems = parse_csv(await file.read())
        if problems:
            return JSONResponse({"code": "csv_invalid", "detail": f"{len(problems)} error(s) in the CSV",
                                 "errors": problems}, status_code=422)
        return {"products": products, **summary(products)}

    @app.post("/product-sets/generate", response_model=GeneratedProducts, tags=["product-sets"],
              summary="The products the model generates from a seed (fixed sequence); seed optional",
              responses=errors.responses(503))
    async def generate_products(body: GenerateRequest) -> Any:
        registry = runtime.require_ready()
        seed, seed_source = (body.seed, "user") if body.seed is not None else (random_seed(), "random")
        try:
            borrow = registry.pool.borrow_whatif()
            worker = borrow.__enter__()
        except NoFreeWorker:
            raise NoWorkerAvailable("no free worker to generate the products; retry in a few seconds") from None
        try:
            items = await registry.run(worker.request, "product_sequence", seed=seed, count=body.count)
        finally:
            borrow.__exit__(None, None, None)
        products = [{"type": t, "priority": int(p)} for t, p in items]
        return {"seed": seed, "seed_source": seed_source, "products": products, **summary(products)}

    @app.get("/product-sets/{set_id}", response_model=ProductSet, tags=["product-sets"],
             responses=errors.responses(404))
    async def get_product_set(set_id: str) -> Any:
        found = runtime.product_sets.get(set_id)
        if found is None:
            raise ProductSetNotFound(f"product set {set_id!r} does not exist")
        return found

    @app.put("/product-sets/{set_id}", response_model=ProductSet, tags=["product-sets"],
             summary="Replace a set (sessions already created keep their own copy)", responses=errors.responses(404))
    async def update_product_set(set_id: str, body: ProductSetIn) -> Any:
        found = runtime.product_sets.update(set_id, body.name, [p.model_dump() for p in body.products])
        if found is None:
            raise ProductSetNotFound(f"product set {set_id!r} does not exist")
        return found

    @app.delete("/product-sets/{set_id}", status_code=204, tags=["product-sets"], responses=errors.responses(404))
    async def delete_product_set(set_id: str) -> Response:
        if not runtime.product_sets.delete(set_id):
            raise ProductSetNotFound(f"product set {set_id!r} does not exist")
        return Response(status_code=204)

    @app.get("/product-sets/{set_id}/csv", tags=["product-sets"], response_class=PlainTextResponse,
             summary="Export a set as CSV (type,priority)", responses=errors.responses(404))
    async def export_product_set(set_id: str) -> Response:
        found = runtime.product_sets.get(set_id)
        if found is None:
            raise ProductSetNotFound(f"product set {set_id!r} does not exist")
        return Response(to_csv(found["products"]), media_type="text/csv",
                        headers={"Content-Disposition": f'attachment; filename="product-set-{set_id[:8]}.csv"'})

    @app.get("/sessions", response_model=list[SessionInfo], tags=["sessions"],
             summary="Every session: active, lost and expired")
    async def list_sessions() -> list[dict[str, Any]]:
        if runtime.registry is None:
            return []
        return [r.info() for r in runtime.registry.list()]

    @app.get("/sessions/{session_id}", response_model=SessionInfo, tags=["sessions"],
             summary="Session parameters and last known tick", responses=errors.responses(404))
    async def get_session(session_id: str = session_id_path) -> dict[str, Any]:
        return runtime.sessions.get(session_id).info()

    @app.post("/sessions/{session_id}/step", response_model=StepResult, tags=["sessions"],
              summary="Advance up to n ticks (stops at the horizon); 409 while running",
              responses=errors.responses(404, 409, 410, 500, 504))
    async def step(session_id: str = session_id_path,
                   n: int = Query(..., ge=1, le=MAX_STEP_TICKS, description=STEP_N_DESCRIPTION)) -> dict[str, Any]:
        registry = runtime.sessions
        record = registry.get(session_id)
        _require_not_running(record, "step")
        watched = len(record.hub) > 0
        record, result = await registry.call(session_id, "step", n=n, with_state=watched)
        registry.after_step(record, result)
        return {k: result[k] for k in ("ticks", "advanced", "finished")}

    @app.post("/sessions/{session_id}/reset", response_model=SessionInfo, tags=["sessions"],
              summary="Stop any run and run setup again with the same parameters",
              responses=errors.responses(404, 410, 500, 504))
    async def reset(session_id: str = session_id_path) -> dict[str, Any]:
        record, result = await runtime.sessions.call(session_id, "reset")
        record.apply_run(result)
        await runtime.sessions.after_reset(record, result)
        return record.info()

    # ----- continuous runs (L5.3) -----

    @app.post("/sessions/{session_id}/run", response_model=SessionInfo, tags=["runs"],
              summary="Run continuously: live (paced, streamed over WebSocket) or fast (no speed limit)",
              description="Allowed in idle, paused and while running (changes mode or speed). 409 when finished. "
                          "503 fast_run_limit when ACLOPI_MAX_FAST_RUNS fast runs are already in progress.",
              responses=errors.responses(404, 409, 410, 500, 503, 504))
    async def run(body: RunRequest, session_id: str = session_id_path) -> dict[str, Any]:
        speed = float(body.speed) if body.mode == "live" else None
        record = await runtime.sessions.start_run(session_id, body.mode, speed)
        return record.info()

    @app.post("/sessions/{session_id}/pause", response_model=SessionInfo, tags=["runs"],
              summary="Pause a running session (409 if it is not running)",
              responses=errors.responses(404, 409, 410, 500, 504))
    async def pause(session_id: str = session_id_path) -> dict[str, Any]:
        record, result = await runtime.sessions.call(session_id, "pause")
        record.apply_run(result)
        return record.info()

    @app.post("/sessions/{session_id}/resume", response_model=SessionInfo, tags=["runs"],
              summary="Resume a paused run with its mode and speed (409 if it is not paused)",
              responses=errors.responses(404, 409, 410, 500, 503, 504))
    async def resume(session_id: str = session_id_path) -> dict[str, Any]:
        record = await runtime.sessions.resume_run(session_id)
        return record.info()

    @app.get("/sessions/{session_id}/state", response_model=PlantState, tags=["sessions"],
             summary="Compact plant state (platform-state)", responses=errors.responses(404, 410, 500, 504))
    async def state(session_id: str = session_id_path) -> Any:
        _, result = await runtime.sessions.call(session_id, "state")
        return result

    @app.get("/sessions/{session_id}/events", response_model=list[Event], tags=["sessions"],
             summary="Events since the previous call; reading them empties the buffer",
             description="Not idempotent: each call returns the events recorded since the previous call "
                         "and empties the session's event buffer. 409 while running: then the events "
                         "travel over the WebSocket (/ws/sessions/{id}).",
             responses=errors.responses(404, 409, 410, 500, 504))
    async def events(session_id: str = session_id_path) -> Any:
        record = runtime.sessions.get(session_id)
        _require_not_running(record, "reading events")
        record, result = await runtime.sessions.call(session_id, "events")
        record.add_events(result)
        return result

    @app.get("/sessions/{session_id}/layout", response_model=PlantLayout, tags=["sessions"],
             summary="Static plant geometry (platform-layout)", responses=errors.responses(404, 410, 500, 504))
    async def layout(session_id: str = session_id_path) -> Any:
        _, result = await runtime.sessions.call(session_id, "layout")
        return result

    @app.get("/sessions/{session_id}/kpis", response_model=Kpis, tags=["sessions"],
             summary="KPIs of the current state (does not alter the simulation)",
             responses=errors.responses(404, 410, 500, 504))
    async def kpis(session_id: str = session_id_path) -> Any:
        _, result = await runtime.sessions.call(session_id, "kpis")
        return result

    @app.delete("/sessions/{session_id}", status_code=204, tags=["sessions"],
                summary="Close the session and free its worker", responses=errors.responses(404))
    async def delete_session(session_id: str = session_id_path) -> Response:
        await runtime.sessions.delete(session_id)
        return Response(status_code=204)

    # ----- decisions: candidates and what-if (L5.4) -----

    @app.get("/sessions/{session_id}/candidates", response_model=CandidatesResult, tags=["decisions"],
             summary="Candidate machines for a pending decision, with load and estimated wait",
             description="Computed from platform-state by aclopi.sim.candidates; the schema is Línea A's "
                         "CandidatesResult (aclopi/contracts/candidates.py, fields in docs/agent-status.md); "
                         "it does not alter the simulation. While the session runs it is served between blocks. "
                         "An invalid request (e.g. seq-mismatch) answers 200 with valid=false and the reason.",
             responses=errors.responses(401, 404, 410, 500, 504))
    async def candidates(session_id: str = session_id_path,
                         product: int = Query(..., ge=0, description="who of the product"),
                         seq: int = Query(..., ge=0, description="Index in ProductOperations of the operation to decide"),
                         _auth: None = Depends(require_agent_token)) -> Any:
        _, result = await runtime.sessions.call(session_id, "candidates", product=product, seq=seq)
        return result

    @app.post("/sessions/{session_id}/what-if", response_model=WhatIfResponse, tags=["decisions"],
              summary="Test two assignments of a pending decision in copies of the simulation",
              description="Rule 4 sessions only. One snapshot of the session (the run is not stopped), one copy "
                          "per option on a borrowed what-if worker, within the request's budget_ms. "
                          "status 'skipped' (no-free-worker, already-used, entry-beyond-cap) is a normal answer "
                          "(200). See docs/whatif.md.",
              responses=errors.responses(401, 404, 409, 410, 500, 504))
    async def what_if(body: WhatIfRequest, session_id: str = session_id_path,
                      _auth: None = Depends(require_agent_token)) -> Any:
        return await run_whatif(runtime.sessions, settings, session_id, body.product, body.seq, body.options,
                                body.max_ticks, body.budget_ms)

    @app.get("/sessions/{session_id}/metrics", response_model=SessionMetrics, tags=["decisions"],
             summary="Per-session metrics: what-ifs run, skipped, caps, stalls and timings",
             responses=errors.responses(404))
    async def session_metrics(session_id: str = session_id_path) -> Any:
        record = runtime.sessions.get(session_id, touch=False)
        return {"whatif": record.whatif_metrics.as_dict(), "decisions": runtime.sessions.decision_metrics(record)}

    @app.post("/sessions/{session_id}/next-machine", response_model=NextMachineResponse, tags=["decisions"],
              summary="The agent's decision for a pending request (rule 4)",
              description="Applied between blocks with platform-set-next-machine. 409 decision_not_pending "
                          "(registered as late) if the product already left the decision; 422 if the machine "
                          "cannot do the operation. See docs/agent-api.md.",
              responses=errors.responses(401, 404, 409, 410, 500, 504))
    async def next_machine(body: NextMachineRequest, session_id: str = session_id_path,
                           _auth: None = Depends(require_agent_token)) -> Any:
        return await runtime.sessions.next_machine(
            session_id, body.product, body.seq, body.machine, body.decision_level, body.reason,
            body.latencies.model_dump() if body.latencies else None)

    # ----- WebSocket and test page (L5.3) -----

    @app.websocket("/ws/sessions/{session_id}")
    async def ws_session(websocket: WebSocket, session_id: str) -> None:
        await stream_session(websocket, runtime, session_id)

    @app.get("/ui", include_in_schema=False)
    async def ui() -> FileResponse:
        return FileResponse(STATIC_DIR / "live.html", media_type="text/html")

    return app


def random_seed() -> int:
    """A seed in NetLogo's random-seed range, from secrets (never from the model's generator)."""
    return secrets.randbelow(2 ** 32) - 2 ** 31


def _require_not_running(record: Any, what: str) -> None:
    if record.status == "active" and record.running:
        raise InvalidRunState(f"{what} is not allowed while the session is {record.run_state}; pause it first",
                              record.session_id)


async def _pool_status(runtime: Runtime) -> list[dict[str, Any]]:
    if runtime.pool is None:
        return []
    return await anyio.to_thread.run_sync(runtime.pool.status, limiter=runtime.limiter)
