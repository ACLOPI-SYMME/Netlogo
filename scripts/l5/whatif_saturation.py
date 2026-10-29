"""plant-saturated criterion (L5.4, to be confirmed): how do machine loads relate to what-ifs
that do not finish before the cap?

Runs rule 4 WITHOUT a decider (exactly rule 3, see docs/rule4-decision-hook.md; the what-if needs
rule 4 to force the tested machine) for 3 seeds x 20,000 ticks. About every 1000 ticks it takes the
next real decision request and runs a what-if of its first two candidates exactly as the platform
does (one snapshot, one copy per option with aclopi.sim.whatif.run_option, cap 2000 ticks, 5 s).

Per what-if (CSV): loads of the two machines (products queued at them or heading to them), ticks
simulated and to entry, seconds, status (ok/timeout) and whether it finished before the cap (the
first copy entered its machine). Summary: for each N, the what-ifs that would NOT be skipped
(min(load_a, load_b) < N) and the share of them that finish before the cap; the largest N that
keeps that share >= 95 %.

    python scripts/l5/whatif_saturation.py [--seeds 42 7 123] [--ticks 20000] [--every 1000]
Results: results/l5/whatif_saturation.csv and .json
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import sys
import time
from pathlib import Path
from typing import Any

from aclopi.sim import SimulationSession
from aclopi.sim.candidates import machine_loads, read_model_static
from aclopi.sim.decisions import clear_decisions, pending_decisions, run_until_decision
from aclopi.sim.whatif import estimate_entry, run_option

REPO_ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = REPO_ROOT / "results" / "l5"
CAP = 2000
BUDGET_S = 5.0

logger = logging.getLogger("whatif_saturation")


def whatifs_for_seed(seed: int, ticks: int, every: int) -> list[dict[str, Any]]:
    rows = []
    with SimulationSession(f"sat_real_{seed}") as real, SimulationSession(f"sat_copy_{seed}") as copy:
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
            options = list(req.candidates[:2])
            state = real.state()
            loads = machine_loads(state, exclude=req.who)
            order = sorted(options, key=lambda m: estimate_entry(state, req.who, m, req.operation, static)[0])
            t0 = time.perf_counter()
            path = real.export_world()
            deadline = time.time() + BUDGET_S - (time.perf_counter() - t0)
            results = {}
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
            first = results[order[0]]
            timed_out = any(r is None or r.timed_out for r in results.values())
            row = {
                "seed": seed, "tick": real.ticks, "product": req.who, "seq": req.seq, "operation": req.operation,
                "machine_a": options[0], "machine_b": options[1],
                "load_a": len(loads[options[0]]), "load_b": len(loads[options[1]]),
                "min_load": min(len(loads[options[0]]), len(loads[options[1]])),
                "first": order[0], "first_entered": bool(first and first.entered),
                "first_ticks_to_entry": first.ticks_simulated if first and first.entered else None,
                "ticks_a": results[options[0]].ticks_simulated if results[options[0]] else None,
                "ticks_b": results[options[1]].ticks_simulated if results[options[1]] else None,
                "stop_a": results[options[0]].stop_reason if results[options[0]] else "skipped",
                "stop_b": results[options[1]].stop_reason if results[options[1]] else "skipped",
                "seconds": round(seconds, 3),
                "status": "timeout" if timed_out else "ok",
                "before_cap": bool(first and first.entered) and not timed_out,
            }
            rows.append(row)
            logger.info("seed %d tick %d: loads %s/%s first %s %s ticks, %.2f s %s", seed, row["tick"], row["load_a"],
                        row["load_b"], row["first"], row["first_ticks_to_entry"], seconds, row["status"])
    return rows


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    max_load = max((r["min_load"] for r in rows), default=0)
    table = []
    for n in range(1, max_load + 2):
        kept = [r for r in rows if r["min_load"] < n]
        share = sum(r["before_cap"] for r in kept) / len(kept) if kept else None
        table.append({"N": n, "kept": len(kept), "skipped": len(rows) - len(kept),
                      "before_cap_share": round(share, 3) if share is not None else None})
    ok_n = [t["N"] for t in table if t["before_cap_share"] is not None and t["before_cap_share"] >= 0.95]
    seconds = sorted(r["seconds"] for r in rows)
    ticks = sorted(r["first_ticks_to_entry"] for r in rows if r["first_ticks_to_entry"] is not None)
    return {
        "whatifs": len(rows),
        "before_cap": sum(r["before_cap"] for r in rows),
        "timeouts": sum(r["status"] == "timeout" for r in rows),
        "by_min_load": {str(k): sum(r["min_load"] == k for r in rows) for k in range(max_load + 1)},
        "table": table,
        "largest_N_with_95pct": max(ok_n) if ok_n else None,
        "all_before_cap_without_skipping": table[-1]["before_cap_share"] if table else None,
        "seconds": {"mean": round(sum(seconds) / len(seconds), 2), "p95": seconds[int(0.95 * (len(seconds) - 1))],
                    "max": seconds[-1]} if seconds else None,
        "first_ticks_to_entry": {"mean": round(sum(ticks) / len(ticks)), "p95": ticks[int(0.95 * (len(ticks) - 1))],
                                 "max": ticks[-1]} if ticks else None,
    }


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
    for name in ("aclopi",):
        logging.getLogger(name).setLevel(logging.WARNING)
    parser = argparse.ArgumentParser()
    parser.add_argument("--seeds", type=int, nargs="+", default=[42, 7, 123])
    parser.add_argument("--ticks", type=int, default=20000)
    parser.add_argument("--every", type=int, default=1000)
    args = parser.parse_args()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    for seed in args.seeds:
        rows += whatifs_for_seed(seed, args.ticks, args.every)
    with open(OUT_DIR / "whatif_saturation.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    summary = summarize(rows)
    (OUT_DIR / "whatif_saturation.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    print(json.dumps(summary, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
