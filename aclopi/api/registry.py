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
worker is killed (L5.5: a session waiting for the agent must push heartbeats, see runner.py).
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
    FastRunLimit, GatewayTimeout, InvalidRunState, NoWorkerAvailable, SessionGone, SessionNotFound,
    WorkerUnavailable,
)
from aclopi.api.hub import SessionHub, encode
from aclopi.api.whatif import WhatIfMetrics
from aclopi.logjson import session_id_var
from aclopi.workers.pool import WorkerPool
from aclopi.workers.protocol import (
    RUN_WATCHDOG_S, NoFreeWorker, SessionLost, WorkerCrashed, WorkerError, WorkerTimeout, timeout_scale,
)

TOMBSTONE_TTL_S = 24 * 3600.0
MAX_TOMBSTONES = 1000
RUNNING = ("running_live", "running_fast")
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
            "mode": self.mode,
            "speed": self.speed,
            "watchers": len(self.hub),
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
        tick = result.get("ticks", result.get("tick"))
        if tick is not None:
            self.ticks = int(tick)

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

    async def create(self, seed: int, rule: int, modeling_type: str, horizon_ticks: int) -> SessionRecord:
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
                                    horizon_ticks=horizon_ticks, session_id=session_id)
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
        )
        record.apply_run(result)
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
        reserve = mode == "fast" and record.run_state != "running_fast"
        if reserve:
            self._check_fast_limit(record)
            self._fast_reservations += 1
        try:
            record, result = await self.call(session_id, "run", mode=mode, speed=speed)
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
                      if r.status == "active" and r.run_state == "running_fast" and r is not record)
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
        elif event == "finished":
            record.ticks, record.finished = int(data["tick"]), True
            record.kpis = data.get("kpis")
            hub.publish({"type": "finished", **data})
        elif event == "run_error":
            logger.error("Run stopped by an error in the worker: %s", data.get("error"),
                         extra={"session_id": session_id})
            hub.publish({"type": "run_error", **data})

    def on_lost(self, session_id: str, reason: str) -> None:
        record = self._records.get(session_id)
        if record is not None and record.status == "active":
            self._close(record, "lost", reason)

    def watchdog(self) -> None:
        """Kill the worker of a running session that has sent nothing for RUN_WATCHDOG_S."""
        limit = RUN_WATCHDOG_S * timeout_scale()
        now = time.monotonic()
        for record in list(self._records.values()):
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
        }
        return encode(message, raw={"state": record.state_raw} if record.state_raw else None)

    def after_step(self, record: SessionRecord, result: dict[str, Any]) -> None:
        """A manual step: tell watching clients (state included when someone is watching)."""
        record.ticks = int(result["ticks"])
        if result.get("finished"):
            record.finished = True
        state = result.get("state")
        if state is not None:
            record.state_raw, record.state_tick = state, record.ticks
            record.hub.publish({"type": "tick", "source": "step", "tick": record.ticks,
                                "advanced": result["advanced"], "events": []}, raw={"state": state})

    async def after_reset(self, record: SessionRecord) -> None:
        """Reset: new run from tick 0; watching clients get a fresh snapshot."""
        record.events.clear()
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
