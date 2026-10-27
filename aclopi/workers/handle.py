"""WorkerHandle: main-process side of one worker process.

request() can be called from several threads at once: every request gets a unique id and a Future;
a reader thread resolves the Futures from the worker's outbox by id, so responses never mix.
Unsolicited "push" messages go to the on_push callback (live mode, L5.3).
"""

from __future__ import annotations

import itertools
import logging
import multiprocessing as mp
import queue
import threading
import time
from concurrent.futures import Future
from concurrent.futures import TimeoutError as FutureTimeout
from typing import Any, Callable

from aclopi.workers.protocol import (
    WorkerCrashed, WorkerError, WorkerTimeout, default_timeout_s, request_message,
)
from aclopi.workers.worker import WorkerConfig, worker_main

logger = logging.getLogger(__name__)

PushCallback = Callable[["WorkerHandle", str, Any], None]


class WorkerHandle:
    def __init__(
        self,
        config: WorkerConfig,
        ctx: Any = None,
        on_push: PushCallback | None = None,
        on_timeout: Callable[["WorkerHandle", str], None] | None = None,
    ) -> None:
        self.config = config
        self._ctx = ctx or mp.get_context("spawn")
        self._on_push = on_push
        self._on_timeout = on_timeout
        self._ids = itertools.count(1)
        self._lock = threading.Lock()
        self._pending: dict[int, tuple[str, Future]] = {}
        self._dead: str | None = None
        self._ready = threading.Event()
        self.ready_info: dict[str, Any] | None = None
        self.fatal_error: str | None = None
        self.process: Any = None
        self._requests: Any = None
        self._outbox: Any = None
        self._reader: threading.Thread | None = None
        self._stop_reader = threading.Event()

    # ----- lifecycle -----

    @property
    def pid(self) -> int | None:
        return self.process.pid if self.process is not None else None

    @property
    def role(self) -> str:
        return self.config.role

    @property
    def slot(self) -> int:
        return self.config.slot

    def start(self) -> None:
        # Fresh queues on every start: a queue can be left corrupted if its process is killed.
        self._requests = self._ctx.Queue()
        self._outbox = self._ctx.Queue()
        self._ready.clear()
        self._stop_reader.clear()
        self.ready_info = None
        self.fatal_error = None
        self.process = self._ctx.Process(
            target=worker_main, args=(self.config, self._requests, self._outbox),
            name=f"aclopi-{self.config.name}-g{self.config.generation}", daemon=False,
        )
        self.process.start()
        self._reader = threading.Thread(target=self._read_loop, name=f"reader-{self.config.name}", daemon=True)
        self._reader.start()

    def wait_ready(self, timeout: float) -> dict[str, Any]:
        deadline = time.monotonic() + timeout
        while not self._ready.wait(0.2):
            if self.fatal_error:
                raise WorkerCrashed(f"{self.config.name} failed to start: {self.fatal_error}")
            if not self.process.is_alive():
                raise WorkerCrashed(f"{self.config.name} died while starting (exit code {self.process.exitcode})")
            if time.monotonic() > deadline:
                raise WorkerTimeout(f"{self.config.name} not ready after {timeout:.0f} s")
        assert self.ready_info is not None
        return self.ready_info

    @property
    def ready(self) -> bool:
        return self._ready.is_set()

    def kill(self) -> None:
        """Kill the process and wait until it is gone, so is_alive() is False on return."""
        if self.process is not None and self.process.is_alive():
            self.process.kill()
            self.process.join(5)

    @property
    def alive(self) -> bool:
        return self._dead is None and self.process is not None and self.process.is_alive()

    def send_shutdown(self) -> None:
        """Ask the worker to exit without waiting for the answer."""
        try:
            self._requests.put(request_message(next(self._ids), "shutdown", {}))
        except (OSError, ValueError):
            pass

    def close(self, join_timeout: float = 10.0) -> None:
        """Wait for the process to exit (killing it if needed) and release queues and threads."""
        if self.process is not None:
            self.process.join(join_timeout)
            if self.process.is_alive():
                logger.warning("%s did not exit in %.0f s; killing it", self.config.name, join_timeout)
                self.process.kill()
                self.process.join(5)
        self.fail_pending(WorkerCrashed(f"{self.config.name} was stopped"))
        self._stop_reader.set()
        if self._reader is not None:
            self._reader.join(2)
        for q in (self._requests, self._outbox):
            if q is not None:
                q.cancel_join_thread()
                q.close()

    # ----- requests -----

    def request(self, op: str, timeout: float | None = None, **args: Any) -> Any:
        """Send a request and wait for its result.

        Raises WorkerError (the operation failed, worker alive), WorkerTimeout (worker treated as
        hung: on_timeout is called so the pool restarts it) or WorkerCrashed (worker died).
        """
        if timeout is None:
            timeout = default_timeout_s(op, args)
        future: Future = Future()
        with self._lock:
            if self._dead is not None or self.process is None or not self.process.is_alive():
                raise WorkerCrashed(f"{self.config.name} is not running" + (f": {self._dead}" if self._dead else ""))
            request_id = next(self._ids)
            self._pending[request_id] = (op, future)
        self._requests.put(request_message(request_id, op, args))
        try:
            return future.result(timeout=timeout)
        except FutureTimeout:
            with self._lock:
                self._pending.pop(request_id, None)
            if self._on_timeout is not None:
                self._on_timeout(self, op)
            raise WorkerTimeout(f"{self.config.name}: no response to {op!r} in {timeout:.1f} s") from None

    def mark_dead(self, reason: str) -> None:
        """The process is gone: fail every pending request and refuse new ones."""
        with self._lock:
            self._dead = reason
        self.fail_pending(WorkerCrashed(f"{self.config.name}: {reason}"))

    def fail_pending(self, exc: BaseException) -> None:
        with self._lock:
            pending, self._pending = self._pending, {}
        for _, future in pending.values():
            if not future.done():
                future.set_exception(exc)

    def _read_loop(self) -> None:
        outbox = self._outbox
        while not self._stop_reader.is_set():
            try:
                msg = outbox.get(timeout=0.2)
            except queue.Empty:
                continue
            except (EOFError, OSError, ValueError):
                break
            except Exception:  # noqa: BLE001 - e.g. a message that cannot be unpickled
                # The reader must survive: its request will fail by timeout instead of every
                # later request on this worker.
                logger.exception("%s: unreadable message from the worker", self.config.name)
                continue
            if msg.get("type") == "response":
                with self._lock:
                    entry = self._pending.pop(msg.get("id"), None)
                if entry is None:
                    continue  # answer to a request that already timed out
                op, future = entry
                if msg.get("ok"):
                    future.set_result(msg.get("result"))
                else:
                    err = msg.get("error") or {}
                    future.set_exception(WorkerError(op, err.get("type", "?"), err.get("message", "")))
            elif msg.get("type") == "push":
                event, data = msg.get("event"), msg.get("data")
                if event == "ready":
                    self.ready_info = data
                    self._ready.set()
                elif event == "fatal":
                    self.fatal_error = (data or {}).get("error", "unknown error")
                if self._on_push is not None:
                    try:
                        self._on_push(self, event, data)
                    except Exception:  # noqa: BLE001 - a callback must not kill the reader
                        logger.exception("on_push callback failed")
