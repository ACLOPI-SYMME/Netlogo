"""Point 3: container memory and JVM heap with 1, 2, 4, 6 and 7 workspaces.

--org threads  : one JVM (one child process) hosting N workspaces.
--org processes: N child processes, one JVM and one workspace each.
Each workspace is set up (rule 3, distinct seed), advanced 3000 ticks and then 300 more ticks
before measuring; memory is read after System.gc() in every JVM. The orchestrating parent has no
JVM, so it survives an OOM kill and records it. Stops at 90 % of the container limit.

--xmx-sweep 1g 768m ...: 10,000-tick run time of a single workspace for each -Xmx (fresh JVM each).

Usage (inside the container):
    python scripts/l4/measure_memory.py --org threads
    ACLOPI_JVM_ARGS=-Xmx768m python scripts/l4/measure_memory.py --org processes --tag xmx768m
    python scripts/l4/measure_memory.py --xmx-sweep none 1g 768m 512m 384m 256m
"""

from __future__ import annotations

import argparse
import multiprocessing as mp
import os
import sys
import time
from multiprocessing.connection import Connection
from pathlib import Path
from typing import Any

from common import (
    CGROUP, MIB, RULE, SESSIONS_ROOT, Monitor, configure_logging, environment_info, jvm_memory, logger,
    looks_interrupted, memory_current, memory_limit, save_json,
)

WARM_TICKS = 3000
RUN_TICKS = 300
REPLY_TIMEOUT_S = 900


def oom_kills() -> int:
    for line in (CGROUP / "memory.events").read_text().splitlines():
        key, value = line.split()
        if key == "oom_kill":
            return int(value)
    return 0


def _new_session(index: int) -> Any:
    from aclopi.sim import SimulationSession

    session = SimulationSession(f"mem_{os.getpid()}_{index}", results_root=SESSIONS_ROOT)
    session.setup(seed=3001 + index, rule=RULE)
    session.step(WARM_TICKS)
    return session


def threads_host(conn: Connection) -> None:
    """Child process with one JVM that grows to N workspaces on request."""
    configure_logging()
    sessions: list[Any] = []
    try:
        while True:
            msg = conn.recv()
            if msg[0] == "grow":
                while len(sessions) < msg[1]:
                    sessions.append(_new_session(len(sessions)))
                for s in sessions:
                    s.step(RUN_TICKS)
                conn.send(("ok", [jvm_memory()]))
            else:
                break
    except Exception as exc:  # noqa: BLE001 - reported to the parent
        conn.send(("error", repr(exc)))
    finally:
        for s in sessions:
            s.close()


def process_worker(conn: Connection, index: int) -> None:
    """Child process with one JVM and one workspace."""
    configure_logging()
    session = None
    try:
        session = _new_session(index)
        session.step(RUN_TICKS)
        conn.send(("ok", [jvm_memory()]))
        conn.recv()  # wait for "quit"
    except Exception as exc:  # noqa: BLE001
        conn.send(("error", repr(exc)))
    finally:
        if session is not None:
            session.close()


def wait_reply(conn: Connection, proc: mp.Process) -> tuple[str, Any]:
    deadline = time.monotonic() + REPLY_TIMEOUT_S
    while time.monotonic() < deadline:
        if conn.poll(1.0):
            return conn.recv()
        if not proc.is_alive():
            return ("died", proc.exitcode)
    return ("timeout", None)


def measure_org(org: str, counts: list[int], tag: str) -> dict[str, Any]:
    ctx = mp.get_context("spawn")
    limit = memory_limit()
    base_mib = memory_current() / MIB
    oom0 = oom_kills()
    points: list[dict[str, Any]] = []
    stopped: str | None = None
    workers: list[tuple[mp.Process, Connection]] = []
    jvm_stats: list[dict[str, float]] = []

    if org == "threads":
        parent_conn, child_conn = ctx.Pipe()
        host = ctx.Process(target=threads_host, args=(child_conn,))
        host.start()
        workers.append((host, parent_conn))

    try:
        for n in counts:
            t0 = time.perf_counter()
            with Monitor() as mon:
                if org == "threads":
                    host, conn = workers[0]
                    conn.send(("grow", n))
                    status, payload = wait_reply(conn, host)
                    replies = [(status, payload)]
                else:
                    replies = []
                    while len(workers) < n:
                        parent_conn, child_conn = ctx.Pipe()
                        proc = ctx.Process(target=process_worker, args=(child_conn, len(workers)))
                        proc.start()
                        workers.append((proc, parent_conn))
                        replies.append(wait_reply(parent_conn, proc))
            bad = [r for r in replies if r[0] != "ok"]
            if bad:
                stopped = f"N={n}: {bad[0][0]} {bad[0][1]} (oom_kill events: {oom_kills() - oom0})"
                logger.error("Stopping: %s", stopped)
                break
            if org == "threads":
                jvm_stats = replies[0][1]
            else:
                jvm_stats.extend(r[1][0] for r in replies)
            time.sleep(1.0)
            container = memory_current()
            point = {
                "workspaces": n,
                "jvms": 1 if org == "threads" else n,
                "container_mib": round(container / MIB, 1),
                "container_peak_mib": mon.result.mem_peak_mib,
                "jvm": list(jvm_stats),
                "seconds_to_reach": round(time.perf_counter() - t0, 1),
            }
            points.append(point)
            logger.info("%s %s N=%d: container %.0f MiB (peak %.0f)", org, tag, n, point["container_mib"], point["container_peak_mib"])
            if limit and container > 0.9 * limit:
                stopped = f"N={n}: container at {100 * container / limit:.0f} % of the limit"
                logger.warning("Stopping: %s", stopped)
                break
    finally:
        for proc, conn in workers:
            try:
                conn.send(("quit",))
            except (OSError, BrokenPipeError):
                pass
        for proc, _ in workers:
            proc.join(timeout=60)
            if proc.is_alive():
                proc.kill()

    fit = linear_fit([p["workspaces"] for p in points], [p["container_mib"] for p in points])
    return {
        "org": org,
        "tag": tag,
        "container_before_mib": round(base_mib, 1),
        "points": points,
        "stopped": stopped,
        "oom_kills": oom_kills() - oom0,
        "fit": fit,
    }


def linear_fit(xs: list[float], ys: list[float]) -> dict[str, float] | None:
    if len(xs) < 2:
        return None
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx
    intercept = my - slope * mx
    return {
        "base_mib": round(intercept, 1),
        "per_workspace_mib": round(slope, 1),
        "projected_7_mib": round(intercept + 7 * slope, 1),
        "projected_8_mib": round(intercept + 8 * slope, 1),
    }


def xmx_run(conn: Connection) -> None:
    configure_logging()
    from aclopi.sim import SimulationSession

    with SimulationSession(f"xmx_{os.getpid()}", results_root=SESSIONS_ROOT) as s:
        s.setup(seed=42, rule=RULE)
        s.run_to_end()  # warm-up
        s.setup(seed=42, rule=RULE)
        with Monitor() as mon:
            s.run_to_end()
        conn.send((mon.result.wall_s, mon.result.cpu_per_wall, jvm_memory(), s.kpis().as_dict()))


def xmx_sweep(values: list[str]) -> list[dict[str, Any]]:
    ctx = mp.get_context("spawn")
    rows = []
    for value in values:
        args = "" if value == "none" else f"-Xmx{value}"
        os.environ["ACLOPI_JVM_ARGS"] = args
        for attempt in range(2):
            parent_conn, child_conn = ctx.Pipe()
            proc = ctx.Process(target=xmx_run, args=(child_conn,))
            proc.start()
            status = wait_reply(parent_conn, proc)
            proc.join()
            if status[0] in ("died", "timeout"):
                rows.append({"xmx": value, "error": f"{status[0]} {status[1]}"})
                break
            wall, cpu_per_wall, mem, kpis = status
            if cpu_per_wall < 0.4 and attempt == 0:
                logger.warning("-Xmx %s run looked interrupted, repeating", value)
                continue
            rows.append({"xmx": value, "run_10000_s": round(wall, 2), "jvm": mem, "kpis": kpis})
            logger.info("-Xmx %s: %.2f s", value, wall)
            break
    os.environ["ACLOPI_JVM_ARGS"] = ""
    return rows


def main() -> int:
    configure_logging()
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--org", choices=("threads", "processes"))
    parser.add_argument("--counts", type=int, nargs="+", default=[1, 2, 4, 6, 7])
    parser.add_argument("--tag", default="default")
    parser.add_argument("--xmx-sweep", nargs="+")
    args = parser.parse_args()

    if args.xmx_sweep:
        rows = xmx_sweep(args.xmx_sweep)
        print("\n-Xmx sweep: 10,000-tick run, rule 3, seed 42")
        for r in rows:
            print(r.get("xmx"), r.get("run_10000_s", r.get("error")), r.get("jvm", ""))
        print("Saved:", save_json("memory_xmx_sweep", {"env": environment_info(), "rows": rows}))
        return 0

    if not args.org:
        parser.error("--org or --xmx-sweep is required")
    result = measure_org(args.org, args.counts, args.tag)
    result["env"] = environment_info()
    print(f"\nMemory, org={args.org}, tag={args.tag}, JVM args='{os.environ.get('ACLOPI_JVM_ARGS', '')}'")
    print(f"{'N':>3} {'JVMs':>4} {'container MiB':>13} {'peak MiB':>9} {'heap used/committed/max per JVM (MiB)':>40}")
    for p in result["points"]:
        heaps = "; ".join(f"{j['heap_used_mib']:.0f}/{j['heap_committed_mib']:.0f}/{j['heap_max_mib']:.0f}" for j in p["jvm"][:3])
        more = " ..." if len(p["jvm"]) > 3 else ""
        print(f"{p['workspaces']:>3} {p['jvms']:>4} {p['container_mib']:>13} {p['container_peak_mib']:>9}   {heaps}{more}")
    print("fit:", result["fit"], "| stopped:", result["stopped"], "| oom_kills:", result["oom_kills"])
    print("Saved:", save_json(f"memory_{args.org}_{args.tag}", result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
