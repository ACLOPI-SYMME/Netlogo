"""WorkerPool: the simulation worker processes of the backend.

- n_session workers hold user sessions (acquire_session / release_session).
- n_whatif workers are lent for what-ifs without queueing: borrow_whatif() raises NoFreeWorker
  immediately when none is free. They run with lower OS priority than session workers.
- A monitor thread waits on the process sentinels: when a worker dies (or is killed because a
  request timed out, i.e. it is treated as hung), its pending requests fail with WorkerCrashed,
  its session is marked as lost (SessionLost on next access) and the worker is restarted.
- shutdown() stops every worker and its JVM (the JVM lives inside the worker process). Workers also
  exit by themselves when the parent process disappears, so no orphans are left behind.

The pool may be used from several threads (and later from the API's event loop); NetLogo only
runs inside the workers, each from its own main thread.
"""

from __future__ import annotations

import logging
import multiprocessing as mp
import os
import shutil
import threading
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from multiprocessing.connection import wait
from pathlib import Path
from typing import Any, Iterator

from aclopi.workers import procinfo
from aclopi.workers.handle import PushCallback, WorkerHandle
from aclopi.workers.protocol import NoFreeWorker, SessionLost, WorkerCrashed
from aclopi.workers.worker import WorkerConfig

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_JVM_ARGS = ("-Xmx768m",)

logger = logging.getLogger(__name__)


@dataclass
class Slot:
    index: int
    role: str
    handle: WorkerHandle
    state: str = "starting"  # starting | free | busy | restarting | failed | stopped
    session_id: str | None = None
    generation: int = 0
    restarts: int = 0
    kill_reason: str | None = None


def default_work_dir() -> Path:
    root = os.environ.get("ACLOPI_WORK_DIR")
    return Path(root) if root else REPO_ROOT / "results" / "workers"


class WorkerPool:
    def __init__(
        self,
        n_session: int = 5,
        n_whatif: int = 2,
        work_dir: str | os.PathLike[str] | None = None,
        jvm_args: tuple[str, ...] | list[str] = DEFAULT_JVM_ARGS,
        debug: bool = False,
        warm: bool = True,
        start_timeout_s: float = 300.0,
        on_push: PushCallback | None = None,
    ) -> None:
        """debug=True enables the diagnostic operations "command" and "report" (arbitrary NetLogo
        code). Only for tests and diagnostics: the API must never create a pool with debug=True
        nor expose those operations."""
        self.pool_id = uuid.uuid4().hex[:8]
        self.work_dir = (Path(work_dir) if work_dir else default_work_dir()) / f"pool_{self.pool_id}"
        self.n_session, self.n_whatif = n_session, n_whatif
        self.jvm_args = tuple(jvm_args)
        self.debug, self.warm = debug, warm
        self.start_timeout_s = start_timeout_s
        self._on_push = on_push
        self._ctx = mp.get_context("spawn")
        self._lock = threading.RLock()
        self._slots: list[Slot] = []
        self._lost: dict[str, str] = {}
        self._stopping = threading.Event()
        self._monitor: threading.Thread | None = None
        self.spawned_pids: set[int] = set()
        self.startup_s: float | None = None

    # ----- lifecycle -----

    def __enter__(self) -> WorkerPool:
        self.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self.shutdown()

    def start(self) -> float:
        """Start every worker and wait until all are loaded, warmed up and ready. Returns seconds."""
        t0 = time.perf_counter()
        worlds = self.work_dir / "worlds"
        shutil.rmtree(worlds, ignore_errors=True)
        worlds.mkdir(parents=True, exist_ok=True)
        roles = ["session"] * self.n_session + ["whatif"] * self.n_whatif
        with self._lock:
            for index, role in enumerate(roles):
                slot = Slot(index=index, role=role, handle=self._new_handle(index, role, 0))
                self._slots.append(slot)
                slot.handle.start()
                self.spawned_pids.add(slot.handle.pid)
        # Workers start in parallel: one deadline for all of them.
        deadline = time.monotonic() + self.start_timeout_s
        current = None
        try:
            for slot in self._slots:
                current = slot
                slot.handle.wait_ready(max(deadline - time.monotonic(), 0.1))
            for slot in self._slots:
                slot.state = "free"
        except Exception as exc:
            if self._stopping.is_set():  # shutdown() was called while starting
                raise
            name = current.handle.config.name if current is not None else "?"
            logger.error("Pool %s: worker %s failed to start: %s", self.pool_id, name, exc,
                         extra={"worker": name})
            for slot in self._slots:
                if slot is not current and not slot.handle.ready:
                    logger.error("Pool %s: worker %s was not ready either", self.pool_id,
                                 slot.handle.config.name, extra={"worker": slot.handle.config.name})
            self.shutdown()
            raise
        self._monitor = threading.Thread(target=self._monitor_loop, name="pool-monitor", daemon=True)
        self._monitor.start()
        self.startup_s = time.perf_counter() - t0
        logger.info("Pool %s ready in %.1f s (%d session + %d what-if workers)",
                    self.pool_id, self.startup_s, self.n_session, self.n_whatif)
        return self.startup_s

    def shutdown(self, timeout_s: float = 15.0) -> None:
        """Stop every worker (and its JVM); kill the ones that do not exit in time. Idempotent."""
        with self._lock:
            if self._stopping.is_set():
                return
            self._stopping.set()
        if self._monitor is not None:
            self._monitor.join(2)
        with self._lock:
            slots = list(self._slots)
        for slot in slots:
            slot.handle.send_shutdown()
        for slot in slots:
            slot.handle.close(join_timeout=timeout_s)
            slot.state = "stopped"
        shutil.rmtree(self.work_dir / "worlds", ignore_errors=True)

    def _new_handle(self, index: int, role: str, generation: int) -> WorkerHandle:
        config = WorkerConfig(
            slot=index, role=role, generation=generation, work_dir=str(self.work_dir),
            jvm_args=self.jvm_args, debug=self.debug, warm=self.warm,
        )
        return WorkerHandle(config, ctx=self._ctx, on_push=self._on_push, on_timeout=self._on_request_timeout)

    # ----- sessions -----

    def acquire_session(self, session_id: str) -> WorkerHandle:
        with self._lock:
            if any(s.session_id == session_id for s in self._slots):
                raise ValueError(f"session {session_id!r} already has a worker")
            slot = next((s for s in self._slots if s.role == "session" and s.state == "free"), None)
            if slot is None:
                raise NoFreeWorker("no free session worker")
            slot.state, slot.session_id = "busy", session_id
            self._lost.pop(session_id, None)
            return slot.handle

    def session(self, session_id: str) -> WorkerHandle:
        """The worker that holds a session. Raises SessionLost if its worker died."""
        with self._lock:
            if session_id in self._lost:
                raise SessionLost(f"session {session_id!r} was lost: {self._lost[session_id]}")
            slot = next((s for s in self._slots if s.session_id == session_id), None)
            if slot is None:
                raise KeyError(f"unknown session {session_id!r}")
            return slot.handle

    def release_session(self, session_id: str) -> None:
        with self._lock:
            self._lost.pop(session_id, None)
            for slot in self._slots:
                if slot.session_id == session_id:
                    slot.session_id = None
                    # A worker that was just killed (timeout) stays "busy" until the monitor
                    # restarts it, so nobody can acquire a dead worker in between.
                    if slot.state == "busy" and slot.handle.alive:
                        slot.state = "free"

    def lost_sessions(self) -> dict[str, str]:
        with self._lock:
            return dict(self._lost)

    # ----- what-if -----

    @contextmanager
    def borrow_whatif(self) -> Iterator[WorkerHandle]:
        """Lend a free what-if worker; raises NoFreeWorker immediately if none is free."""
        with self._lock:
            slot = next((s for s in self._slots if s.role == "whatif" and s.state == "free"), None)
            if slot is None:
                raise NoFreeWorker("no free what-if worker")
            slot.state = "busy"
            generation, handle = slot.generation, slot.handle
        try:
            yield handle
        finally:
            with self._lock:
                if slot.generation == generation and slot.state == "busy":
                    slot.state = "free"

    @contextmanager
    def whatif_from_session(self, session_id: str) -> Iterator[WorkerHandle]:
        """Export the session's world, import it into a borrowed what-if worker and lend it.
        The world file is deleted after the import (or if anything fails)."""
        source = self.session(session_id)
        with self.borrow_whatif() as whatif:
            exported = source.request("export_world")
            path = Path(exported["path"])
            try:
                whatif.request("import_world", path=str(path), delete_after=True)
            finally:
                path.unlink(missing_ok=True)
            yield whatif

    # ----- status -----

    def status(self) -> list[dict[str, Any]]:
        with self._lock:
            slots = list(self._slots)
        rows = []
        for s in slots:
            pid = s.handle.pid
            alive = s.handle.process is not None and s.handle.process.is_alive()
            rows.append({
                "slot": s.index,
                "role": s.role,
                "ready": s.handle.ready and alive,
                "pid": pid,
                "state": s.state,
                "session_id": s.session_id,
                "rss_mib": procinfo.rss_mib(pid) if pid and alive else None,
                "priority": procinfo.process_priority(pid) if pid and alive else None,
                "generation": s.generation,
                "restarts": s.restarts,
            })
        return rows

    # ----- failure handling -----

    def _on_request_timeout(self, handle: WorkerHandle, op: str) -> None:
        """A request timed out: treat the worker as hung and kill it; the monitor restarts it."""
        with self._lock:
            slot = next((s for s in self._slots if s.handle is handle), None)
            if slot is None or self._stopping.is_set():
                return
            slot.kill_reason = f"unresponsive (no response to {op!r} within its timeout)"
        logger.error("%s: %s; killing it", handle.config.name, slot.kill_reason)
        handle.kill()

    def _monitor_loop(self) -> None:
        while not self._stopping.is_set():
            with self._lock:
                watched = {s.handle.process.sentinel: s for s in self._slots
                           if s.state in ("free", "busy") and s.handle.process is not None}
            if not watched:
                self._stopping.wait(0.5)
                continue
            for sentinel in wait(list(watched), timeout=0.5):
                if not self._stopping.is_set():
                    self._handle_death(watched[sentinel])

    def _handle_death(self, slot: Slot) -> None:
        with self._lock:
            old = slot.handle
            reason = slot.kill_reason or f"worker process exited unexpectedly (exit code {old.process.exitcode})"
            if slot.session_id is not None:
                self._lost[slot.session_id] = reason
                logger.error("Session %s lost: %s", slot.session_id, reason,
                             extra={"session_id": slot.session_id, "worker": old.config.name})
            slot.session_id = None
            slot.state = "restarting"
            slot.kill_reason = None
        old.mark_dead(reason)
        threading.Thread(target=self._restart, args=(slot, old), name=f"restart-{slot.index}", daemon=True).start()

    def _restart(self, slot: Slot, old: WorkerHandle) -> None:
        old.close(join_timeout=5)
        with self._lock:
            slot.generation += 1
            slot.restarts += 1
            handle = self._new_handle(slot.index, slot.role, slot.generation)
            slot.handle = handle
        if self._stopping.is_set():
            slot.state = "stopped"
            return
        handle.start()
        self.spawned_pids.add(handle.pid)
        try:
            handle.wait_ready(self.start_timeout_s)
        except (WorkerCrashed, Exception) as exc:  # noqa: BLE001
            logger.error("Restart of slot %d failed: %s", slot.index, exc)
            slot.state = "failed"
            return
        with self._lock:
            if not self._stopping.is_set():
                slot.state = "free"
        logger.info("Slot %d (%s) restarted as generation %d, pid %s", slot.index, slot.role, slot.generation, handle.pid)

    def wait_until_free(self, slot_index: int, timeout_s: float) -> bool:
        """Test helper: wait until a slot is back to "free" (e.g. after a restart)."""
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            with self._lock:
                if self._slots[slot_index].state == "free":
                    return True
            time.sleep(0.2)
        return False
