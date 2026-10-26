"""Point 4: N simultaneous 10,000-tick runs (rule 3, seeds 1001..1000+N) in three forms.

a) single : one thread, round-robin blocks of 100 ticks over the N sessions (one JVM).
b) threads: N threads in one process, one workspace each (one JVM).
c) process: N processes, one JVM and one workspace each.

Every form runs in fresh processes. Before timing, each session is set up and advanced 3000 ticks
in the same form (JIT warm-up), then set up again; only the full runs are timed. KPIs per seed
must be identical across forms.

Usage (inside the container):
    python scripts/l4/bench_concurrency.py --counts 1 4 5 7
"""

from __future__ import annotations

import argparse
import multiprocessing as mp
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from multiprocessing.connection import Connection
from typing import Any

from common import (
    RULE, SESSIONS_ROOT, Monitor, configure_logging, environment_info, logger, looks_interrupted, save_json,
)

BLOCK = 100
WARM_TICKS = 3000
RUN_TIMEOUT_S = 900
FORMS = ("single", "threads", "processes")


def seed_for(i: int) -> int:
    return 1001 + i


def _session(tag: str, i: int) -> Any:
    from aclopi.sim import SimulationSession

    return SimulationSession(f"conc_{tag}_{os.getpid()}_{i}", results_root=SESSIONS_ROOT)


def _run_blocks(session: Any) -> None:
    while not session.step(BLOCK).finished:
        pass


def in_process_form(conn: Connection, form: str, n: int) -> None:
    """Forms a and b: one process, one JVM, N workspaces."""
    configure_logging()
    sessions = [_session(form, i) for i in range(n)]
    try:
        def prepare(warm: bool) -> None:
            for i, s in enumerate(sessions):
                s.setup(seed=seed_for(i), rule=RULE)
                if warm:
                    s.step(WARM_TICKS)

        def run_all() -> None:
            if form == "single":
                pending = list(sessions)
                while pending:
                    pending = [s for s in pending if not s.step(BLOCK).finished]
            else:
                with ThreadPoolExecutor(max_workers=n) as pool:
                    futures = [pool.submit(_run_blocks, s) for s in sessions]
                    for f in futures:
                        f.result(timeout=RUN_TIMEOUT_S)

        prepare(warm=True)
        if form == "threads":  # warm-up in the same form
            with ThreadPoolExecutor(max_workers=n) as pool:
                list(pool.map(lambda s: s.step(WARM_TICKS), sessions))
        prepare(warm=False)
        conn.send(("ready",))
        conn.recv()  # parent starts its monitor, then says go
        t0 = time.perf_counter()
        cpu0 = time.process_time()
        run_all()
        wall = time.perf_counter() - t0
        cpu = time.process_time() - cpu0
        conn.send(("ok", wall, cpu, [s.kpis().as_dict() for s in sessions]))
    except Exception as exc:  # noqa: BLE001 - reported to the parent with the exact error
        conn.send(("error", f"{type(exc).__name__}: {exc}"))
    finally:
        for s in sessions:
            s.close()


def process_worker(conn: Connection, i: int, start: Any) -> None:
    """Form c: one process with its own JVM and workspace."""
    configure_logging()
    session = _session("processes", i)
    try:
        session.setup(seed=seed_for(i), rule=RULE)
        session.step(WARM_TICKS)
        session.setup(seed=seed_for(i), rule=RULE)
        conn.send(("ready",))
        start.wait()
        t0 = time.perf_counter()
        cpu0 = time.process_time()
        _run_blocks(session)
        conn.send(("ok", time.perf_counter() - t0, time.process_time() - cpu0, [session.kpis().as_dict()]))
    except Exception as exc:  # noqa: BLE001
        conn.send(("error", f"{type(exc).__name__}: {exc}"))
    finally:
        session.close()


def recv(conn: Connection, proc: mp.Process, timeout: float) -> tuple:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if conn.poll(0.5):
            return conn.recv()
        if not proc.is_alive():
            return ("died", f"exit code {proc.exitcode}")
    return ("timeout", f"no reply in {timeout:.0f} s")


def run_form(form: str, n: int) -> dict[str, Any]:
    ctx = mp.get_context("spawn")
    if form in ("single", "threads"):
        parent, child = ctx.Pipe()
        proc = ctx.Process(target=in_process_form, args=(child, form, n))
        proc.start()
        ready = recv(parent, proc, RUN_TIMEOUT_S)
        if ready[0] != "ready":
            proc.join(timeout=60)
            return {"form": form, "n": n, "error": f"{ready[0]}: {ready[1]}"}
        # The monitor covers only the timed runs (model load and warm-up happened before "ready").
        with Monitor() as mon:
            parent.send(("go",))
            reply = recv(parent, proc, RUN_TIMEOUT_S)
        proc.join(timeout=60)
        if reply[0] != "ok":
            return {"form": form, "n": n, "error": f"{reply[0]}: {reply[1]}"}
        _, wall, cpu, kpis = reply
        return {"form": form, "n": n, "wall_s": round(wall, 2), "process_cpu_s": round(cpu, 1), "kpis": kpis, "monitor": mon.result}

    start = ctx.Event()
    workers = []
    for i in range(n):
        parent, child = ctx.Pipe()
        proc = ctx.Process(target=process_worker, args=(child, i, start))
        proc.start()
        workers.append((proc, parent))
    for proc, conn in workers:
        reply = recv(conn, proc, RUN_TIMEOUT_S)
        if reply[0] != "ready":
            start.set()
            for p, _ in workers:
                p.kill()
            return {"form": form, "n": n, "error": f"worker not ready: {reply[0]} {reply[1]}"}
    with Monitor() as mon:
        t0 = time.perf_counter()
        start.set()
        replies = [recv(conn, proc, RUN_TIMEOUT_S) for proc, conn in workers]
        wall = time.perf_counter() - t0
    for proc, _ in workers:
        proc.join(timeout=60)
    errors = [r for r in replies if r[0] != "ok"]
    if errors:
        return {"form": form, "n": n, "error": f"{errors[0][0]}: {errors[0][1]}", "failed_workers": len(errors)}
    return {
        "form": form,
        "n": n,
        "wall_s": round(wall, 2),
        "process_cpu_s": round(sum(r[2] for r in replies), 1),
        "kpis": [r[3][0] for r in replies],
        "monitor": mon.result,
    }


def main() -> int:
    configure_logging()
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--counts", type=int, nargs="+", default=[1, 4, 5, 7])
    parser.add_argument("--forms", nargs="+", choices=FORMS, default=list(FORMS))
    args = parser.parse_args()

    rows: list[dict[str, Any]] = []
    for n in args.counts:
        for form in args.forms:
            expected = 1 if form == "single" else min(n, 4)
            for attempt in range(2):
                logger.info("Running form=%s N=%d (attempt %d)", form, n, attempt + 1)
                row = run_form(form, n)
                mon = row.get("monitor")
                if mon is not None and looks_interrupted(mon, expected) and attempt == 0:
                    logger.warning("form=%s N=%d looked interrupted (cpu/wall=%.2f), repeating", form, n, mon.cpu_per_wall)
                    continue
                break
            if mon is not None:
                row["cpu_util_pct"] = mon.cpu_util_pct
                row["mem_peak_mib"] = mon.mem_peak_mib
                row["cpu_per_wall"] = round(mon.cpu_per_wall, 2)
                del row["monitor"]
            rows.append(row)
            logger.info("form=%s N=%d -> %s", form, n, row.get("wall_s", row.get("error")))

    # Speed-up against the single-thread form and KPI equality per seed.
    for n in args.counts:
        group = [r for r in rows if r["n"] == n]
        single = next((r for r in group if r["form"] == "single" and "wall_s" in r), None)
        ok_rows = [r for r in group if "kpis" in r]
        for r in group:
            if single and "wall_s" in r:
                r["speedup_vs_single"] = round(single["wall_s"] / r["wall_s"], 2)
            if ok_rows and "kpis" in r:
                r["kpis_identical_across_forms"] = all(o["kpis"] == ok_rows[0]["kpis"] for o in ok_rows)

    print("\nSimultaneous 10,000-tick runs, rule 3, blocks of", BLOCK)
    print(f"{'N':>2} {'form':>9} {'wall s':>7} {'speedup':>7} {'CPU util % per core':>28} {'mem peak MiB':>12} KPIs equal")
    for r in rows:
        if "error" in r:
            print(f"{r['n']:>2} {r['form']:>9}  ERROR: {r['error']}")
            continue
        util = " ".join(f"{v:>5.0f}" for v in r["cpu_util_pct"].values())
        print(f"{r['n']:>2} {r['form']:>9} {r['wall_s']:>7} {r.get('speedup_vs_single', ''):>7} {util:>28} {r['mem_peak_mib']:>12} {r.get('kpis_identical_across_forms')}")
    print("Saved:", save_json("concurrency", {"env": environment_info(), "block": BLOCK, "rows": rows}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
