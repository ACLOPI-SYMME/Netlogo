"""Summary of the baseline runs without LLM (rule3, b1, b1b): scripts/a4/run_experiments.py --combined.

    per strategy   makespan_ticks mean and standard deviation, mean_flow_time and work_completed (means)
    per seed       makespan of b1 and b1b minus rule3 (ticks and %)
    b1 decisions   percentiles 10..90 of gap_finish and gap_finish_plus_next (the candidates result's,
                   over all candidates) and % obvious / uncertain / very_close re-classified with
                   aclopi.agent.triage.classify for u_wide in 100, 150, 200 and u_narrow in 30, 50, 80
Input: the combined CSV and the agent's decision log of those runs (ACLOPI_AGENT_LOG; b1 records carry
the candidates). Output: <out>.md and <out>.csv (section,key,value).

Usage:
    python scripts/a4/baseline_summary.py --runs results/a4/baseline_5seeds.csv \
        --decisions results/a4/baseline/decisions.jsonl --out results/a4/baseline_5seeds_summary
"""

from __future__ import annotations

import argparse
import csv
import json
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

from aclopi.agent.triage import TriageParams, classify

STRATEGIES = ("rule3", "b1", "b1b")
U_WIDE, U_NARROW = (100.0, 150.0, 200.0), (30.0, 50.0, 80.0)
QUANTILES = (0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9)


def quantile(values: list[float], q: float) -> float:
    s = sorted(values)
    return s[min(len(s) - 1, int(round(q * (len(s) - 1))))]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--runs", required=True)
    parser.add_argument("--decisions", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    runs = list(csv.DictReader(Path(args.runs).open(encoding="utf-8")))
    rows: list[tuple[str, str, str]] = []
    md = [f"# Línea base sin LLM ({len(runs)} corridas)", "", f"Corridas: `{args.runs}`.", "",
          "## Por estrategia", "", "| Estrategia | n | makespan medio (ticks) | desv. | mean_flow_time | work_completed | todas terminadas |",
          "|---|---|---|---|---|---|---|"]
    for st in STRATEGIES:
        rs = [r for r in runs if r["strategy"] == st]
        if not rs:
            continue
        ms = [float(r["makespan_ticks"]) for r in rs]
        flow = statistics.mean(float(r["mean_flow_time"]) for r in rs)
        work = statistics.mean(float(r["work_completed"]) for r in rs)
        sd = statistics.stdev(ms) if len(ms) > 1 else 0.0
        done = sum(r["all_done"] == "True" for r in rs)
        md.append(f"| {st} | {len(rs)} | {statistics.mean(ms):.0f} | {sd:.0f} | {flow:.1f} | {work:.1f} | {done}/{len(rs)} |")
        rows += [("strategy", f"{st}_makespan_mean", f"{statistics.mean(ms):.1f}"), ("strategy", f"{st}_makespan_sd", f"{sd:.1f}"),
                 ("strategy", f"{st}_mean_flow_time", f"{flow:.2f}"), ("strategy", f"{st}_work_completed", f"{work:.2f}"),
                 ("strategy", f"{st}_all_done", f"{done}/{len(rs)}")]

    md += ["", "## Por semilla (makespan en ticks; diferencia contra rule3)", "",
           "| Semilla | rule3 | b1 | b1 − rule3 | b1b | b1b − rule3 |", "|---|---|---|---|---|---|"]
    by_seed: dict[str, dict[str, float]] = defaultdict(dict)
    for r in runs:
        by_seed[r["seed"]][r["strategy"]] = float(r["makespan_ticks"])
    for seed in sorted(by_seed, key=int):
        m = by_seed[seed]
        cells = [seed, f"{m.get('rule3', float('nan')):.0f}"]
        for st in ("b1", "b1b"):
            if st in m and "rule3" in m:
                d = m[st] - m["rule3"]
                cells += [f"{m[st]:.0f}", f"{d:+.0f} ({100 * d / m['rule3']:+.1f} %)"]
                rows.append(("seed", f"s{seed}_{st}_minus_rule3", f"{d:.0f}"))
            else:
                cells += ["", ""]
        md.append("| " + " | ".join(cells) + " |")

    b1_sessions = {r["session_id"] for r in runs if r["strategy"] == "b1"}
    decisions = [json.loads(line) for line in Path(args.decisions).open(encoding="utf-8") if line.strip()]
    b1 = [d for d in decisions if d.get("session_id") in b1_sessions and d.get("candidates")]
    gaps = {k: [float(d[k]) for d in b1 if d.get(k) is not None] for k in ("gap_finish", "gap_finish_plus_next")}
    single = sum(1 for d in b1 if len(d["candidates"]) == 1)
    md += ["", f"## Decisiones de b1 ({len(b1)} con candidatas; {single} con una sola candidata, sin gap)", "",
           "Percentiles de los gaps (u.t., segunda − mejor, sobre todas las candidatas):", "",
           "| | " + " | ".join(f"p{int(q * 100)}" for q in QUANTILES) + " |", "|---|" + "---|" * len(QUANTILES)]
    for k, vs in gaps.items():
        if vs:
            md.append(f"| {k} | " + " | ".join(f"{quantile(vs, q):.1f}" for q in QUANTILES) + " |")
            rows += [("gaps", f"{k}_p{int(q * 100)}", f"{quantile(vs, q):.2f}") for q in QUANTILES]
    md += ["", "Nivel con el filtro del agente (`aclopi.agent.triage.classify`), % de decisiones de b1 "
           "(obvia / dudosa / muy reñida):", "", "| U_amplio \\ U_estrecho | " + " | ".join(f"{n:.0f}" for n in U_NARROW) + " |",
           "|---|" + "---|" * len(U_NARROW)]
    for w in U_WIDE:
        cells = []
        for n in U_NARROW:
            c = Counter(classify(d["candidates"], TriageParams(u_wide=w, u_narrow=n)).level for d in b1)
            pct = {lv: 100 * c.get(lv, 0) / len(b1) if b1 else 0.0 for lv in ("obvious", "uncertain", "very_close")}
            cells.append(f"{pct['obvious']:.0f} / {pct['uncertain']:.0f} / {pct['very_close']:.0f}")
            rows += [("triage", f"w{w:.0f}_n{n:.0f}_{lv}", f"{v:.1f}") for lv, v in pct.items()]
        md.append(f"| {w:.0f} | " + " | ".join(cells) + " |")

    out = Path(args.out)
    out.with_suffix(".md").write_text("\n".join(md) + "\n", encoding="utf-8")
    with out.with_suffix(".csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["section", "key", "value"])
        w.writerows(rows)
    print("\n".join(md))
    return 0


if __name__ == "__main__":
    sys.exit(main())
