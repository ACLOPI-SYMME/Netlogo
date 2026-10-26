"""Process information and priority (psutil), for Windows and Linux."""

from __future__ import annotations

import logging
import os
import sys

import psutil

logger = logging.getLogger(__name__)


def rss_mib(pid: int) -> float | None:
    """Resident memory of a process in MiB (includes the JVM, which lives inside the worker)."""
    try:
        return round(psutil.Process(pid).memory_info().rss / 2**20, 1)
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return None


def lower_own_priority() -> str:
    """Lower the priority of the current process (what-if workers). Returns what was applied."""
    try:
        if sys.platform == "win32":
            psutil.Process().nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)
            return "BELOW_NORMAL_PRIORITY_CLASS"
        new = os.nice(10)  # raising niceness needs no privileges
        return f"nice {new}"
    except Exception as exc:  # noqa: BLE001 - priority is best effort
        logger.warning("Could not lower process priority: %s", exc)
        return f"unchanged ({exc})"


def process_priority(pid: int) -> int | None:
    try:
        return int(psutil.Process(pid).nice())
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return None


def is_alive(pid: int) -> bool:
    try:
        return psutil.Process(pid).status() != psutil.STATUS_ZOMBIE
    except psutil.NoSuchProcess:
        return False
