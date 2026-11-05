"""Report of the decisions of one run, from the agent's decision log (Markdown + CSV).

Input: the agent service's decision log, JSON lines appended to ACLOPI_AGENT_LOG (default
results/agent/decisions.jsonl; in docker compose /app/results/agent/decisions.jsonl = ./results/agent/).
One line per decision of every session; --session selects one (default: the session with most lines).
With --runs (the folder of scripts/a4/run_experiments.py --events), the real end of each operation is
taken from the run's events (as scripts/a4/estimation_error.py does).

Output (--out PREFIX):
    PREFIX.md               summary and one row per decision
    PREFIX_summary.csv      metric,value
    PREFIX_decisions.csv    one row per decision
Summary: decisions and number / % per level, what-if requested / done / skipped (with reason), mean and
p95 latency (total_ms) per level, and how often the machine chosen differs from B1's (best by finish).

Usage:
    python scripts/a4/decision_report.py --decisions results/agent/decisions.jsonl --runs results/a4 --out results/a4/report
"""

from __future__ import annotations

import argparse
import csv
import json
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from estimation_error import load_exits  # noqa: E402

LEVELS = ("code-obvious", "llm", "llm-what-if", "code-fallback", "heuristic")
DONE = ("ok", "timeout")  # what-if answered with results (timeout: what was ready)
COLUMNS = ["tick", "product", "seq", "operation", "current_machine", "candidates", "gap_finish", "gap_finish_plus_next",
           "triage", "level", "machine", "b1_machine", "differs_from_b1", "reason", "total_ms", "llm_ms", "what_if_ms",
           "what_if", "estimated_finish", "real_end", "error"]


def percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    s = sorted(values)
    return s[min(len(s) - 1, int(round(q * (len(s) - 1))))]


def b1_choice(candidates: list[dict[str, Any]]) -> str | None:
    """Best by finish, ties by machine number (aclopi.agent.triage.ranked)."""
    valid = [c for c in candidates if c.get("finish") is not None]
    if not valid:
        return None
    return min(valid, key=lambda c: (float(c["finish"]), int(str(c["machine"])[1:])))["machine"]


def fmt(v: Any, digits: int = 1) -> str:
    if v is None or v == "":
        return ""
    if isinstance(v, float):
        return f"{v:.{digits}f}"
    return str(v)


def decision_row(d: dict[str, Any], exits: dict[int, list[tuple[float, str]]] | None) -> dict[str, Any]:
    cands = d.get("candidates") or []
    b1 = b1_choice(cands)
    lat = d.get("latencies") or {}
    real = None
    if exits is not None and d.get("machine") is not None:
        product_exits = exits.get(int(d["product"]), [])
        if len(product_exits) > int(d["seq"]) and product_exits[int(d["seq"])][1] == d["machine"]:
            real = product_exits[int(d["seq"])][0]
    w = d.get("what_if") or {}
    return {
        "tick": d.get("tick"), "product": d.get("product"), "seq": d.get("seq"), "operation": d.get("operation"),
        "current_machine": d.get("current_machine"),
        "candidates": "; ".join(f"{c['machine']} f={fmt(c.get('finish'))} fpn={fmt(c.get('finish_plus_next'))}" for c in cands),
        "gap_finish": d.get("gap_finish"), "gap_finish_plus_next": d.get("gap_finish_plus_next"), "triage": d.get("triage"),
        "level": d.get("level"), "machine": d.get("machine"), "b1_machine": b1,
        "differs_from_b1": None if b1 is None or d.get("machine") is None else d["machine"] != b1,
        "reason": (d.get("reason") or "").replace("\n", " ").replace("|", "/"),
        "total_ms": d.get("total_ms", lat.get("total_ms")), "llm_ms": " ".join(fmt(x) for x in lat.get("llm_ms") or []),
        "what_if_ms": lat.get("what_if_ms"),
        "what_if": f"{w.get('status')} {w.get('skipped_reason') or ''}".strip() if d.get("what_if_requested") else "",
        "estimated_finish": d.get("estimated_finish"), "real_end": real, "error": d.get("error"),
    }


def summary(records: list[dict[str, Any]], rows: list[dict[str, Any]]) -> list[tuple[str, Any]]:
    n = len(records)
    out: list[tuple[str, Any]] = [("decisions", n)]
    levels = Counter(r.get("level") for r in records)
    for lv in LEVELS:
        out += [(f"n_{lv}", levels.get(lv, 0)), (f"pct_{lv}", round(100 * levels.get(lv, 0) / n, 1) if n else 0.0)]
    no_level = n - sum(levels.get(lv, 0) for lv in LEVELS)
    out.append(("n_no_decision", no_level))
    requested = [r for r in records if r.get("what_if_requested")]
    done = [r for r in requested if (r.get("what_if") or {}).get("status") in DONE]
    out += [("what_if_requested", len(requested)), ("what_if_done", len(done)),
            ("what_if_skipped", len(requested) - len(done))]
    for reason, k in sorted(Counter(r.get("what_if_reason") for r in requested if r not in done).items(), key=str):
        out.append((f"what_if_skipped_{reason}", k))
    by_level: dict[str, list[float]] = defaultdict(list)
    for r in rows:
        if r["level"] and r["total_ms"] is not None:
            by_level[r["level"]].append(float(r["total_ms"]))
    for lv in LEVELS:
        if by_level[lv]:
            out += [(f"latency_mean_ms_{lv}", round(statistics.mean(by_level[lv]), 1)),
                    (f"latency_p95_ms_{lv}", round(percentile(by_level[lv], 0.95), 1))]
    compared = [r for r in rows if r["differs_from_b1"] is not None]
    differs = sum(1 for r in compared if r["differs_from_b1"])
    out += [("compared_with_b1", len(compared)), ("differs_from_b1", differs),
            ("pct_differs_from_b1", round(100 * differs / len(compared), 1) if compared else 0.0)]
    ends = [r for r in rows if r["real_end"] is not None and r["estimated_finish"] is not None]
    out.append(("decisions_with_real_end", len(ends)))
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--decisions", required=True, help="decision log (JSON lines)")
    parser.add_argument("--session", help="session_id (default: the one with most decisions)")
    parser.add_argument("--runs", help="run_experiments.py folder with <run>.csv and <run>.events.jsonl")
    parser.add_argument("--out", required=True, help="output prefix")
    args = parser.parse_args()

    records = [json.loads(line) for line in Path(args.decisions).open(encoding="utf-8") if line.strip()]
    sessions = Counter(r.get("session_id") for r in records)
    if not sessions:
        print("no decisions in the log")
        return 1
    sid = args.session or sessions.most_common(1)[0][0]
    records = sorted((r for r in records if r.get("session_id") == sid), key=lambda r: (r.get("tick") or 0, r.get("product")))
    exits = load_exits(Path(args.runs)).get(sid) if args.runs else None
    rows = [decision_row(r, exits) for r in records]
    summ = summary(records, rows)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.with_name(out.name + "_summary.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["metric", "value"])
        w.writerows(summ)
    with out.with_name(out.name + "_decisions.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(rows)
    strategies = ", ".join(sorted({str(r.get("strategy")) for r in records}))
    lines = [f"# Decisiones de la sesión `{sid}`", "", f"Estrategia: {strategies}. Registro: `{args.decisions}`."
             + ("" if exits is not None else " Sin eventos: no hay fin real."), "", "| Métrica | Valor |", "|---|---|"]
    lines += [f"| {k} | {fmt(v)} |" for k, v in summ]
    lines += ["", "| " + " | ".join(COLUMNS) + " |", "|" + "---|" * len(COLUMNS)]
    lines += ["| " + " | ".join(fmt(r[c]) for c in COLUMNS) + " |" for r in rows]
    out.with_name(out.name + ".md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    for k, v in summ:
        print(f"{k}: {v}")
    print(f"written {out}.md, {out}_summary.csv, {out}_decisions.csv")
    return 0


if __name__ == "__main__":
    sys.exit(main())
