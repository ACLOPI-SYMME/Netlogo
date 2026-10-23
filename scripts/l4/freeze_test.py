"""Point 5: freeze test. What a demo user would see while what-ifs run.

5 live sessions (rule 3, seeds 2001..2005, started at tick 3000) advance in blocks of 3 ticks
followed by platform-state, paced at 32 ticks/s (one block every 93.75 ms, no catch-up bursts).
Every 3 s a what-if runs: export one live session (rotating), import into one of 2 what-if
workspaces (alternating) and advance 1000 ticks. Duration 60 s.

Forms:
  single         : one thread; the what-if runs inline (blocks every live session meanwhile).
  single_chunked : one thread; the what-if runs as export, import and 32-tick slices interleaved
                   with the live blocks.
  threads        : 5 live threads + 1 what-if thread, one JVM (the session lock serializes the
                   export with the live loop of the exported session).
  processes      : 5 live processes + 1 what-if process (2 workspaces); exports are requested
                   through a pipe and done between two live blocks.

Per live session: real ticks/s, max pause between blocks and p95 of the pauses.
Criterion: no live session should stand still for more than ~0.5 s.

Usage (inside the container):
    python scripts/l4/freeze_test.py --forms single single_chunked threads processes
"""

from __future__ import annotations

import argparse
import multiprocessing as mp
import os
import sys
import threading
import time
from multiprocessing.connection import Connection
from pathlib import Path
from typing import Any

from common import (
    RULE, SESSIONS_ROOT, Monitor, configure_logging, environment_info, logger, looks_interrupted, percentile, save_json,
)

LIVE = 5
WHATIF_WORKSPACES = 2
DURATION_S = 60.0
BLOCK = 3
RATE = 32.0
PERIOD_S = BLOCK / RATE
WHATIF_EVERY_S = 3.0
WHATIF_TICKS = 1000
SLICE = 32
PREWARM_TICKS = 3000
FREEZE_LIMIT_S = 0.5
FORMS = ("single", "single_chunked", "threads", "processes")


def make_session(tag: str, i: int) -> Any:
    from aclopi.sim import SimulationSession

    return SimulationSession(f"freeze_{tag}_{os.getpid()}_{i}", results_root=SESSIONS_ROOT)


WARM_EXPORT = os.environ.get("FREEZE_WARM_EXPORT") == "1"
WARM_EXPORTS = int(os.environ.get("FREEZE_WARM_EXPORTS", "1"))


def prepare_live(session: Any, k: int) -> None:
    session.setup(seed=2001 + k, rule=RULE)
    session.step(PREWARM_TICKS)
    if WARM_EXPORT:  # the first export-world calls of a JVM are several times slower than later ones
        for _ in range(WARM_EXPORTS):
            session.export_world().unlink()


def prepare_whatif(sessions: list[Any]) -> None:
    """Set up the what-if workspaces and run one full what-if on each (JIT warm-up)."""
    sessions[0].setup(seed=2101, rule=RULE)
    sessions[0].step(PREWARM_TICKS)
    path = sessions[0].export_world()
    for s in sessions:
        s.import_world(path)
        s.step(WHATIF_TICKS)
    path.unlink()


def live_stats(times: list[float], ticks: int, t0: float, t_end: float) -> dict[str, float]:
    gaps = [b - a for a, b in zip([t0] + times[:-1], times)]
    if times:
        gaps.append(t_end - times[-1])
    return {
        "ticks": ticks,
        "ticks_per_s": round(ticks / (t_end - t0), 1),
        "blocks": len(times),
        "max_pause_s": round(max(gaps), 3) if gaps else 0.0,
        "p95_pause_s": round(percentile(gaps, 95), 3),
        "pauses_over_limit": sum(1 for g in gaps if g > FREEZE_LIMIT_S),
    }


def next_due(due: float, now: float) -> float:
    """Pace at PERIOD_S without bursts: after a stall, resume from now instead of catching up."""
    return max(due + PERIOD_S, now)


# ----- single thread (inline or chunked what-if) -----

def run_single(chunked: bool) -> dict[str, Any]:
    tag = "single_chunked" if chunked else "single"
    lives = [make_session(tag, k) for k in range(LIVE)]
    whatifs = [make_session(f"{tag}_wi", j) for j in range(WHATIF_WORKSPACES)]
    try:
        for k, s in enumerate(lives):
            prepare_live(s, k)
        prepare_whatif(whatifs)

        times: list[list[float]] = [[] for _ in lives]
        ticks = [0] * LIVE
        whatif_log: list[dict[str, float]] = []
        t0 = time.monotonic()
        end = t0 + DURATION_S
        due = [t0] * LIVE
        next_whatif = t0 + WHATIF_EVERY_S
        count = 0
        job: dict[str, Any] | None = None

        def run_job_part(job: dict[str, Any]) -> bool:
            """Advance the what-if job; returns True when it is complete."""
            t = time.monotonic()
            if job["phase"] == "export":
                job["path"] = lives[job["k"]].export_world()
                job["export_s"] = time.monotonic() - t
                job["phase"] = "import"
            elif job["phase"] == "import":
                whatifs[job["j"]].import_world(job["path"])
                job["path"].unlink()
                job["import_s"] = time.monotonic() - t
                job["phase"] = "advance"
                job["remaining"] = WHATIF_TICKS
                job["advance_s"] = 0.0
            else:
                n = min(SLICE, job["remaining"]) if chunked else job["remaining"]
                whatifs[job["j"]].step(n)
                job["remaining"] -= n
                job["advance_s"] += time.monotonic() - t
            return job["phase"] == "advance" and job["remaining"] == 0

        with Monitor() as mon:
            while True:
                now = time.monotonic()
                if now >= end:
                    break
                for k, s in enumerate(lives):
                    if now >= due[k]:
                        r = s.step(BLOCK)
                        s.state()
                        t = time.monotonic()
                        times[k].append(t)
                        ticks[k] += r.advanced
                        due[k] = next_due(due[k], t)
                if job is None and now >= next_whatif:
                    job = {"k": count % LIVE, "j": count % WHATIF_WORKSPACES, "phase": "export",
                           "start": now, "scheduled": next_whatif}
                    next_whatif += WHATIF_EVERY_S
                    count += 1
                if job is not None:
                    while True:
                        done = run_job_part(job)
                        if done or chunked:
                            break
                    if done:
                        finished = time.monotonic()
                        whatif_log.append({
                            "export_s": job["export_s"], "import_s": job["import_s"], "advance_s": job["advance_s"],
                            "total_s": finished - job["start"], "late_start_s": job["start"] - job["scheduled"],
                        })
                        job = None
                    continue
                wait = min(min(due), next_whatif, end) - time.monotonic()
                if wait > 0:
                    time.sleep(wait)
        t_end = time.monotonic()
        return {
            "live": [live_stats(times[k], ticks[k], t0, t_end) for k in range(LIVE)],
            "whatifs": whatif_log,
            "monitor": mon.result,
        }
    finally:
        for s in lives + whatifs:
            s.close()


# ----- threads -----

def run_threads() -> dict[str, Any]:
    lives = [make_session("threads", k) for k in range(LIVE)]
    whatifs = [make_session("threads_wi", j) for j in range(WHATIF_WORKSPACES)]
    try:
        for k, s in enumerate(lives):
            prepare_live(s, k)
        prepare_whatif(whatifs)

        times: list[list[float]] = [[] for _ in lives]
        ticks = [0] * LIVE
        whatif_log: list[dict[str, float]] = []
        errors: list[str] = []
        t0 = time.monotonic() + 0.5
        end = t0 + DURATION_S

        def live_loop(k: int) -> None:
            try:
                s = lives[k]
                due = t0
                while True:
                    now = time.monotonic()
                    if now >= end:
                        return
                    if now < due:
                        time.sleep(min(due, end) - now)
                        continue
                    r = s.step(BLOCK)
                    s.state()
                    t = time.monotonic()
                    times[k].append(t)
                    ticks[k] += r.advanced
                    due = next_due(due, t)
            except Exception as exc:  # noqa: BLE001
                errors.append(f"live {k}: {type(exc).__name__}: {exc}")

        def whatif_loop() -> None:
            try:
                scheduled = t0 + WHATIF_EVERY_S
                count = 0
                while True:
                    now = time.monotonic()
                    if now >= end:
                        return
                    if now < scheduled:
                        time.sleep(min(scheduled, end) - now)
                        continue
                    k, j = count % LIVE, count % WHATIF_WORKSPACES
                    start = time.monotonic()
                    path = lives[k].export_world()
                    t1 = time.monotonic()
                    whatifs[j].import_world(path)
                    path.unlink()
                    t2 = time.monotonic()
                    whatifs[j].step(WHATIF_TICKS)
                    t3 = time.monotonic()
                    whatif_log.append({"export_s": t1 - start, "import_s": t2 - t1, "advance_s": t3 - t2,
                                       "total_s": t3 - start, "late_start_s": start - scheduled})
                    scheduled += WHATIF_EVERY_S
                    count += 1
            except Exception as exc:  # noqa: BLE001
                errors.append(f"what-if: {type(exc).__name__}: {exc}")

        threads = [threading.Thread(target=live_loop, args=(k,)) for k in range(LIVE)]
        threads.append(threading.Thread(target=whatif_loop))
        with Monitor() as mon:
            for th in threads:
                th.start()
            for th in threads:
                th.join(timeout=DURATION_S + 120)
        hung = [th.name for th in threads if th.is_alive()]
        if hung:
            errors.append(f"threads still running after the deadline: {hung}")
        t_end = max(end, time.monotonic()) if not hung else end
        return {
            "live": [live_stats(times[k], ticks[k], t0, min(t_end, end)) for k in range(LIVE)],
            "whatifs": whatif_log,
            "errors": errors,
            "monitor": mon.result,
        }
    finally:
        for s in lives + whatifs:
            s.close()


# ----- processes -----

def live_process(conn: Connection, k: int) -> None:
    configure_logging()
    s = make_session("processes", k)
    try:
        prepare_live(s, k)
        conn.send(("ready",))
        _, t0, end = conn.recv()
        times: list[float] = []
        ticks = 0
        due = t0
        while True:
            now = time.monotonic()
            if now >= end:
                break
            if now < due:
                if conn.poll(min(due, end) - now):
                    msg = conn.recv()
                    if msg[0] == "export":
                        start = time.monotonic()
                        path = s.export_world()
                        conn.send(("path", str(path), time.monotonic() - start))
                continue
            r = s.step(BLOCK)
            s.state()
            t = time.monotonic()
            times.append(t)
            ticks += r.advanced
            due = next_due(due, t)
        conn.send(("stats", times, ticks))
    except Exception as exc:  # noqa: BLE001
        conn.send(("error", f"{type(exc).__name__}: {exc}"))
    finally:
        s.close()


def whatif_process(conn: Connection) -> None:
    configure_logging()
    whatifs = [make_session("processes_wi", j) for j in range(WHATIF_WORKSPACES)]
    try:
        prepare_whatif(whatifs)
        conn.send(("ready",))
        while True:
            msg = conn.recv()
            if msg[0] != "whatif":
                break
            _, path, j = msg
            t0 = time.monotonic()
            whatifs[j].import_world(path)
            Path(path).unlink()
            t1 = time.monotonic()
            whatifs[j].step(WHATIF_TICKS)
            conn.send(("done", t1 - t0, time.monotonic() - t1))
    except Exception as exc:  # noqa: BLE001
        conn.send(("error", f"{type(exc).__name__}: {exc}"))
    finally:
        for s in whatifs:
            s.close()


def run_processes() -> dict[str, Any]:
    ctx = mp.get_context("spawn")
    lives = []
    for k in range(LIVE):
        parent, child = ctx.Pipe()
        p = ctx.Process(target=live_process, args=(child, k))
        p.start()
        lives.append((p, parent))
    wparent, wchild = ctx.Pipe()
    wproc = ctx.Process(target=whatif_process, args=(wchild,))
    wproc.start()
    errors: list[str] = []
    for p, conn in lives + [(wproc, wparent)]:
        msg = conn.recv()
        if msg[0] != "ready":
            errors.append(str(msg))
    if errors:
        for p, _ in lives + [(wproc, wparent)]:
            p.kill()
        return {"errors": errors}

    t0 = time.monotonic() + 0.5
    end = t0 + DURATION_S
    for _, conn in lives:
        conn.send(("start", t0, end))
    whatif_log: list[dict[str, float]] = []
    with Monitor() as mon:
        scheduled = t0 + WHATIF_EVERY_S
        count = 0
        while True:
            now = time.monotonic()
            if now >= end - 0.5:  # a request must reach the live loop before it stops
                break
            if now < scheduled:
                time.sleep(min(scheduled, end - 0.5) - now)
                continue
            k, j = count % LIVE, count % WHATIF_WORKSPACES
            start = time.monotonic()
            lives[k][1].send(("export",))
            msg = lives[k][1].recv()
            if msg[0] != "path":
                errors.append(f"export from live {k}: {msg}")
                break
            t1 = time.monotonic()
            wparent.send(("whatif", msg[1], j))
            done = wparent.recv()
            if done[0] != "done":
                errors.append(f"what-if: {done}")
                break
            t3 = time.monotonic()
            whatif_log.append({"export_s": msg[2], "export_roundtrip_s": t1 - start, "import_s": done[1],
                               "advance_s": done[2], "total_s": t3 - start, "late_start_s": start - scheduled})
            scheduled += WHATIF_EVERY_S
            count += 1
        stats = []
        for k, (p, conn) in enumerate(lives):
            msg = conn.recv()
            if msg[0] != "stats":
                errors.append(f"live {k}: {msg}")
                stats.append(None)
            else:
                stats.append(msg)
    wparent.send(("quit",))
    for p, _ in lives + [(wproc, wparent)]:
        p.join(timeout=60)
    live = [live_stats(m[1], m[2], t0, end) for m in stats if m is not None]
    return {"live": live, "whatifs": whatif_log, "errors": errors, "monitor": mon.result}


def summarize(form: str, result: dict[str, Any]) -> dict[str, Any]:
    live = result.get("live", [])
    wis = result.get("whatifs", [])
    mon = result.get("monitor")
    summary = {
        "form": form,
        "errors": result.get("errors", []),
        "live": live,
        "min_ticks_per_s": min((x["ticks_per_s"] for x in live), default=0),
        "max_pause_s": max((x["max_pause_s"] for x in live), default=0),
        "worst_p95_pause_s": max((x["p95_pause_s"] for x in live), default=0),
        "pauses_over_limit": sum(x["pauses_over_limit"] for x in live),
        "whatifs_done": len(wis),
        "whatif_mean_total_s": round(sum(w["total_s"] for w in wis) / len(wis), 2) if wis else None,
        "whatif_max_total_s": round(max(w["total_s"] for w in wis), 2) if wis else None,
        "whatif_max_late_start_s": round(max(w["late_start_s"] for w in wis), 2) if wis else None,
        "whatifs": wis,
    }
    if mon is not None:
        summary.update({"cpu_util_pct": mon.cpu_util_pct, "mem_peak_mib": mon.mem_peak_mib,
                        "cpu_per_wall": round(mon.cpu_per_wall, 2), "monitor_wall_s": round(mon.wall_s, 1)})
    summary["meets_criterion"] = bool(live) and summary["max_pause_s"] <= FREEZE_LIMIT_S and not summary["errors"]
    return summary


def main() -> int:
    configure_logging()
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--forms", nargs="+", choices=FORMS, default=list(FORMS))
    parser.add_argument("--warm-export", action="store_true",
                        help="do one export-world per live session before the test (JIT warm-up)")
    parser.add_argument("--tag", default="")
    args = parser.parse_args()
    if args.warm_export:
        os.environ["FREEZE_WARM_EXPORT"] = "1"  # inherited by spawned processes
        global WARM_EXPORT
        WARM_EXPORT = True

    runners = {
        "single": lambda: run_single(chunked=False),
        "single_chunked": lambda: run_single(chunked=True),
        "threads": run_threads,
        "processes": run_processes,
    }
    rows = []
    for form in args.forms:
        for attempt in range(2):
            logger.info("Freeze test form=%s (attempt %d)", form, attempt + 1)
            result = runners[form]()
            mon = result.get("monitor")
            # The live loops are paced, so CPU use is lower than in a batch run; a host sleep shows
            # up as a monitor wall time far above the 60 s of the test.
            if mon is not None and mon.wall_s > DURATION_S * 1.5 and attempt == 0:
                logger.warning("form=%s took %.0f s of wall time for a %d s test, repeating", form, mon.wall_s, DURATION_S)
                continue
            break
        row = summarize(form, result)
        rows.append(row)
        logger.info("form=%s: max pause %.3f s, worst p95 %.3f s, min ticks/s %.1f", form,
                    row["max_pause_s"], row["worst_p95_pause_s"], row["min_ticks_per_s"])

    print(f"\nFreeze test: {LIVE} live sessions at {RATE:.0f} ticks/s (blocks of {BLOCK}), what-if every "
          f"{WHATIF_EVERY_S:.0f} s ({WHATIF_TICKS} ticks), {DURATION_S:.0f} s, rule 3")
    print(f"{'form':>15} {'min t/s':>7} {'max pause s':>11} {'worst p95 s':>11} {'>0.5 s':>6} {'what-ifs':>8} "
          f"{'wi mean/max s':>13} {'CPU % per core':>24} {'mem MiB':>8} ok")
    for r in rows:
        util = " ".join(f"{v:>4.0f}" for v in r.get("cpu_util_pct", {}).values())
        wi = f"{r['whatif_mean_total_s']}/{r['whatif_max_total_s']}"
        print(f"{r['form']:>15} {r['min_ticks_per_s']:>7} {r['max_pause_s']:>11} {r['worst_p95_pause_s']:>11} "
              f"{r['pauses_over_limit']:>6} {r['whatifs_done']:>8} {wi:>13} {util:>24} {r.get('mem_peak_mib', ''):>8} "
              f"{r['meets_criterion']}")
        for e in r["errors"]:
            print(f"{'':>15} ERROR: {e}")
    name = "freeze" + (f"_{args.tag}" if args.tag else "")
    print("Saved:", save_json(name, {"env": environment_info(), "warm_export": WARM_EXPORT, "rows": rows}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
