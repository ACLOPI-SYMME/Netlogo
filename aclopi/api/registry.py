"""SessionRegistry: the API's sessions on top of the WorkerPool.

- One asyncio.Lock per session: requests to a session run one at a time, in arrival order
  (asyncio.Lock is FIFO); different sessions run in parallel.
- Blocking WorkerHandle calls run in threads (anyio.to_thread), never on the event loop.
- A session is "active", "lost" (its worker crashed or hung) or "expired" (closed for
  inactivity). Lost and expired sessions stay listed (410 on access) until DELETE, or until they
  are older than TOMBSTONE_TTL_S, or there are more than MAX_TOMBSTONES.
- When a request times out the pool has already killed the worker; the slot stays "busy" until
  the monitor restarts it, so no new session gets a dead worker.

Continuous runs (L5.3): the worker pushes run_state / tick / progress / finished / run_error
messages (pool reader thread -> on_push via call_soon_threadsafe). Each push first updates the
session's cache (tick, platform-state text, KPIs, run state, event log) and then is published to
the session's WebSocket hub, so a snapshot built from the cache is never older than a message.

Inactivity: HTTP requests always count. A connected WebSocket client counts only while the
session is running (running_live / running_fast); in idle, paused or finished only HTTP counts,
so a forgotten browser tab does not hold a worker forever.

Watchdog: a running session that sends no push for RUN_WATCHDOG_S is treated as hung and its
worker is killed. A fast run waiting for the agent pushes heartbeats (runner.py), so only the
worker's own requests count, never the time the agent takes.

Decisions (L5.5, rule 4 with strategy b1 / b1b / agent): every decision request pushed by the
worker is sent to the agent (POST /decide, aclopi.api.agent) without waiting for it. The agent
answers with POST /sessions/{id}/next-machine (next_machine below). A fast run waiting for
decisions fails with reason agent_unavailable after ACLOPI_FAST_DECISION_TIMEOUT_S; a live run
never waits (the model applies rule 3: rule3-fallback, counted from the "assignments").

Scenarios (docs/scenarios.md): the session keeps its scenario ({id, params}, params completed by
validate_params) and the events applied so far (tick-0 events come in the setup/reset response;
later ones in the block pushes and step responses). Each one is added to the event log as type
"scenario" and published as a "scenario_event" message BEFORE the block's decision requests are sent
to the agent. They are saved with the run (scenario_events, scenario_summary).
"""

from __future__ import annotations

import asyncio
import functools
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable

import anyio

from aclopi.api.errors import (
    AgentUnavailable, DecisionNotPending, FastRunLimit, GatewayTimeout, InvalidOption, InvalidRunState,
    NoWorkerAvailable, Rule4Required, SessionGone, SessionNotFound, WorkerUnavailable,
)
from aclopi.contracts.agent import DECIDE_CONTEXT_FIELDS, DECIDING_STRATEGIES
from aclopi.api.hub import SessionHub, encode
from aclopi.api.product_sets import products_hash
from aclopi.api.results import new_run_id
from aclopi.api.whatif import WhatIfMetrics
from aclopi.logjson import session_id_var
from aclopi.workers.pool import WorkerPool
from aclopi.workers.protocol import (
    RUN_WATCHDOG_S, NoFreeWorker, SessionLost, WorkerCrashed, WorkerError, WorkerTimeout, timeout_scale,
)

TOMBSTONE_TTL_S = 24 * 3600.0
MAX_TOMBSTONES = 1000
RUNNING = ("running_live", "running_fast", "waiting_decision")
FAST_STATES = ("running_fast", "waiting_decision")
NOT_PENDING = {"product-finished", "stale-seq", "not-in-machine", "seq-mismatch"}
MAX_DECISION_LOG = 100_000
RECENT_EVENTS = 500
MAX_EVENT_LOG = 200_000  # per session; kept for persistence (L5.6)

logger = logging.getLogger(__name__)


@dataclass
class SessionRecord:
    session_id: str
    parameters: dict[str, Any]
    worker_slot: int | None
    created_at: float
    last_activity: float
    last_activity_mono: float
    hub: SessionHub
    ticks: int = 0
    finished: bool = False
    status: str = "active"  # active | lost | expired | deleted (deleted records are no longer listed)
    lost_reason: str | None = None
    closed_mono: float | None = None
    pending: int = 0
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    # continuous runs
    run_state: str = "idle"
    mode: str | None = None
    speed: float | None = None
    last_push_mono: float = 0.0
    # cache for snapshots
    state_raw: str | None = None
    state_tick: int = -1
    kpis: dict[str, Any] | None = None
    layout: dict[str, Any] | None = None
    events: list[dict[str, Any]] = field(default_factory=list)
    events_dropped: int = 0
    # what-if (L5.4): (product, seq) already tested in this run, and the session's metrics
    whatif_used: set[tuple[int, int]] = field(default_factory=set)
    whatif_metrics: WhatIfMetrics = field(default_factory=WhatIfMetrics)
    # decisions (L5.5)
    strategy: str | None = None
    run_reason: str | None = None
    pending_decisions: int = 0
    waiting_since: float | None = None  # fast run waiting for the agent (monotonic)
    decision_requests: dict[tuple[int, int], dict[str, Any]] = field(default_factory=dict)
    decision_log: list[dict[str, Any]] = field(default_factory=list)
    sources: dict[str, int] = field(default_factory=dict)  # Decision.Source counts
    decide_failed: int = 0
    agent: Any = None  # the API's AgentClient (for the warnings in info())
    last_run_id: str | None = None
    # product list (L5.6): a COPY of the list, so editing the set later does not change the session
    seed_source: str = "user"
    product_set_id: str | None = None
    product_list: list[dict[str, Any]] | None = None
    products_hash: str | None = None
    # the run in progress, saved to the results store when it finishes, fails or is stopped (L5.7)
    run_started_at: float | None = None
    run_mode: str | None = None
    run_decision_start: int = 0
    # scenario (docs/scenarios.md): {id, params} and the events applied in this run (from tick 0)
    scenario: dict[str, Any] = field(default_factory=lambda: {"id": "S0", "params": {}})
    scenario_events: list[dict[str, Any]] = field(default_factory=list)

    @property
    def deciding(self) -> bool:
        return int(self.parameters.get("rule", 0)) == 4 and self.strategy in DECIDING_STRATEGIES

    @property
    def running(self) -> bool:
        return self.run_state in RUNNING

    def info(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "status": self.status,
            "parameters": self.parameters,
            "ticks": self.ticks,
            "finished": self.finished,
            "run_state": self.run_state,
            "run_reason": self.run_reason,
            "mode": self.mode,
            "speed": self.speed,
            "strategy": self.strategy,
            "pending_decisions": self.pending_decisions,
            "watchers": len(self.hub),
            "warnings": ["agent_unavailable"] if self.deciding and not (self.agent and self.agent.available) else [],
            "seed_source": self.seed_source,
            "last_run_id": self.last_run_id,
            "product_set_id": self.product_set_id,
            "products_total": len(self.product_list) if self.product_list is not None else None,
            "products_hash": self.products_hash,
            "scenario": self.scenario,
            "scenario_summary": self.scenario_summary(),
            "lost_reason": self.lost_reason,
            "worker_slot": self.worker_slot,
            "created_at": self.created_at,
            "last_activity": self.last_activity,
        }

    def apply_run(self, result: dict[str, Any]) -> None:
        """Run fields from a worker response or a run_state push."""
        if "run_state" in result:
            self.run_state, self.mode, self.speed = result["run_state"], result.get("mode"), result.get("speed")
            self.finished = self.run_state == "finished"
            self.run_reason = result.get("reason")
            self.pending_decisions = int(result.get("pending_decisions") or 0)
            if self.run_state != "waiting_decision":
                self.waiting_since = None
        tick = result.get("ticks", result.get("tick"))
        if tick is not None:
            self.ticks = int(tick)

    def scenario_summary(self) -> dict[str, int]:
        applied = sum(1 for e in self.scenario_events if e["applied"])
        return {"applied": applied, "skipped": len(self.scenario_events) - applied}

    def add_scenario_events(self, applied: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
        """Keep the applied events (run and event log); returns them, to be published."""
        applied = list(applied or [])
        self.scenario_events.extend(applied)
        self.add_events(applied)
        return applied

    def add_events(self, events: list[dict[str, Any]]) -> None:
        self.events.extend(events)
        if len(self.events) > MAX_EVENT_LOG:
            extra = len(self.events) - MAX_EVENT_LOG
            del self.events[:extra]
            self.events_dropped += extra


class SessionRegistry:
    def __init__(
        self,
        pool: WorkerPool,
        idle_timeout_s: float,
        limiter: anyio.CapacityLimiter,
        max_fast_runs: int = 1,
        ws_queue: int = 32,
        tombstone_ttl_s: float = TOMBSTONE_TTL_S,
        max_tombstones: int = MAX_TOMBSTONES,
    ) -> None:
        self.pool = pool
        self.idle_timeout_s = idle_timeout_s
        self.limiter = limiter
        self.max_fast_runs = max_fast_runs
        self.ws_queue = ws_queue
        self.tombstone_ttl_s = tombstone_ttl_s
        self.max_tombstones = max_tombstones
        self._records: dict[str, SessionRecord] = {}
        self._fast_reservations = 0
        self.loop: asyncio.AbstractEventLoop | None = None
        self.agent: Any = None  # aclopi.api.agent.AgentClient, set by the app
        self.fast_decision_timeout_s = 90.0
        self._tasks: set[asyncio.Task[Any]] = set()
        self.results: Any = None  # aclopi.api.results.ResultsStore, set by the app

    async def run(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        """Run a blocking call in a thread (contextvars, hence session_id, are copied)."""
        return await anyio.to_thread.run_sync(functools.partial(fn, *args, **kwargs), limiter=self.limiter)

    # ----- callbacks from pool threads -----

    def attach(self, loop: asyncio.AbstractEventLoop) -> None:
        self.loop = loop

    def push_from_thread(self, session_id: str, event: str, data: Any) -> None:
        if self.loop is not None and not self.loop.is_closed():
            self.loop.call_soon_threadsafe(self.on_push, session_id, event, data)

    def lost_from_thread(self, session_id: str, reason: str) -> None:
        if self.loop is not None and not self.loop.is_closed():
            self.loop.call_soon_threadsafe(self.on_lost, session_id, reason)

    # ----- queries -----

    def active_count(self) -> int:
        return sum(1 for r in self._records.values() if r.status == "active")

    def list(self) -> list[SessionRecord]:
        self.refresh_lost()
        self.prune()
        return sorted(self._records.values(), key=lambda r: r.created_at)

    def get(self, session_id: str, touch: bool = True) -> SessionRecord:
        self.refresh_lost()
        record = self._records.get(session_id)
        if record is None or record.status == "deleted":
            raise SessionNotFound(f"session {session_id!r} does not exist", session_id)
        if touch and record.status == "active":
            self._touch(record)
        return record

    # ----- lifecycle -----

    async def create(self, seed: int, rule: int, modeling_type: str, horizon_ticks: int,
                     strategy: str | None = None, seed_source: str = "user",
                     product_list: list[dict[str, Any]] | None = None,
                     product_set_id: str | None = None,
                     scenario: dict[str, Any] | None = None) -> SessionRecord:
        """scenario: {id, params} already completed by aclopi.sim.scenarios.validate_params."""
        scenario = scenario or {"id": "S0", "params": {}}
        session_id = uuid.uuid4().hex
        session_id_var.set(session_id)
        try:
            handle = self.pool.acquire_session(session_id)
        except NoFreeWorker:
            raise NoWorkerAvailable(
                f"all {self.pool.n_session} session workers are busy; close a session (DELETE /sessions/{{id}}) "
                "or wait until one is closed"
            ) from None
        try:
            result = await self.run(handle.request, "setup", seed=seed, rule=rule, modeling_type=modeling_type,
                                    horizon_ticks=horizon_ticks, session_id=session_id,
                                    product_list=[[p["type"], p["priority"]] for p in product_list] if product_list else None,
                                    scenario=scenario)
        except WorkerTimeout as exc:
            # The pool killed the worker; it frees the slot itself after the restart.
            self.pool.release_session(session_id)
            raise GatewayTimeout(f"setup did not finish in time: {exc}; the worker is being restarted", session_id) from None
        except WorkerCrashed as exc:
            self.pool.release_session(session_id)
            raise WorkerUnavailable(f"the worker crashed during setup ({exc}); it is being restarted, retry", session_id) from None
        except BaseException:
            self.pool.release_session(session_id)
            raise
        now = time.time()
        record = SessionRecord(
            session_id=session_id,
            parameters={"seed": seed, "rule": rule, "modeling_type": modeling_type, "horizon_ticks": horizon_ticks},
            worker_slot=handle.slot,
            created_at=now,
            last_activity=now,
            last_activity_mono=time.monotonic(),
            hub=SessionHub(session_id, self.ws_queue),
            strategy=strategy,
            agent=self.agent,
            seed_source=seed_source,
            product_set_id=product_set_id,
            product_list=[dict(p) for p in product_list] if product_list else None,
            products_hash=products_hash(product_list) if product_list else None,
            scenario={"id": scenario["id"], "params": dict(scenario.get("params") or {})},
        )
        record.apply_run(result)
        record.add_scenario_events(result.get("scenario_events"))  # tick 0: nobody is watching yet
        self._records[session_id] = record
        logger.info("Session created on worker %s", handle.config.name, extra={"worker": handle.config.name})
        return record

    async def call(self, session_id: str, op: str, touch: bool = True, **args: Any) -> tuple[SessionRecord, Any]:
        """Run one worker operation for a session, in order with the session's other requests."""
        record = self.get(session_id, touch=touch)
        self._ensure_active(record)
        record.pending += 1
        try:
            async with record.lock:
                self.refresh_lost()
                self._ensure_active(record)
                if touch:
                    self._touch(record)
                try:
                    handle = self.pool.session(session_id)
                except SessionLost as exc:
                    self._close(record, "lost", str(exc).split(": ", 1)[-1])
                    raise self._gone(record) from None
                except KeyError:
                    self._close(record, "lost", "its worker no longer holds this session")
                    raise self._gone(record) from None
                try:
                    result = await self.run(handle.request, op, **args)
                except WorkerCrashed as exc:
                    reason = self.pool.lost_sessions().get(session_id) or str(exc)
                    self._close(record, "lost", reason)
                    raise self._gone(record) from None
                except WorkerTimeout as exc:
                    self._close(record, "lost", f"worker unresponsive ({exc}); it was restarted")
                    raise GatewayTimeout(f"{exc}; the worker is being restarted and this session is lost", session_id) from None
                except WorkerError as exc:
                    if exc.error_type == "RunStateError":
                        raise InvalidRunState(exc.message, session_id) from None
                    raise
                if touch:
                    self._touch(record)
                return record, result
        finally:
            record.pending -= 1

    async def delete(self, session_id: str) -> None:
        record = self.get(session_id, touch=False)
        if record.status == "active":
            async with record.lock:
                if record.status == "active":
                    await self._stop_worker(record)
                    self.pool.release_session(session_id)
        else:
            self.pool.release_session(session_id)  # clears the pool's lost entry, if any
        self.save_run(record, "stopped", "deleted")
        record.status = "deleted"
        record.hub.close_all("session_deleted", "the session was closed (DELETE)")
        self._records.pop(session_id, None)
        logger.info("Session deleted", extra={"session_id": session_id})

    def close_all(self) -> None:
        for record in self._records.values():
            if record.status == "active":
                record.status = "deleted"
            record.hub.close_all("server_shutdown", "the platform is stopping")

    async def _stop_worker(self, record: SessionRecord) -> None:
        """Stop any run before the worker is released (it would keep running for nobody)."""
        try:
            handle = self.pool.session(record.session_id)
            await self.run(handle.request, "stop")
        except Exception as exc:  # noqa: BLE001 - releasing must go on; setup stops runs anyway
            logger.warning("Could not stop the run before releasing the worker: %s", exc,
                           extra={"session_id": record.session_id})

    # ----- continuous runs -----

    async def start_run(self, session_id: str, mode: str, speed: float | None) -> SessionRecord:
        record = self.get(session_id)
        self._ensure_active(record)
        if record.deciding and mode == "fast" and not (self.agent is not None and self.agent.available):
            raise AgentUnavailable(
                f"a fast run with strategy {record.strategy!r} waits for the agent at every decision, and the "
                f"agent is {self.agent.status if self.agent else 'not configured'}", session_id)
        reserve = mode == "fast" and record.run_state not in FAST_STATES
        if reserve:
            self._check_fast_limit(record)
            self._fast_reservations += 1
        try:
            new_run = record.run_state == "idle"
            record, result = await self.call(session_id, "run", mode=mode, speed=speed,
                                             decisions=record.deciding, rule4=int(record.parameters["rule"]) == 4)
            if new_run or record.run_started_at is None:
                record.run_started_at, record.run_decision_start = time.time(), len(record.decision_log)
            record.run_mode = mode
        finally:
            if reserve:
                self._fast_reservations -= 1
        record.apply_run(result)
        record.last_push_mono = time.monotonic()
        return record

    async def resume_run(self, session_id: str) -> SessionRecord:
        record = self.get(session_id)
        self._ensure_active(record)
        reserve = record.run_state == "paused" and record.mode == "fast"
        if reserve:
            self._check_fast_limit(record)
            self._fast_reservations += 1
        try:
            record, result = await self.call(session_id, "resume")
        finally:
            if reserve:
                self._fast_reservations -= 1
        record.apply_run(result)
        record.last_push_mono = time.monotonic()
        return record

    def _check_fast_limit(self, record: SessionRecord) -> None:
        running = sum(1 for r in self._records.values()
                      if r.status == "active" and r.run_state in FAST_STATES and r is not record)
        if running + self._fast_reservations >= self.max_fast_runs:
            raise FastRunLimit(
                f"{self.max_fast_runs} fast run(s) already in progress (ACLOPI_MAX_FAST_RUNS); "
                "wait until one finishes or pause it", record.session_id)

    def on_push(self, session_id: str, event: str, data: Any) -> None:
        record = self._records.get(session_id)
        if record is None or record.status != "active":
            return
        record.last_push_mono = time.monotonic()
        hub = record.hub
        # Scenario events first: registered and published before the block's decision requests go out.
        if isinstance(data, dict):
            self._publish_scenario(record, data.pop("scenario_events", None))
        self._decision_push(record, event, data)
        if event == "tick":
            state = data.pop("state", None)
            record.ticks = int(data["tick"])
            if state is not None:
                record.state_raw, record.state_tick = state, record.ticks
            if data.get("kpis") is not None:
                record.kpis = data["kpis"]
            record.add_events(data.get("events") or [])
            hub.publish({"type": "tick", "source": "run", **data}, raw={"state": state} if state else None)
        elif event == "progress":
            state = data.pop("state", None)  # at most once a second (runner.py)
            record.ticks = int(data["tick"])
            if state is not None:
                record.state_raw, record.state_tick = state, record.ticks
            if data.get("kpis") is not None:
                record.kpis = data["kpis"]
            record.add_events(data.get("events") or [])
            hub.publish({"type": "progress", **data}, raw={"state": state} if state else None)
        elif event == "run_state":
            record.apply_run(data)
            hub.publish({"type": "run_state", **data})
            if record.run_state == "failed":
                self.save_run(record, "failed", record.run_reason)
        elif event == "finished":
            record.ticks, record.finished = int(data["tick"]), True
            record.kpis = data.get("kpis")
            hub.publish({"type": "finished", **data})
            self.save_run(record, "finished", data.get("reason"))
        elif event == "run_error":
            logger.error("Run stopped by an error in the worker: %s", data.get("error"),
                         extra={"session_id": session_id})
            hub.publish({"type": "run_error", **data})

    # ----- scenarios -----

    @staticmethod
    def _publish_scenario(record: SessionRecord, applied: list[dict[str, Any]] | None) -> None:
        for ev in record.add_scenario_events(applied):
            record.hub.publish({"type": "scenario_event", "tick": ev["tick"], "event": ev})

    # ----- decisions (L5.5) -----

    def _decision_push(self, record: SessionRecord, event: str, data: Any) -> None:
        """Take the decision parts out of a push: send the requests to the agent, count sources."""
        if not isinstance(data, dict):
            return
        for a in data.pop("assignments", None) or []:
            record.sources[a["source"]] = record.sources.get(a["source"], 0) + 1
        # The requests travel in the block's tick/progress push; "decision_required" (fast mode)
        # repeats them only to say that the run now waits: it starts the timeout, nothing is resent.
        requests = data.pop("decision_requests", None) or []
        if event == "decision_required":
            record.waiting_since = record.waiting_since or time.monotonic()
        for req in requests:
            self._request_decision(record, req)

    def _request_decision(self, record: SessionRecord, req: dict[str, Any]) -> None:
        live = record.run_state == "running_live"
        payload = {
            "session_id": record.session_id, "product": int(req["who"]), "seq": int(req["seq"]),
            "strategy": record.strategy, "mode": "live" if live else "fast",
            "ticks_per_second": round(32.0 * (record.speed or 1.0), 3) if live else None,
            # Simulated.Time advances 0.31 per tick, rounded to 2 decimals (Product.Movement)
            "tick": int(req["tick"]), "simulated_time": round(0.31 * int(req["tick"]), 2),
            "operation": req.get("operation"), "origin": req.get("origin"), "candidates": req.get("candidates"),
            # Product context and plant summary, read in the worker when the request was collected
            **{k: req.get(k) for k in DECIDE_CONTEXT_FIELDS},
        }
        record.decision_requests[(payload["product"], payload["seq"])] = {
            "sent_mono": time.monotonic(), "tick": payload["tick"], "mode": payload["mode"]}
        if self.agent is None:
            return

        async def send() -> None:
            if not await self.agent.decide(payload):
                record.decide_failed += 1

        task = asyncio.ensure_future(send())
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def next_machine(self, session_id: str, product: int, seq: int, machine: str, level: str,
                           reason: str | None, latencies: dict[str, Any] | None) -> dict[str, Any]:
        record = self.get(session_id)
        self._ensure_active(record)
        if int(record.parameters.get("rule", 0)) != 4:
            raise Rule4Required("next-machine needs a session with rule 4", session_id)
        record, out = await self.call(session_id, "next_machine", product=product, seq=seq, machine=machine)
        result = out["result"]
        request = record.decision_requests.get((product, seq))
        entry = {
            "tick": int(out["tick"]), "request_tick": request["tick"] if request else None, "product": product,
            "seq": seq, "strategy": record.strategy, "decision_level": level, "machine": machine,
            "reason": reason, "latency_ms": round(1000 * (time.monotonic() - request["sent_mono"]), 1) if request else None,
            "agent_latencies": latencies, "late": False, "result": result,
        }
        if result == "ok":
            record.decision_requests.pop((product, seq), None)
            record.apply_run(out)
            self._log_decision(record, entry)
            record.hub.publish({"type": "decision", "product": product, "seq_op": seq, "machine": machine,
                                "level": level, "late": False, "latency_ms": entry["latency_ms"], "tick": entry["tick"]})
            return {"applied": True, "tick": entry["tick"], "late": False, "run_state": record.run_state,
                    "pending_decisions": record.pending_decisions}
        if result in NOT_PENDING:
            entry["late"] = True
            record.decision_requests.pop((product, seq), None)
            self._log_decision(record, entry)
            record.hub.publish({"type": "decision", "product": product, "seq_op": seq, "machine": machine,
                                "level": level, "late": True, "latency_ms": entry["latency_ms"], "tick": entry["tick"]})
            raise DecisionNotPending(f"the decision is no longer pending ({result}): registered as late", session_id)
        if result == "rule4-not-active":
            raise Rule4Required("next-machine needs a session with rule 4", session_id)
        raise InvalidOption(f"invalid next machine: {result}", session_id)

    def _log_decision(self, record: SessionRecord, entry: dict[str, Any]) -> None:
        record.decision_log.append(entry)
        if len(record.decision_log) > MAX_DECISION_LOG:
            del record.decision_log[: len(record.decision_log) - MAX_DECISION_LOG]

    def decision_metrics(self, record: SessionRecord) -> dict[str, Any]:
        applied = [d for d in record.decision_log if not d["late"]]
        levels: dict[str, int] = {}
        for d in applied:
            levels[d["decision_level"]] = levels.get(d["decision_level"], 0) + 1
        lat = sorted(d["latency_ms"] for d in applied if d["latency_ms"] is not None)
        multi = record.sources.get("agent", 0) + record.sources.get("rule3-fallback", 0)
        return {
            "strategy": record.strategy,
            "requests_sent": len(record.decision_log) + len(record.decision_requests),
            "decide_failed": record.decide_failed,
            "applied": len(applied),
            "late": sum(1 for d in record.decision_log if d["late"]),
            "unanswered": len(record.decision_requests),
            "by_level": levels,
            "by_level_pct": {k: round(100 * v / len(applied), 1) for k, v in levels.items()} if applied else {},
            "sources": dict(record.sources),
            "rule3_fallback_pct": round(100 * record.sources.get("rule3-fallback", 0) / multi, 1) if multi else None,
            "single_option": record.sources.get("single-option", 0),
            "latency_ms": {"mean": round(sum(lat) / len(lat), 1), "p95": lat[min(len(lat) - 1, int(round(0.95 * (len(lat) - 1))))],
                           "max": lat[-1], "n": len(lat)} if lat else None,
            "log": [{k: d[k] for k in ("tick", "request_tick", "product", "seq", "machine", "decision_level", "late",
                                       "latency_ms", "reason")} for d in record.decision_log],
        }

    # ----- results (L5.7) -----

    def save_run(self, record: SessionRecord, status: str, reason: str | None) -> None:
        """Save the run in progress (if any) to the results store, in a thread; never raises."""
        if record.run_started_at is None:
            return
        kpis = record.kpis or {}
        # "seq" is the stored decisions' sort key (their order in the run): the operation's seq is seq_op
        decisions = [{**{k: v for k, v in d.items() if k != "seq"}, "seq_op": d["seq"]}
                     for d in record.decision_log[record.run_decision_start:]]
        metrics = {k: v for k, v in self.decision_metrics(record).items() if k != "log"}
        run = {
            "run_id": new_run_id(), "session_id": record.session_id, "created_at": record.run_started_at,
            "finished_at": time.time(), "status": status, "reason": reason, "ticks": record.ticks,
            "rule": int(record.parameters["rule"]), "strategy": record.strategy,
            "seed": int(record.parameters["seed"]), "seed_source": record.seed_source,
            "modeling_type": record.parameters.get("modeling_type"),
            "horizon_ticks": int(record.parameters["horizon_ticks"]), "mode": record.run_mode,
            "product_set_id": record.product_set_id, "products_hash": record.products_hash,
            "products": record.product_list,
            "scenario_id": record.scenario["id"], "scenario": record.scenario,
            "scenario_events": [dict(e) for e in record.scenario_events],
            "scenario_summary": record.scenario_summary(),
            "kpis": {k: kpis.get(k) for k in ("ticks", "finished", "created", "wip", "work_completed", "mean_flow_time",
                                              "throughput", "products_total", "all_done", "makespan_ticks",
                                              "makespan_time")},
            "utilization": kpis.get("utilization"),
            "decisions_summary": metrics,
            "whatif_summary": record.whatif_metrics.as_dict(),
        }
        record.run_started_at = None
        record.last_run_id = run["run_id"]
        if self.results is None:
            return
        store = self.results

        def write() -> None:
            try:
                store.save_run(run, [dict(d) for d in decisions])
                logger.info("Run %s saved (%s)", run["run_id"], status, extra={"session_id": record.session_id})
            except Exception:  # noqa: BLE001 - saving must never break the platform
                logger.exception("Could not save run %s", run["run_id"], extra={"session_id": record.session_id})

        if self.loop is not None and self.loop.is_running():
            future = self.loop.run_in_executor(None, write)
            self._tasks.add(future)  # type: ignore[arg-type]
            future.add_done_callback(self._tasks.discard)  # type: ignore[arg-type]
        else:
            write()

    def on_lost(self, session_id: str, reason: str) -> None:
        record = self._records.get(session_id)
        if record is not None and record.status == "active":
            self._close(record, "lost", reason)

    def watchdog(self) -> None:
        """Kill the worker of a running session that has sent nothing for RUN_WATCHDOG_S."""
        limit = RUN_WATCHDOG_S * timeout_scale()
        now = time.monotonic()
        for record in list(self._records.values()):
            if (record.status == "active" and record.run_state == "waiting_decision" and record.waiting_since
                    and now - record.waiting_since > self.fast_decision_timeout_s):
                record.waiting_since = None  # one failure per stall
                logger.error("No decision from the agent for %.0f s: the fast run fails (agent_unavailable)",
                             self.fast_decision_timeout_s, extra={"session_id": record.session_id})
                task = asyncio.ensure_future(self._fail_run(record.session_id, "agent_unavailable"))
                self._tasks.add(task)
                task.add_done_callback(self._tasks.discard)
            if record.status == "active" and record.running and now - record.last_push_mono > limit:
                reason = f"no progress from the worker for {now - record.last_push_mono:.0f} s while {record.run_state}"
                record.last_push_mono = now  # one kill per stall
                if self.loop is not None:
                    self.loop.run_in_executor(None, self.pool.kill_session_worker, record.session_id, reason)

    # ----- snapshots for WebSocket clients -----

    async def refresh_cache(self, session_id: str) -> SessionRecord:
        """Bring the snapshot cache up to date from the worker (without counting as activity)."""
        record = self.get(session_id, touch=False)
        if record.layout is None:
            record, layout = await self.call(session_id, "layout", touch=False)
            record.layout = layout
        record, snap = await self.call(session_id, "snapshot", touch=False)
        tick = int(snap["tick"])
        if tick >= record.state_tick or record.state_raw is None:
            record.state_raw, record.state_tick = snap["state"], tick
            record.kpis = snap["kpis"]
            record.ticks = max(record.ticks, tick)
        return record

    def snapshot_text(self, record: SessionRecord) -> str:
        """The snapshot message, from the cache (synchronous: consistent with the published seq)."""
        message = {
            "type": "snapshot",
            "seq": record.hub.seq,
            "session": record.info(),
            "tick": record.ticks,
            "state_tick": record.state_tick if record.state_raw is not None else None,
            "layout": record.layout,
            "kpis": record.kpis,
            "recent_events": record.events[-RECENT_EVENTS:],
            "scenario": record.scenario,
            "scenario_events": record.scenario_events,  # every event applied so far in this run
        }
        return encode(message, raw={"state": record.state_raw} if record.state_raw else None)

    def after_step(self, record: SessionRecord, result: dict[str, Any]) -> None:
        """A manual step: tell watching clients (state included when someone is watching)."""
        record.ticks = int(result["ticks"])
        if result.get("finished"):
            record.finished = True
        self._publish_scenario(record, result.get("scenario_events"))
        state = result.get("state")
        if state is not None:
            record.state_raw, record.state_tick = state, record.ticks
            record.hub.publish({"type": "tick", "source": "step", "tick": record.ticks,
                                "advanced": result["advanced"], "events": []}, raw={"state": state})

    async def after_reset(self, record: SessionRecord, result: dict[str, Any] | None = None) -> None:
        """Reset: new run from tick 0 (tick-0 scenario events applied again, from the reset response);
        watching clients get a fresh snapshot."""
        self.save_run(record, "stopped", "reset")
        record.events.clear()
        record.scenario_events.clear()
        record.add_scenario_events((result or {}).get("scenario_events"))
        record.whatif_used.clear()  # a new run: the same product ids come back
        record.state_raw, record.state_tick, record.kpis = None, -1, None
        record.finished = False
        if len(record.hub):
            await self.refresh_cache(record.session_id)
            record.hub.resync_all("reset")

    # ----- lost and idle sessions -----

    def refresh_lost(self) -> None:
        """Mark as lost the sessions whose worker died (detected by the pool's monitor)."""
        for session_id, reason in self.pool.lost_sessions().items():
            record = self._records.get(session_id)
            if record is not None and record.status == "active":
                self._close(record, "lost", reason)
            else:
                self.pool.release_session(session_id)

    async def sweep(self) -> None:
        """Close idle sessions and prune old tombstones (see the module docstring)."""
        self.refresh_lost()
        now = time.monotonic()
        for record in list(self._records.values()):
            if record.status != "active":
                continue
            if record.running and len(record.hub) > 0:
                self._touch(record)  # watched while running: counts as activity
                continue
            if (record.pending == 0 and not record.lock.locked()
                    and now - record.last_activity_mono > self.idle_timeout_s):
                async with record.lock:
                    if record.status != "active":
                        continue
                    if record.run_state != "idle":
                        await self._stop_worker(record)
                    self._close(record, "expired", f"closed after {self.idle_timeout_s:g} s without requests")
        self.prune()

    async def _fail_run(self, session_id: str, reason: str) -> None:
        try:
            record, out = await self.call(session_id, "fail_run", touch=False, reason=reason)
            record.apply_run(out)
        except Exception:  # noqa: BLE001
            logger.exception("Could not fail the run", extra={"session_id": session_id})

    async def sweep_loop(self) -> None:
        interval = min(60.0, max(self.idle_timeout_s / 4, 0.5))
        while True:
            await asyncio.sleep(interval)
            try:
                await self.sweep()
            except Exception:  # noqa: BLE001 - the sweeper must keep running
                logger.exception("Idle-session sweep failed")

    async def watchdog_loop(self) -> None:
        while True:
            await asyncio.sleep(1.0)
            try:
                self.watchdog()
            except Exception:  # noqa: BLE001
                logger.exception("Run watchdog failed")

    def prune(self) -> None:
        now = time.monotonic()
        closed = [r for r in self._records.values() if r.closed_mono is not None and r.status in ("lost", "expired")]
        for record in closed:
            if now - record.closed_mono > self.tombstone_ttl_s:  # type: ignore[operator]
                self._records.pop(record.session_id, None)
        closed = sorted((r for r in closed if r.session_id in self._records), key=lambda r: r.closed_mono or 0.0)
        for record in closed[: max(len(closed) - self.max_tombstones, 0)]:
            self._records.pop(record.session_id, None)

    # ----- helpers -----

    def _touch(self, record: SessionRecord) -> None:
        record.last_activity = time.time()
        record.last_activity_mono = time.monotonic()

    def _close(self, record: SessionRecord, status: str, reason: str) -> None:
        self.save_run(record, "stopped", f"{status}: {reason}")
        record.status, record.lost_reason, record.closed_mono = status, reason, time.monotonic()
        record.run_state, record.mode, record.speed = ("finished" if record.finished else "idle"), None, None
        self.pool.release_session(record.session_id)
        code = "session_lost" if status == "lost" else "session_expired"
        record.hub.close_all(code, reason)
        log = logger.error if status == "lost" else logger.info
        log("Session %s: %s", status, reason, extra={"session_id": record.session_id})

    def _ensure_active(self, record: SessionRecord) -> None:
        if record.status == "deleted":
            raise SessionNotFound(f"session {record.session_id!r} does not exist", record.session_id)
        if record.status != "active":
            raise self._gone(record)

    @staticmethod
    def _gone(record: SessionRecord) -> SessionGone:
        if record.status == "expired":
            return SessionGone(f"session {record.session_id} was closed: {record.lost_reason}", record.session_id,
                               "session_expired")
        return SessionGone(f"session {record.session_id} was lost: {record.lost_reason}", record.session_id,
                           "session_lost")
