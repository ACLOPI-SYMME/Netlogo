"""SessionRegistry: the API's sessions on top of the WorkerPool.

- One asyncio.Lock per session: requests to a session run one at a time, in arrival order
  (asyncio.Lock is FIFO); different sessions run in parallel.
- Blocking WorkerHandle calls run in threads (anyio.to_thread), never on the event loop.
- A session is "active", "lost" (its worker crashed or hung) or "expired" (closed for
  inactivity). Lost and expired sessions stay listed (410 on access) until DELETE, or until they
  are older than TOMBSTONE_TTL_S, or there are more than MAX_TOMBSTONES.
- When a request times out the pool has already killed the worker; the slot stays "busy" until
  the monitor restarts it, so no new session gets a dead worker.
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

from aclopi.api.errors import GatewayTimeout, NoWorkerAvailable, SessionGone, SessionNotFound, WorkerUnavailable
from aclopi.logjson import session_id_var
from aclopi.workers.pool import WorkerPool
from aclopi.workers.protocol import NoFreeWorker, SessionLost, WorkerCrashed, WorkerError, WorkerTimeout

TOMBSTONE_TTL_S = 24 * 3600.0
MAX_TOMBSTONES = 1000

logger = logging.getLogger(__name__)


@dataclass
class SessionRecord:
    session_id: str
    parameters: dict[str, Any]
    worker_slot: int | None
    created_at: float
    last_activity: float
    last_activity_mono: float
    ticks: int = 0
    finished: bool = False
    status: str = "active"  # active | lost | expired | deleted (deleted records are no longer listed)
    lost_reason: str | None = None
    closed_mono: float | None = None
    pending: int = 0
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    def info(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "status": self.status,
            "parameters": self.parameters,
            "ticks": self.ticks,
            "finished": self.finished,
            "lost_reason": self.lost_reason,
            "worker_slot": self.worker_slot,
            "created_at": self.created_at,
            "last_activity": self.last_activity,
        }


class SessionRegistry:
    def __init__(
        self,
        pool: WorkerPool,
        idle_timeout_s: float,
        limiter: anyio.CapacityLimiter,
        tombstone_ttl_s: float = TOMBSTONE_TTL_S,
        max_tombstones: int = MAX_TOMBSTONES,
    ) -> None:
        self.pool = pool
        self.idle_timeout_s = idle_timeout_s
        self.limiter = limiter
        self.tombstone_ttl_s = tombstone_ttl_s
        self.max_tombstones = max_tombstones
        self._records: dict[str, SessionRecord] = {}

    async def run(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        """Run a blocking call in a thread (contextvars, hence session_id, are copied)."""
        return await anyio.to_thread.run_sync(functools.partial(fn, *args, **kwargs), limiter=self.limiter)

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
            ticks=int(result["ticks"]),
        )
        self._records[session_id] = record
        logger.info("Session created on worker %s", handle.config.name, extra={"worker": handle.config.name})
        return record

    async def call(self, session_id: str, op: str, **args: Any) -> tuple[SessionRecord, Any]:
        """Run one worker operation for a session, in order with the session's other requests."""
        record = self.get(session_id)
        self._ensure_active(record)
        record.pending += 1
        try:
            async with record.lock:
                self.refresh_lost()
                self._ensure_active(record)
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
                except WorkerError:
                    raise
                self._touch(record)
                return record, result
        finally:
            record.pending -= 1

    async def delete(self, session_id: str) -> None:
        record = self.get(session_id, touch=False)
        if record.status == "active":
            async with record.lock:
                if record.status == "active":
                    self.pool.release_session(session_id)
        else:
            self.pool.release_session(session_id)  # clears the pool's lost entry, if any
        record.status = "deleted"
        self._records.pop(session_id, None)
        logger.info("Session deleted", extra={"session_id": session_id})

    def close_all(self) -> None:
        for record in self._records.values():
            if record.status == "active":
                record.status = "deleted"

    # ----- lost and idle sessions -----

    def refresh_lost(self) -> None:
        """Mark as lost the sessions whose worker died (detected by the pool's monitor)."""
        for session_id, reason in self.pool.lost_sessions().items():
            record = self._records.get(session_id)
            if record is not None and record.status == "active":
                self._close(record, "lost", reason)
            else:
                self.pool.release_session(session_id)

    def sweep(self) -> None:
        """Close idle sessions (no request for idle_timeout_s, none in progress) and prune."""
        self.refresh_lost()
        now = time.monotonic()
        for record in list(self._records.values()):
            if (record.status == "active" and record.pending == 0 and not record.lock.locked()
                    and now - record.last_activity_mono > self.idle_timeout_s):
                self._close(record, "expired", f"closed after {self.idle_timeout_s:g} s without requests")
        self.prune()

    async def sweep_loop(self) -> None:
        interval = min(60.0, max(self.idle_timeout_s / 4, 0.5))
        while True:
            await asyncio.sleep(interval)
            try:
                self.sweep()
            except Exception:  # noqa: BLE001 - the sweeper must keep running
                logger.exception("Idle-session sweep failed")

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
        self.pool.release_session(record.session_id)
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
