"""A2 measurement: rule 3 with the fixed product sequence over several seeds.

For each seed (100,000 ticks, Stochastic, fixed product sequence on): finished products, work
completed (nominal processing time, see aclopi/sim/kpis.py), mean flow time (the existing KPI,
from the first operation start), created products, wall time of the run, and the decision
requests rule 4 would generate (rule 4 without decider, which runs the same simulation; checked).
Also, for information only, the mean flow time from ProductCreationTime (not a KPI).
At the end: mean and standard deviation across seeds of finished products and work completed.

Usage (from the repository root):
    python scripts/a2/measure_fixed_sequence.py --seeds 42 7 123 2024 31415 --horizon 100000
Results: results/a2/fixed_sequence_rule3.json
"""

from __future__ import annotations

import argparse
import json
import logging
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # scripts/

from rule4_checks import run  # noqa: E402

from aclopi.sim import SimulationSession  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
OUTPUT = REPO_ROOT / "results" / "a2" / "fixed_sequence_rule3.json"
FLOW_FROM_CREATION = (
    'platform-local [ -> ifelse-value any? products with [Product.State = "death"] '
    '[mean [last ProductRealCompletion - ProductCreationTime] of products with [Product.State = "death"]] [-1] ]'
)


def main() -> int:
    logging.basicConfig(level=logging.WARNING)
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--seeds", type=int, nargs="+", default=[42, 7, 123, 2024, 31415])
    parser.add_argument("--horizon", type=int, default=100000)
    args = parser.parse_args()

    rows = []
    with SimulationSession("a2_fixed_sequence") as s:
        run(s, 3, 1, 10000, fixed_product_sequence=True)  # JVM warm-up
        for seed in args.seeds:
            r3 = run(s, 3, seed, args.horizon, fixed_product_sequence=True)
            flow_creation = float(s.link.report(FLOW_FROM_CREATION))
            r4 = run(s, 4, seed, args.horizon, poll=True, fixed_product_sequence=True)
            same = r4.kpis == r3.kpis
            k = r3.kpis
            rows.append({
                "seed": seed, "finished": k["finished"], "work_completed": round(k["work_completed"], 2),
                "mean_flow_time": k["mean_flow_time"], "mean_flow_from_creation": flow_creation,
                "created": k["created"], "wall_s": round(r3.wall_s, 1), "requests": r4.requests,
                "rule4_without_decider_same_kpis": same,
            })
            print(json.dumps(rows[-1]), flush=True)

    finished = [r["finished"] for r in rows]
    work = [r["work_completed"] for r in rows]
    summary = {
        "finished_mean": statistics.mean(finished), "finished_stdev": statistics.stdev(finished) if len(rows) > 1 else 0.0,
        "work_completed_mean": statistics.mean(work), "work_completed_stdev": statistics.stdev(work) if len(rows) > 1 else 0.0,
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps({"horizon": args.horizon, "rows": rows, "summary": summary}, indent=1), encoding="utf-8")

    print()
    print("| seed | finished | work completed | mean flow (from 1st start) | mean flow (from creation) | created | wall (s) | requests |")
    print("|---|---|---|---|---|---|---|---|")
    for r in rows:
        print(f"| {r['seed']} | {r['finished']} | {r['work_completed']:.1f} | {r['mean_flow_time']:.1f} | "
              f"{r['mean_flow_from_creation']:.1f} | {r['created']} | {r['wall_s']} | {r['requests']} |")
    print(f"\nfinished: mean {summary['finished_mean']:.2f}, stdev {summary['finished_stdev']:.2f}")
    print(f"work completed: mean {summary['work_completed_mean']:.1f}, stdev {summary['work_completed_stdev']:.1f}")
    return 0 if all(r["rule4_without_decider_same_kpis"] for r in rows) else 1


if __name__ == "__main__":
    sys.exit(main())
