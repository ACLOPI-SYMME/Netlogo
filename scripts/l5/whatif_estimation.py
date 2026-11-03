"""Quality of the what-if entry estimate (with travel) and of the entry-beyond-cap criterion (L5.4).

Runs rule 4 WITHOUT a decider (exactly rule 3, see docs/rule4-decision-hook.md; the what-if needs
rule 4 to force the tested machine) for 3 seeds x 20,000 ticks. About every 1000 ticks it takes the
next real decision request and runs a what-if of its first two candidates exactly as the platform
does: entry estimated with travel (aclopi.sim.whatif.estimate_entry), the earlier estimate first,
one snapshot, one copy per option (run_option), cap 3000 ticks, budget 10 s.

Per what-if (CSV): estimated and real ticks to entry of each option, stop reasons, whether the
first copy (earlier estimate) really entered first, entry-beyond-cap, seconds and status.
Summary (JSON): share of first-was-first, estimate error (estimate - real, ticks) over the copies
that entered, how often entry-beyond-cap would fire, ok / timeout / cap.

    python scripts/l5/whatif_estimation.py [--seeds 42 7 123] [--ticks 20000] [--every 1000]
Results: results/l5/whatif_estimation.csv and .json
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import statistics
import sys
import time
from pathlib import Path
from typing import Any

from aclopi.sim import SimulationSession
from aclopi.sim.candidates import read_model_static
from aclopi.sim.decisions import clear_decisions, pending_decisions, run_until_decision
from aclopi.sim.whatif import estimate_entry, run_option

REPO_ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = REPO_ROOT / "results" / "l5"
CAP = 3000
BUDGET_S = 10.0

logger = logging.getLogger("whatif_estimation")


def whatifs_for_seed(seed: int, ticks: int, every: int) -> list[dict[str, Any]]:
    rows = []
    with SimulationSession(f"est_real_{seed}") as real, SimulationSession(f"est_copy_{seed}") as copy:
        real.setup(seed=seed, rule=4, horizon_ticks=ticks + 5000)
        static = read_model_static(real)
        next_at = every
        while real.ticks < ticks:
            if real.ticks < next_at:
                real.step(min(next_at - real.ticks, 2000))
                continue
            clear_decisions(real)  # requests queued during the plain steps are stale by now
            run_until_decision(real, 5000)
            requests = pending_decisions(real)
            clear_decisions(real)
            if not requests:
                break
            req = requests[0]
            next_at = real.ticks + every
            start = real.ticks
            options = list(req.candidates[:2])
            state = real.state()
            now = float(state["time"])
            est = {m: int(round((estimate_entry(state, req.who, m, req.operation, static)[0] - now) / static.tick_time))
                   for m in options}
            order = sorted(options, key=lambda m: (est[m], options.index(m)))
            t0 = time.perf_counter()
            path = real.export_world()
            deadline = time.time() + BUDGET_S - (time.perf_counter() - t0)
            results: dict[str, Any] = {}
            window = None
            try:
                for machine in order:
                    if time.time() >= deadline:
                        results[machine] = None
                        continue
                    copy.import_world(path)
                    r = run_option(copy, static, req.who, req.seq, machine, CAP, window_tick=window, deadline=deadline)
                    results[machine] = r
                    if window is None:
                        window = r.stop_tick
            finally:
                path.unlink(missing_ok=True)
            seconds = time.perf_counter() - t0
            real_entry = {m: (r.entry_tick - start) if r is not None and r.entered else None for m, r in results.items()}
            first, second = order
            a, b = real_entry[first], real_entry[second]
            stops = {m: (r.stop_reason if r is not None else "skipped") for m, r in results.items()}
            first_was_first: bool | None
            if a is not None and b is not None:
                first_was_first = a <= b
            elif a is not None:  # the second did not enter: known to be later only if pruned or capped
                first_was_first = True if stops[second] in ("pruned", "cap") else None
            elif b is not None:
                first_was_first = False
            else:
                first_was_first = None  # neither entered
            timed_out = any(r is None or r.timed_out for r in results.values())
            row = {
                "seed": seed, "tick": start, "product": req.who, "seq": req.seq, "operation": req.operation,
                "first": first, "second": second,
                "est_first": est[first], "est_second": est[second],
                "real_first": a, "real_second": b,
                "stop_first": stops[first], "stop_second": stops[second],
                "first_was_first": first_was_first,
                "beyond_cap": all(t > CAP for t in est.values()),
                "seconds": round(seconds, 3),
                "status": "timeout" if timed_out else "ok",
            }
            rows.append(row)
            logger.info("seed %d tick %d: est %s/%s real %s/%s stops %s/%s first_was_first=%s %.2f s %s", seed, start,
                        est[first], est[second], a, b, stops[first], stops[second], first_was_first, seconds, row["status"])
    return rows


def pct(values: list[float], q: float) -> float:
    s = sorted(values)
    return s[min(len(s) - 1, int(round(q * (len(s) - 1))))]


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    errors, abs_errors = [], []
    for r in rows:
        for which in ("first", "second"):
            if r[f"real_{which}"] is not None:
                e = r[f"est_{which}"] - r[f"real_{which}"]
                errors.append(e)
                abs_errors.append(abs(e))
    known = [r for r in rows if r["first_was_first"] is not None]
    stops = [r[f"stop_{w}"] for r in rows for w in ("first", "second")]
    seconds = [r["seconds"] for r in rows]
    return {
        "whatifs": len(rows),
        "first_was_first_share": round(sum(bool(r["first_was_first"]) for r in known) / len(known), 3) if known else None,
        "first_was_first_known": len(known),
        "estimate_error_ticks": {
            "copies_entered": len(errors),
            "mean_signed": round(statistics.fmean(errors), 1) if errors else None,
            "mean_abs": round(statistics.fmean(abs_errors), 1) if abs_errors else None,
            "p95_abs": pct(abs_errors, 0.95) if abs_errors else None,
            "max_abs": max(abs_errors) if abs_errors else None,
        },
        "entry_beyond_cap_would_fire": sum(r["beyond_cap"] for r in rows),
        "status": {"ok": sum(r["status"] == "ok" for r in rows), "timeout": sum(r["status"] == "timeout" for r in rows)},
        "first_copy_cap": sum(r["stop_first"] == "cap" for r in rows),
        "stop_reasons": {k: stops.count(k) for k in sorted(set(stops))},
        "seconds": {"mean": round(statistics.fmean(seconds), 2), "p95": pct(seconds, 0.95), "max": max(seconds)} if seconds else None,
    }


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
    logging.getLogger("aclopi").setLevel(logging.WARNING)
    parser = argparse.ArgumentParser()
    parser.add_argument("--seeds", type=int, nargs="+", default=[42, 7, 123])
    parser.add_argument("--ticks", type=int, default=20000)
    parser.add_argument("--every", type=int, default=1000)
    args = parser.parse_args()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    for seed in args.seeds:
        rows += whatifs_for_seed(seed, args.ticks, args.every)
    with open(OUT_DIR / "whatif_estimation.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    summary = summarize(rows)
    (OUT_DIR / "whatif_estimation.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    print(json.dumps(summary, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
