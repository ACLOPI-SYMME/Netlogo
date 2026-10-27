"""Single API instance per work folder.

Every API process starts its own WorkerPool (7 JVMs, ~3.3 GB). Running uvicorn with several
workers, or two API processes on the same work folder, would start several pools. The lock file
<work_dir>/api.lock makes the second one fail at startup with a clear message.

The file records pid, host name and process start time, so a lock left behind by a killed process
(or by another container sharing the mounted results/ folder) is detected as stale and replaced.
"""

from __future__ import annotations

import json
import logging
import os
import socket
from pathlib import Path

import psutil

logger = logging.getLogger(__name__)


class InstanceLockError(RuntimeError):
    pass


def _identity() -> dict[str, object]:
    return {"pid": os.getpid(), "host": socket.gethostname(), "create_time": psutil.Process().create_time()}


def _is_stale(owner: dict[str, object]) -> bool:
    if owner.get("host") != socket.gethostname():
        return True
    try:
        process = psutil.Process(int(owner["pid"]))  # type: ignore[arg-type]
        return abs(process.create_time() - float(owner["create_time"])) > 1.0  # type: ignore[arg-type]
    except (psutil.Error, KeyError, TypeError, ValueError):
        return True


class InstanceLock:
    def __init__(self, work_dir: Path) -> None:
        self.path = Path(work_dir) / "api.lock"
        self._held = False

    def acquire(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        me = _identity()
        for _ in range(2):
            try:
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                try:
                    owner = json.loads(self.path.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    owner = {}
                if owner.get("pid") == me["pid"] and owner.get("host") == me["host"]:
                    raise InstanceLockError(f"{self.path} is already held by this process")
                if not _is_stale(owner):
                    raise InstanceLockError(
                        f"another API instance (pid {owner.get('pid')}) is running on {self.path.parent} with its "
                        "own worker pool; run a single API process with a single uvicorn worker"
                    )
                logger.warning("Removing stale API lock %s (owner %s)", self.path, owner)
                self.path.unlink(missing_ok=True)
                continue
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(me, f)
            self._held = True
            return
        raise InstanceLockError(f"could not acquire {self.path}")

    def release(self) -> None:
        if self._held:
            self.path.unlink(missing_ok=True)
            self._held = False
