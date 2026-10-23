"""Shared helpers for the L4 measurements. Linux only (cgroup v2 and /proc), meant to run in the
aclopi-sim container started with docker/run.ps1 (--cpus=4 --cpuset-cpus=0-3 --memory=6g)."""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
RESULTS_DIR = REPO_ROOT / "results" / "l4"
# Session folders (exported CSVs, world files) live on the container's own filesystem: the
# bind-mounted results/ goes through the Windows file sharing layer, unlike an EC2 disk.
SESSIONS_ROOT = Path(os.environ.get("ACLOPI_SESSIONS_ROOT", "/tmp/aclopi-sessions"))
CGROUP = Path("/sys/fs/cgroup")
RULE = 3
GIB = 1024**3
MIB = 1024**2

logger = logging.getLogger("l4")


def configure_logging() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")


def save_json(name: str, data: Any) -> Path:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    path = RESULTS_DIR / f"{name}.json"
    path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    return path


# ----- cgroup / proc readers -----

def memory_current() -> int:
    return int((CGROUP / "memory.current").read_text())


def memory_limit() -> int | None:
    raw = (CGROUP / "memory.max").read_text().strip()
    return None if raw == "max" else int(raw)


def cgroup_cpu_seconds() -> float:
    for line in (CGROUP / "cpu.stat").read_text().splitlines():
        key, value = line.split()
        if key == "usage_usec":
            return int(value) / 1e6
    raise RuntimeError("usage_usec not found in cpu.stat")


def allowed_cpus() -> list[int]:
    cpus: list[int] = []
    for part in (CGROUP / "cpuset.cpus.effective").read_text().strip().split(","):
        if "-" in part:
            lo, hi = part.split("-")
            cpus.extend(range(int(lo), int(hi) + 1))
        elif part:
            cpus.append(int(part))
    return cpus


def per_cpu_times() -> dict[int, tuple[int, int]]:
    """{cpu: (busy_jiffies, total_jiffies)} from /proc/stat."""
    result = {}
    for line in Path("/proc/stat").read_text().splitlines():
        if line.startswith("cpu") and line[3].isdigit():
            parts = line.split()
            values = list(map(int, parts[1:]))
            idle = values[3] + values[4]  # idle + iowait
            total = sum(values[:8])
            result[int(parts[0][3:])] = (total - idle, total)
    return result


def rss_bytes(pid: int | str = "self") -> int:
    for line in Path(f"/proc/{pid}/status").read_text().splitlines():
        if line.startswith("VmRSS:"):
            return int(line.split()[1]) * 1024
    return 0


def cpu_topology() -> dict[int, str]:
    """{cpu: thread_siblings_list} for the CPUs this container may use."""
    topo = {}
    for cpu in allowed_cpus():
        path = Path(f"/sys/devices/system/cpu/cpu{cpu}/topology/thread_siblings_list")
        topo[cpu] = path.read_text().strip() if path.exists() else "?"
    return topo


def jvm_memory(gc: bool = True) -> dict[str, float]:
    """Heap/non-heap of the JVM running in this process (MiB), after an optional System.gc()."""
    import jpype

    management = jpype.JClass("java.lang.management.ManagementFactory")
    if gc:
        jpype.JClass("java.lang.System").gc()
        time.sleep(0.2)
    bean = management.getMemoryMXBean()
    heap, nonheap = bean.getHeapMemoryUsage(), bean.getNonHeapMemoryUsage()
    return {
        "heap_used_mib": round(heap.getUsed() / MIB, 1),
        "heap_committed_mib": round(heap.getCommitted() / MIB, 1),
        "heap_max_mib": round(heap.getMax() / MIB, 1),
        "nonheap_used_mib": round(nonheap.getUsed() / MIB, 1),
        "rss_mib": round(rss_bytes() / MIB, 1),
    }


# ----- background monitor -----

@dataclass
class MonitorResult:
    wall_s: float
    cgroup_cpu_s: float
    mem_peak_mib: float
    mem_end_mib: float
    cpu_util_pct: dict[int, float] = field(default_factory=dict)

    @property
    def cpu_per_wall(self) -> float:
        return self.cgroup_cpu_s / self.wall_s if self.wall_s else 0.0


class Monitor:
    """Samples container memory every `interval` s; reports per-CPU utilization and CPU time."""

    def __init__(self, interval: float = 0.25) -> None:
        self.interval = interval
        self._stop = threading.Event()
        self._peak = 0
        self._thread = threading.Thread(target=self._run, daemon=True)

    def _run(self) -> None:
        while not self._stop.is_set():
            self._peak = max(self._peak, memory_current())
            self._stop.wait(self.interval)

    def __enter__(self) -> Monitor:
        self._t0 = time.perf_counter()
        self._cpu0 = cgroup_cpu_seconds()
        self._stat0 = per_cpu_times()
        self._peak = memory_current()
        self._thread.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self._stop.set()
        self._thread.join()
        wall = time.perf_counter() - self._t0
        stat1 = per_cpu_times()
        util = {}
        for cpu in allowed_cpus():
            busy0, total0 = self._stat0.get(cpu, (0, 0))
            busy1, total1 = stat1.get(cpu, (0, 0))
            util[cpu] = round(100 * (busy1 - busy0) / (total1 - total0), 1) if total1 > total0 else 0.0
        end = memory_current()
        self.result = MonitorResult(
            wall_s=wall,
            cgroup_cpu_s=cgroup_cpu_seconds() - self._cpu0,
            mem_peak_mib=round(max(self._peak, end) / MIB, 1),
            mem_end_mib=round(end / MIB, 1),
            cpu_util_pct=util,
        )


def looks_interrupted(result: MonitorResult, expected_busy_cpus: float) -> bool:
    """True if the container used far less CPU than the work needs (e.g. the host slept).

    expected_busy_cpus: CPUs that should be busy on average (1 for a single thread, up to 4).
    """
    return result.wall_s > 2.0 and result.cpu_per_wall < 0.4 * expected_busy_cpus


def percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    k = (len(ordered) - 1) * pct / 100
    lo = int(k)
    hi = min(lo + 1, len(ordered) - 1)
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (k - lo)


def environment_info() -> dict[str, Any]:
    return {
        "cpus_allowed": allowed_cpus(),
        "cpu_topology": cpu_topology(),
        "memory_limit_mib": None if memory_limit() is None else memory_limit() / MIB,
        "jvm_args": os.environ.get("ACLOPI_JVM_ARGS", ""),
        "nproc": os.cpu_count(),
    }
