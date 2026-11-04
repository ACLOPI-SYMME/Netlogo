"""Error of the candidates estimate: estimated_finish of each decision vs the real end of that operation.

Inputs: the agent's decision log (ACLOPI_AGENT_LOG, JSON lines with session_id, product, seq, machine,
estimated_finish) and the events of each run kept by run_experiments.py --events (<run>.events.jsonl,
matched through the session_id column of <run>.csv). The real end of operation seq of a product is
the time of its (seq+1)-th ProductExitsMachine event (exits happen in operation order; seq counts
from 0), and it must be at the chosen machine.

Usage:
    python scripts/a4/estimation_error.py --decisions results/agent/decisions.jsonl --runs results/a4
"""

from __future__ import annotations

import argparse
import csv
import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path


def load_exits(runs: Path) -> dict[str, dict[int, list[tuple[float, str]]]]:
    """session_id -> product -> [(time, machine)] of its ProductExitsMachine events in order."""
    out: dict[str, dict[int, list[tuple[float, str]]]] = {}
    for run_csv in runs.glob("*.csv"):
        events = run_csv.with_suffix(".events.jsonl")
        if not events.exists():
            continue
        sid = next(csv.DictReader(run_csv.open(encoding="utf-8")))["session_id"]
        exits: dict[int, list[tuple[float, str]]] = defaultdict(list)
        for line in events.open(encoding="utf-8"):
            ev = json.loads(line)
            if ev.get("event") == "ProductExitsMachine":
                exits[int(ev["who"])].append((float(ev["time"]), str(ev["location"])))
        out[sid] = exits
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--decisions", required=True)
    parser.add_argument("--runs", required=True)
    args = parser.parse_args()

    exits = load_exits(Path(args.runs))
    errors: dict[str, list[float]] = defaultdict(list)
    missing = mismatched = 0
    for line in Path(args.decisions).open(encoding="utf-8"):
        d = json.loads(line)
        if d.get("estimated_finish") is None or d.get("machine") is None or d.get("session_id") not in exits:
            continue
        product_exits = exits[d["session_id"]].get(int(d["product"]), [])
        if len(product_exits) <= int(d["seq"]):
            missing += 1  # the operation had not ended when the run stopped
            continue
        end, machine = product_exits[int(d["seq"])]
        if machine != d["machine"]:
            mismatched += 1  # the decision was not applied (late) or rule 3 decided
            continue
        errors[d.get("strategy") or "?"].append(float(d["estimated_finish"]) - end)
        errors["all"].append(float(d["estimated_finish"]) - end)

    print(f"decisions matched: {len(errors['all'])}, operation not ended: {missing}, other machine used: {mismatched}")
    print("estimated_finish - real end (u.t.; negative = optimistic)")
    print("group   n     mean  median    p90(|e|)  mean|e|")
    for group, e in sorted(errors.items()):
        if not e:
            continue
        abs_e = sorted(abs(x) for x in e)
        p90 = abs_e[min(len(abs_e) - 1, int(round(0.9 * (len(abs_e) - 1))))]
        print(f"{group:6s} {len(e):4d} {statistics.mean(e):8.1f} {statistics.median(e):7.1f} {p90:10.1f} "
              f"{statistics.mean(abs_e):8.1f}")
    return 0 if errors["all"] else 1


if __name__ == "__main__":
    sys.exit(main())
