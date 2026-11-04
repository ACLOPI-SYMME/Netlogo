"""Why did operations end later than candidates estimated? (smoke test records, no simulation)

For each decision whose real end is more than --threshold u.t. after estimated_finish, split the
lateness (real_end - estimated_finish) with the run's events:
  start part   = real entry - estimated start
    - if the product entered when the chosen machine became free (it waited for it), the wait is
      split among the jobs the machine ran between the decision and the entry:
        (a) the occupant at decision time, reprocessed in place (its next job on the same machine
            started when it finished);
        (b) a product not counted at decision time: its decision for that machine was taken after
            this one (its entry to its previous machine came later), or a new product;
        (d) the rest: jobs that were counted but took longer than estimated;
    - otherwise the machine was free when it arrived: (c) the travel took longer than distances.
  process part = (real end - real entry) - estimated processing time  -> (d) random processing time
Events: <run>.events.jsonl from run_experiments.py --events (k-th entry/exit of a product = operation k).

Usage: python scripts/a4/diagnose_finish_error.py --decisions results/a4/smoke_decisions.jsonl --runs results/a4
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

TICK = 0.31


def load_runs(runs: Path) -> dict[str, dict[str, Any]]:
    out = {}
    for run_csv in runs.glob("*.csv"):
        ev_path = run_csv.with_suffix(".events.jsonl")
        if not ev_path.exists():
            continue
        sid = next(csv.DictReader(run_csv.open(encoding="utf-8")))["session_id"]
        entries: dict[int, list[tuple[float, str]]] = defaultdict(list)
        exits: dict[int, list[tuple[float, str]]] = defaultdict(list)
        created: dict[int, float] = {}
        for line in ev_path.open(encoding="utf-8"):
            e = json.loads(line)
            who, t = int(e["who"]), float(e["time"])
            created.setdefault(who, t)
            if e["event"] == "ProductEntersMachine":
                entries[who].append((t, e["location"]))
            elif e["event"] == "ProductExitsMachine":
                exits[who].append((t, e["location"]))
        jobs: dict[str, list[dict[str, Any]]] = defaultdict(list)  # machine -> jobs
        for who, ens in entries.items():
            for k, (t_in, m) in enumerate(ens):
                t_out = exits[who][k][0] if k < len(exits[who]) else float("inf")
                jobs[m].append({"who": who, "k": k, "in": t_in, "out": t_out})
        out[sid] = {"entries": entries, "exits": exits, "jobs": jobs, "created": created}
    return out


def diagnose(d: dict[str, Any], run: dict[str, Any]) -> dict[str, Any] | None:
    who, seq, m, now = int(d["product"]), int(d["seq"]), d["machine"], float(d["now"])
    ens, exs = run["entries"].get(who, []), run["exits"].get(who, [])
    if len(exs) <= seq or ens[seq][1] != m:
        return None
    t_in, t_end = ens[seq][0], exs[seq][0]
    late = t_end - float(d["estimated_finish"])
    est_start = float(d["estimated_start"])
    proc_est = float(d["estimated_finish"]) - est_start
    parts = Counter()
    parts["d_proc"] += (t_end - t_in) - proc_est  # its own random processing time
    start_late = t_in - est_start
    others = [j for j in run["jobs"][m] if j["who"] != who and j["in"] < t_in and j["out"] > now - 1e-9]
    last_free = max((j["out"] for j in others), default=-1.0)
    travel = next((c.get("travel") for c in d.get("candidates", []) if c["machine"] == m), None)
    own_exit = exs[seq - 1][0] if seq >= 1 else now
    arrival_est = own_exit + float(travel or 0.0)
    if others and last_free > arrival_est:  # the machine was still busy when it should have arrived: it waited
        parts["c"] += t_in - last_free  # from "machine free" to entry (entry segment, gates)
        budget = last_free - est_start
        for j in sorted(others, key=lambda j: j["in"]):
            dur = min(j["out"], t_in) - max(j["in"], now)
            q_ens = run["entries"][j["who"]]
            if j["in"] > now and j["k"] > 0 and run["exits"][j["who"]][j["k"] - 1][1] == m \
                    and abs(run["exits"][j["who"]][j["k"] - 1][0] - j["in"]) <= TICK + 1e-6 \
                    and run["exits"][j["who"]][j["k"] - 1][0] > now:
                cause = "a"  # occupant (or a later job) reprocessed in place
            elif j["in"] > now and (j["k"] == 0 and run["created"][j["who"]] > now
                                    or j["k"] > 0 and q_ens[j["k"] - 1][0] >= now):
                cause = "b"  # decided (or created) after this decision: not counted
            else:
                cause = "d_jobs"
            take = max(0.0, min(dur, budget)) if cause != "d_jobs" else 0.0
            parts[cause] += take
            budget -= take
        parts["d_jobs"] += budget  # counted jobs that took longer than estimated
    else:
        parts["c"] += t_in - arrival_est
        parts["d_jobs"] += start_late - parts["c"]
    parts["d"] = parts["d_proc"] + parts["d_jobs"]
    main = max(("a", "b", "c", "d"), key=lambda k: parts[k])
    return {"late": late, "parts": dict(parts), "main": main, "machine": m, "current": ens[seq - 1][1] if seq else None}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--decisions", required=True)
    ap.add_argument("--runs", required=True)
    ap.add_argument("--threshold", type=float, default=100.0)
    args = ap.parse_args()
    runs = load_runs(Path(args.runs))
    rows = []
    for line in Path(args.decisions).open(encoding="utf-8"):
        d = json.loads(line)
        if d.get("session_id") in runs and d.get("estimated_finish") is not None:
            r = diagnose(d, runs[d["session_id"]])
            if r is not None and r["late"] > args.threshold:
                rows.append({**r, "strategy": d.get("strategy"), "product": d["product"], "seq": d["seq"]})
    print(f"decisions later than estimated by > {args.threshold:.0f} u.t.: {len(rows)}")
    names = {"a": "(a) occupant reprocessed in place", "b": "(b) arrival not counted",
             "c": "(c) travel longer than distances", "d": "(d) other (processing time, counted jobs)"}
    print("cause                                      main cause in   u.t. explained (sum over these decisions)")
    for k in "abcd":
        print(f"{names[k]:42s} {sum(1 for r in rows if r['main'] == k):6d}   {sum(r['parts'].get(k, 0) for r in rows):10.0f}")
    print(f"  of (d): own processing time {sum(r['parts'].get('d_proc', 0) for r in rows):.0f}, "
          f"counted jobs longer than estimated {sum(r['parts'].get('d_jobs', 0) for r in rows):.0f}")
    print(f"total lateness: {sum(r['late'] for r in rows):.0f} u.t.")
    for r in sorted(rows, key=lambda r: -r["late"])[:8]:
        print(f"  {r['strategy']:6s} p{r['product']} seq{r['seq']} {r['current']}->{r['machine']}: late {r['late']:.0f} "
              + " ".join(f"{k}={v:.0f}" for k, v in sorted(r["parts"].items()) if abs(v) >= 1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
