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
import logging
import os
import re
import time
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Callable

import anyio
from fastapi import FastAPI, Path, Query, Request, Response
from fastapi.responses import JSONResponse

from aclopi.api import errors
from aclopi.api.errors import PlatformStarting, WorkerUnavailable
from aclopi.api.instance_lock import InstanceLock
from aclopi.api.models import (
    STEP_N_DESCRIPTION, Event, Health, Kpis, PlantLayout, PlantState, Probe, SessionCreate, SessionInfo, StepResult,
)
from aclopi.api.registry import SessionRegistry
from aclopi.api.settings import Settings
from aclopi.logjson import session_id_var
from aclopi.workers.pool import WorkerPool
from aclopi.workers.protocol import MAX_STEP_TICKS, set_timeout_scale

API_VERSION = "0.2.0"
THREAD_LIMIT = 32
SESSION_PATH = re.compile(r"^/sessions/([^/]+)")
QUIET_PATHS = ("/health",)

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
        self._tasks: list[asyncio.Task[Any]] = []

    async def start(self) -> None:
        self.lock.acquire()
        set_timeout_scale(self.settings.timeout_scale)
        self.pool = self.pool_factory(self.settings)
        if self.pool.debug:
            raise RuntimeError("the API must never run a pool with debug=True")
        self.registry = SessionRegistry(self.pool, self.settings.session_idle_timeout_s, self.limiter)
        self._tasks = [
            asyncio.create_task(self._start_pool(), name="pool-start"),
            asyncio.create_task(self.registry.sweep_loop(), name="idle-sweeper"),
        ]
        logger.info("API starting: %d session + %d what-if workers", self.settings.n_session_workers,
                    self.settings.n_whatif_workers, extra={"phase": self.phase})

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
        sweeper = self._tasks[1] if len(self._tasks) > 1 else None
        if sweeper is not None:
            sweeper.cancel()
        if self.registry is not None:
            self.registry.close_all()
        if self.pool is not None:
            await anyio.to_thread.run_sync(self.pool.shutdown)
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
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
        }

    # ----- sessions -----

    session_id_path = Path(description="Session id returned by POST /sessions")

    @app.post("/sessions", response_model=SessionInfo, status_code=201, tags=["sessions"],
              summary="Create a session on a free worker and run setup",
              responses=errors.responses(500, 503, 504))
    async def create_session(body: SessionCreate, request: Request) -> dict[str, Any]:
        registry = runtime.require_ready()
        record = await registry.create(body.seed, body.rule, body.modeling_type, body.horizon_ticks)
        request.state.session_id = record.session_id
        return record.info()

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
              summary="Advance up to n ticks (stops at the horizon)",
              responses=errors.responses(404, 410, 500, 504))
    async def step(session_id: str = session_id_path,
                   n: int = Query(..., ge=1, le=MAX_STEP_TICKS, description=STEP_N_DESCRIPTION)) -> dict[str, Any]:
        record, result = await runtime.sessions.call(session_id, "step", n=n)
        record.ticks, record.finished = int(result["ticks"]), bool(result["finished"])
        return result

    @app.post("/sessions/{session_id}/reset", response_model=SessionInfo, tags=["sessions"],
              summary="Run setup again with the same parameters", responses=errors.responses(404, 410, 500, 504))
    async def reset(session_id: str = session_id_path) -> dict[str, Any]:
        record, result = await runtime.sessions.call(session_id, "reset")
        record.ticks, record.finished = int(result["ticks"]), False
        return record.info()

    @app.get("/sessions/{session_id}/state", response_model=PlantState, tags=["sessions"],
             summary="Compact plant state (platform-state)", responses=errors.responses(404, 410, 500, 504))
    async def state(session_id: str = session_id_path) -> Any:
        _, result = await runtime.sessions.call(session_id, "state")
        return result

    @app.get("/sessions/{session_id}/events", response_model=list[Event], tags=["sessions"],
             summary="Events since the previous call; reading them empties the buffer",
             description="Not idempotent: each call returns the events recorded since the previous call "
                         "and empties the session's event buffer.",
             responses=errors.responses(404, 410, 500, 504))
    async def events(session_id: str = session_id_path) -> Any:
        _, result = await runtime.sessions.call(session_id, "events")
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

    return app


async def _pool_status(runtime: Runtime) -> list[dict[str, Any]]:
    if runtime.pool is None:
        return []
    return await anyio.to_thread.run_sync(runtime.pool.status, limiter=runtime.limiter)
