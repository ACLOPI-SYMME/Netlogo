"""Agent (real LLM) against the runs without LLM on the original plant (S0), same seeds and product lists.

    per strategy   makespan_ticks mean / sd and mean_flow_time (mean), runs finished
    paired test    agent - rule3 and agent - b1 in makespan_ticks (by seed): mean difference and 95 % interval
    agent          % per decision level, LLM calls, failures, invalid JSON, latency p50 / p95, what-if
                   requested, 409 / 422 rejections, and how often it chose a machine other than B1's
                   (best by finish among the candidates)
Output: <out>.md and <out>.csv (key,value).

Usage:
    python scripts/a4/agent_summary.py --agent results/real_llm/final/agent_5seeds.csv
        --baseline results/a4/baseline_5seeds.csv --decisions results/real_llm/decisions.jsonl --out results/real_llm/agent_5seeds_summary
"""

from __future__ import annotations

import argparse
import csv
import json
import statistics
import sys
from collections import Counter
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from scenario_summary import paired  # noqa: E402

LEVELS = ("code-obvious", "llm", "llm-what-if", "code-fallback")


def b1_choice(rec: dict[str, Any]) -> str | None:
    cands = rec.get("candidates") or []
    if not cands:
        return None
    return min(cands, key=lambda c: (float(c["finish"]), int(str(c["machine"])[1:])))["machine"]


def nearest_rank(values: list[float], q: float) -> float:
    s = sorted(values)
    return s[max(0, min(len(s) - 1, int(round(q * len(s) + 0.5)) - 1))]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--agent", required=True)
    parser.add_argument("--baseline", required=True)
    parser.add_argument("--decisions", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    agent = list(csv.DictReader(Path(args.agent).open(encoding="utf-8")))
    base = [r for r in csv.DictReader(Path(args.baseline).open(encoding="utf-8")) if r["strategy"] in ("rule3", "b1", "b1b")]
    runs = [r for r in base + agent if r["all_done"] == "True" and int(r["n"]) == int(agent[0]["n"])]
    seeds = sorted({r["seed"] for r in agent}, key=int)
    by: dict[str, dict[str, dict[str, Any]]] = {}
    for r in runs:
        if r["seed"] in seeds:
            by.setdefault(r["strategy"], {})[r["seed"]] = r
    rows: list[tuple[str, str]] = []
    md = [f"# Agente con LLM real frente a rule3 / b1 / b1b (S0, semillas {' '.join(seeds)}, {agent[0]['n']} productos)", "",
          "| Estrategia | n | makespan medio | desv. | mean_flow_time |", "|---|---|---|---|---|"]
    for st in ("rule3", "b1", "b1b", "agent"):
        rs = list(by.get(st, {}).values())
        if not rs:
            continue
        ms = [float(r["makespan_ticks"]) for r in rs]
        flow = statistics.mean(float(r["mean_flow_time"]) for r in rs)
        sd = statistics.stdev(ms) if len(ms) > 1 else 0.0
        md.append(f"| {st} | {len(rs)} | {statistics.mean(ms):.0f} | {sd:.0f} | {flow:.1f} |")
        rows += [(f"{st}_makespan_mean", f"{statistics.mean(ms):.1f}"), (f"{st}_makespan_sd", f"{sd:.1f}"),
                 (f"{st}_mean_flow_time", f"{flow:.2f}"), (f"{st}_runs", str(len(rs)))]
    md += ["", "Prueba pareada por semilla (makespan, ticks):", "", "| Comparación | n | diferencia media | IC 95 % | % |",
           "|---|---|---|---|---|"]
    for ref in ("rule3", "b1"):
        common = [s for s in seeds if s in by.get("agent", {}) and s in by.get(ref, {})]
        if not common:
            continue
        diffs = [float(by["agent"][s]["makespan_ticks"]) - float(by[ref][s]["makespan_ticks"]) for s in common]
        mean, lo, hi = paired(diffs)
        ref_mean = statistics.mean(float(by[ref][s]["makespan_ticks"]) for s in common)
        md.append(f"| agent − {ref} | {len(common)} | {mean:+.0f} | [{lo:+.0f}, {hi:+.0f}] | {100 * mean / ref_mean:+.1f} % |")
        rows += [(f"agent_minus_{ref}_mean", f"{mean:.1f}"), (f"agent_minus_{ref}_ci_low", f"{lo:.1f}"),
                 (f"agent_minus_{ref}_ci_high", f"{hi:.1f}")]

    sessions = {r["session_id"] for r in by.get("agent", {}).values()}
    recs = [json.loads(line) for line in Path(args.decisions).open(encoding="utf-8")]
    recs = [r for r in recs if r.get("session_id") in sessions]
    n = len(recs)
    levels = Counter(r.get("level") for r in recs)
    lat = [x for r in recs for x in (r.get("latencies") or {}).get("llm_ms") or []]
    errors = Counter((r.get("error") or "").split(":")[0] for r in recs if r.get("error"))
    invalid = sum(v for k, v in errors.items() if k in ("llm-invalid-json", "invalid-answer"))
    failed = sum(v for k, v in errors.items() if k.startswith(("llm-", "invalid-", "machine-not", "what-if-not", "deadline")))
    differs = sum(1 for r in recs if r.get("machine") and r["machine"] != b1_choice(r))
    rejected = Counter(str(r.get("rejected")) for r in recs if r.get("rejected"))
    md += ["", f"Decisiones del agente: {n} en {len(sessions)} corridas.", "",
           "| Nivel | % |", "|---|---|", *[f"| {lv} | {100 * levels.get(lv, 0) / max(n, 1):.1f} |" for lv in LEVELS], "",
           f"- Llamadas al LLM: {len(lat)}; fallidas {failed} ({100 * failed / max(len(lat), 1):.1f} %); "
           f"JSON inválido {invalid} ({100 * invalid / max(len(lat), 1):.1f} %).",
           f"- Latencia del LLM: p50 {statistics.median(lat) if lat else float('nan'):.0f} ms, "
           f"p95 {nearest_rank(lat, 0.95) if lat else float('nan'):.0f} ms.",
           f"- What-if pedidos: {sum(bool(r.get('what_if_requested')) for r in recs)} "
           f"(ofrecidos {sum(bool(r.get('what_if_offered')) for r in recs)}).",
           f"- Rechazos 409/422: {sum(rejected.values())} {dict(rejected) or ''}.",
           f"- Eligió distinto de B1: {differs} de {n} ({100 * differs / max(n, 1):.1f} %)."]
    rows += [("decisions", str(n)), *[(f"pct_{lv}", f"{100 * levels.get(lv, 0) / max(n, 1):.1f}") for lv in LEVELS],
             ("llm_calls", str(len(lat))), ("llm_failed", str(failed)), ("llm_invalid_json", str(invalid)),
             ("llm_p50_ms", f"{statistics.median(lat):.0f}" if lat else ""),
             ("llm_p95_ms", f"{nearest_rank(lat, 0.95):.0f}" if lat else ""),
             ("rejected", str(sum(rejected.values()))), ("differs_from_b1", str(differs))]

    out = Path(args.out)
    out.with_suffix(".md").write_text("\n".join(md) + "\n", encoding="utf-8")
    with out.with_suffix(".csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["key", "value"])
        w.writerows(rows)
    print("\n".join(md))
    return 0


if __name__ == "__main__":
    sys.exit(main())
