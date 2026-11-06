"""Summary per scenario of runs without LLM (rule3, b1, b1b): scripts/a4/run_experiments.py --scenarios --combined.

    per scenario and strategy   makespan_ticks mean and standard deviation, mean_flow_time (mean),
                                scenario events applied / skipped (S3: failures; totals over the seeds)
    paired test (by seed)       b1 - rule3 and b1b - rule3 in makespan_ticks: mean difference and 95 %
                                interval (Student t with n-1 degrees of freedom)
Output: <out>.md and <out>.csv (scenario,key,value).

Usage:
    python scripts/a4/scenario_summary.py --runs results/a4/scenarios_5seeds.csv --out results/a4/scenarios_5seeds_summary
"""

from __future__ import annotations

import argparse
import csv
import math
import statistics
import sys
from collections import defaultdict
from pathlib import Path

STRATEGIES = ("rule3", "b1", "b1b")
# two-sided 95 % Student t quantiles, by degrees of freedom
T95 = {1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571, 6: 2.447, 7: 2.365, 8: 2.306, 9: 2.262, 10: 2.228,
       12: 2.179, 15: 2.131, 20: 2.086, 30: 2.042}


def t95(df: int) -> float:
    return T95.get(df) or T95[max(k for k in T95 if k <= df)] if df >= 1 else math.nan


def paired(diffs: list[float]) -> tuple[float, float, float]:
    """Mean difference and its 95 % interval."""
    mean = statistics.mean(diffs)
    if len(diffs) < 2:
        return mean, math.nan, math.nan
    half = t95(len(diffs) - 1) * statistics.stdev(diffs) / math.sqrt(len(diffs))
    return mean, mean - half, mean + half


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--runs", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    every = list(csv.DictReader(Path(args.runs).open(encoding="utf-8")))
    runs = [r for r in every if r["all_done"] == "True"]  # a run that did not finish has no makespan
    left_out = [f"{r['strategy']} {r['scenario']} s{r['seed']} ({r['reason']})" for r in every if r["all_done"] != "True"]
    rows: list[tuple[str, str, str]] = [("all", "left_out", "; ".join(left_out))]
    md = [f"# Escenarios sin LLM ({len(every)} corridas)", "", f"Corridas: `{args.runs}`. Makespan en ticks.",
          f"Sin terminar, fuera del resumen y de su par en la prueba pareada: {', '.join(left_out) or 'ninguna'}."]
    for sc in sorted({r["scenario"] for r in runs}):
        rs = [r for r in runs if r["scenario"] == sc]
        md += ["", f"## {sc}", "", "| Estrategia | n | makespan medio | desv. | mean_flow_time | eventos aplicados / saltados | todas terminadas |",
               "|---|---|---|---|---|---|---|"]
        by_seed: dict[str, dict[str, float]] = defaultdict(dict)
        for st in STRATEGIES:
            sr = [r for r in rs if r["strategy"] == st]
            if not sr:
                continue
            ms = [float(r["makespan_ticks"]) for r in sr]
            for r in sr:
                by_seed[r["seed"]][st] = float(r["makespan_ticks"])
            sd = statistics.stdev(ms) if len(ms) > 1 else 0.0
            flow = statistics.mean(float(r["mean_flow_time"]) for r in sr)
            applied = sum(int(r["scenario_applied"] or 0) for r in sr)
            skipped = sum(int(r["scenario_skipped"] or 0) for r in sr)
            total = sum(1 for r in every if r["scenario"] == sc and r["strategy"] == st)
            md.append(f"| {st} | {len(sr)} | {statistics.mean(ms):.0f} | {sd:.0f} | {flow:.1f} | {applied} / {skipped} | {len(sr)}/{total} |")
            rows += [(sc, f"{st}_makespan_mean", f"{statistics.mean(ms):.1f}"), (sc, f"{st}_makespan_sd", f"{sd:.1f}"),
                     (sc, f"{st}_mean_flow_time", f"{flow:.2f}"), (sc, f"{st}_events_applied", str(applied)),
                     (sc, f"{st}_events_skipped", str(skipped)), (sc, f"{st}_all_done", f"{len(sr)}/{total}")]
        md += ["", "Prueba pareada por semilla (makespan, ticks):", "",
               "| Comparación | n | diferencia media | IC 95 % | % |", "|---|---|---|---|---|"]
        for st in ("b1", "b1b"):
            seeds = [s for s in by_seed if st in by_seed[s] and "rule3" in by_seed[s]]
            if not seeds:
                continue
            diffs = [by_seed[s][st] - by_seed[s]["rule3"] for s in seeds]
            mean, lo, hi = paired(diffs)
            base = statistics.mean(by_seed[s]["rule3"] for s in seeds)
            md.append(f"| {st} − rule3 | {len(seeds)} | {mean:+.0f} | [{lo:+.0f}, {hi:+.0f}] | {100 * mean / base:+.1f} % |")
            rows += [(sc, f"{st}_minus_rule3_mean", f"{mean:.1f}"), (sc, f"{st}_minus_rule3_ci_low", f"{lo:.1f}"),
                     (sc, f"{st}_minus_rule3_ci_high", f"{hi:.1f}")]

    out = Path(args.out)
    out.with_suffix(".md").write_text("\n".join(md) + "\n", encoding="utf-8")
    with out.with_suffix(".csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["scenario", "key", "value"])
        w.writerows(rows)
    print("\n".join(md))
    return 0


if __name__ == "__main__":
    sys.exit(main())
