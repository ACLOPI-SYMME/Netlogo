"""L5.1 measurements of the worker pool (run in the container with the L4 limits).

- Startup: time until the 7 workers (5 session + 2 what-if, -Xmx768m) are warmed up and answer ping.
- Memory: container (cgroup) and per-worker RSS with the 7 workers loaded, and with the 5 sessions
  at tick 3000 plus the 2 what-if workers holding imported worlds.
- Latency through the queues of ping, step(3) and state(), vs SimulationSession called directly
  (measured after the pool is stopped, so its JVM does not distort the memory numbers).
- P8: first export_world of each session after the warmed-up start vs the following ones.
- Complete what-if between processes: export + import + advance 1000 ticks.

Usage (inside the container):
    python scripts/l5/bench_workers.py
"""

from __future__ import annotations

import json
import logging
import statistics
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Callable

from aclopi.sim import SimulationSession
from aclopi.workers import WorkerPool

REPO_ROOT = Path(__file__).resolve().parents[2]
RESULTS = REPO_ROOT / "results" / "l5"
CGROUP_MEMORY = Path("/sys/fs/cgroup/memory.current")
RULE = 3
LATENCY_REPS = 500
EXPORT_REPS = 6
WHATIF_REPS = 10
WHATIF_WARMUP = 2

logger = logging.getLogger("bench_workers")


def container_mib() -> float | None:
    return round(int(CGROUP_MEMORY.read_text()) / 2**20, 1) if CGROUP_MEMORY.exists() else None


def stats_ms(samples: list[float]) -> dict[str, float]:
    ordered = sorted(samples)
    p95 = ordered[min(len(ordered) - 1, int(round(0.95 * (len(ordered) - 1))))]
    return {"mean_ms": round(1000 * statistics.mean(samples), 3), "p95_ms": round(1000 * p95, 3),
            "max_ms": round(1000 * max(samples), 3), "n": len(samples)}


def timed(fn: Callable[[], Any], reps: int) -> list[float]:
    out = []
    for _ in range(reps):
        t0 = time.perf_counter()
        fn()
        out.append(time.perf_counter() - t0)
    return out


def memory_snapshot(pool: WorkerPool) -> dict[str, Any]:
    rows = pool.status()
    return {
        "container_mib": container_mib(),
        "workers_rss_mib": round(sum(r["rss_mib"] or 0 for r in rows), 1),
        "per_worker_rss_mib": {f"{r['role']}{r['slot']}": r["rss_mib"] for r in rows},
    }


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
    result: dict[str, Any] = {"container_before_mib": container_mib()}
    work_dir = Path(tempfile.mkdtemp(prefix="aclopi_bench_"))

    t0 = time.perf_counter()
    pool = WorkerPool(n_session=5, n_whatif=2, work_dir=work_dir)
    pool.start()
    handles = [pool.acquire_session(f"s{i}") for i in range(5)]
    for h in handles + []:
        h.request("ping")
    with pool.borrow_whatif() as w1, pool.borrow_whatif() as w2:
        w1.request("ping")
        w2.request("ping")
    result["startup"] = {"pool_ready_s": round(pool.startup_s or 0, 1),
                         "all_answer_ping_s": round(time.perf_counter() - t0, 1)}
    logger.info("startup: %s", result["startup"])
    try:
        result["memory_loaded"] = memory_snapshot(pool)

        for i, h in enumerate(handles):
            h.request("setup", seed=601 + i, rule=RULE)
            for _ in range(3):
                h.request("step", n=1000)

        # P8: first export after the warmed-up start vs the next ones (time inside the worker).
        first, rest = [], []
        for h in handles:
            for k in range(EXPORT_REPS):
                r = h.request("export_world")
                Path(r["path"]).unlink(missing_ok=True)
                (first if k == 0 else rest).append(r["export_ms"])
        result["p8_export_ms"] = {
            "first_after_start": {"mean": round(statistics.mean(first), 1), "max": round(max(first), 1), "values": first},
            "following": {"mean": round(statistics.mean(rest), 1), "max": round(max(rest), 1)},
        }
        logger.info("P8: %s", result["p8_export_ms"])

        # Complete what-if between processes.
        totals, parts = [], []
        for k in range(WHATIF_WARMUP + WHATIF_REPS):
            source = handles[k % len(handles)]
            t0 = time.perf_counter()
            exported = source.request("export_world")
            t1 = time.perf_counter()
            with pool.borrow_whatif() as w:
                w.request("import_world", path=exported["path"], delete_after=True)
                t2 = time.perf_counter()
                w.request("step", n=1000)
            t3 = time.perf_counter()
            if k >= WHATIF_WARMUP:
                totals.append(t3 - t0)
                parts.append((t1 - t0, t2 - t1, t3 - t2))
        result["whatif"] = {
            "total": stats_ms(totals),
            "export": stats_ms([p[0] for p in parts]),
            "import": stats_ms([p[1] for p in parts]),
            "advance_1000": stats_ms([p[2] for p in parts]),
        }
        logger.info("what-if total: %s", result["whatif"]["total"])

        # Memory with 5 sessions at tick ~3000+ and both what-if workers holding a world.
        with pool.borrow_whatif() as w1, pool.borrow_whatif() as w2:
            for w, h in ((w1, handles[0]), (w2, handles[1])):
                w.request("import_world", path=h.request("export_world")["path"], delete_after=True)
            result["memory_running"] = memory_snapshot(pool)

        # Latency through the queues.
        h = handles[0]
        h.request("setup", seed=42, rule=RULE)
        h.request("step", n=1000)
        result["latency_queue"] = {
            "ping": stats_ms(timed(lambda: h.request("ping"), LATENCY_REPS)),
            "step3": stats_ms(timed(lambda: h.request("step", n=3), LATENCY_REPS)),
            "state": stats_ms(timed(lambda: h.request("state"), LATENCY_REPS)),
        }
        logger.info("queue latency: %s", result["latency_queue"])
    finally:
        pool.shutdown()

    # Direct calls in this process, for comparison (same seed and starting tick).
    with SimulationSession("direct", results_root=work_dir / "direct") as s:
        s.setup(seed=1, rule=RULE)
        s.step(2000)  # JIT warm-up, as the workers do
        s.setup(seed=42, rule=RULE)
        s.step(1000)
        result["latency_direct"] = {
            "ticks": stats_ms(timed(lambda: s.ticks, LATENCY_REPS)),
            "step3": stats_ms(timed(lambda: s.step(3), LATENCY_REPS)),
            "state": stats_ms(timed(lambda: s.state(), LATENCY_REPS)),
        }
    logger.info("direct latency: %s", result["latency_direct"])

    RESULTS.mkdir(parents=True, exist_ok=True)
    out = RESULTS / "bench_workers.json"
    out.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k != "p8_export_ms"}, indent=1))
    print("P8:", json.dumps(result["p8_export_ms"]))
    print("Saved:", out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
