"""A0 phase 0: travel times between machines vs `distances`, and the same machine twice in a row.

Rule 3, Stochastic, fixed product sequence (SimulationSession default). The run advances in blocks
of --block ticks and reads the event buffer once per block (no tick-by-tick reads).

ProductEntersMachine is recorded when the machine STARTS processing the product (EventMachineEntry
is called from the entry gate, check-movement-W7/W10/..., in the same block that sets
Machine.Processing and Next.Completion), not when the product reaches the machine's queue.
ProductExitsMachine is recorded when the operation completes (Cheking.Machine.Completion), while
the product is still on the machine's station.

1. Travel A -> B (A != B) = entry tick at B - exit tick at A. It includes the wait at A's station
   for the exit gate. Because the entry marks the start of processing, only trips where B was free
   are kept: B's previous operation had completed at least --free-gap ticks before the entry.
   Per pair: trips, kept trips, min, median and distances[A][B] / 0.3 (ticks).
2. Same machine twice (next entry of the product is at the machine it just left): ticks between
   exit and re-entry, and the products already heading to that machine (their previous exit, with
   that machine as next entry, happened before the re-exit) that entered it later.

Usage (from the repository root):
    python scripts/a0/measure_phase0.py --ticks 30000 --seed 42
Output: data/a0/travel_times.csv
"""

from __future__ import annotations

import argparse
import csv
import json
import statistics
import sys
import time
from collections import defaultdict
from pathlib import Path

from aclopi.sim import SimulationSession

REPO_ROOT = Path(__file__).resolve().parents[2]
OUTPUT = REPO_ROOT / "data" / "a0" / "travel_times.csv"
SPEED = 0.3  # distance per tick on straight conveyors (jump 0.300 * speed-factor)


def collect(ticks: int, seed: int, block: int) -> tuple[list[dict], list[list[float]]]:
    events: list[dict] = []
    with SimulationSession("a0_phase0") as s:
        s.setup(seed=seed, rule=3, horizon_ticks=ticks)
        distances = json.loads(str(s.link.report("json-any distances")))  # fixed global, no random numbers
        start = time.perf_counter()
        while True:
            result = s.step(block)
            events += [e for e in s.events() if e["event"] in ("ProductEntersMachine", "ProductExitsMachine")]
            elapsed = time.perf_counter() - start
            done = result.ticks / ticks
            print(f"  {100 * done:5.1f}%  tick {result.ticks}  {elapsed:5.1f} s  "
                  f"~{elapsed / max(done, 1e-9) - elapsed:5.1f} s left", flush=True)
            if result.finished:
                return events, distances


def analyze(events: list[dict], distances: list[list[float]], free_gap: int) -> tuple[list[dict], dict]:
    by_product: dict[int, list[dict]] = defaultdict(list)
    machine_log: dict[str, list[tuple[int, str, int]]] = defaultdict(list)  # machine -> (tick, kind, who)
    for e in events:  # buffer order = execution order
        by_product[e["who"]].append(e)
        machine_log[e["location"]].append((e["tick"], e["event"], e["who"]))

    legs = []  # exit at A followed by the product's next entry at B
    for who, evs in by_product.items():
        for a, b in zip(evs, evs[1:]):
            if a["event"] == "ProductExitsMachine" and b["event"] == "ProductEntersMachine":
                legs.append({"who": who, "A": a["location"], "B": b["location"], "exit": a["tick"], "entry": b["tick"]})

    def b_was_free(leg: dict) -> bool:
        before = [t for t, kind, w in machine_log[leg["B"]] if kind == "ProductExitsMachine" and t <= leg["entry"] and w != leg["who"]]
        return not before or leg["entry"] - before[-1] >= free_gap

    idx = lambda m: int(m[1:]) - 1  # noqa: E731
    pairs: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for leg in legs:
        if leg["A"] != leg["B"]:
            pairs[(leg["A"], leg["B"])].append(leg)
    rows = []
    for (a, b), ls in pairs.items():
        free = [l["entry"] - l["exit"] for l in ls if b_was_free(l)]
        rows.append({
            "from": a, "to": b, "trips": len(ls), "trips_b_free": len(free),
            "min_ticks": min(free) if free else "", "median_ticks": statistics.median(free) if free else "",
            "distance": distances[idx(a)][idx(b)], "formula_ticks": round(distances[idx(a)][idx(b)] / SPEED, 1),
        })
    rows.sort(key=lambda r: -r["trips"])

    same = [l for l in legs if l["A"] == l["B"]]
    overtaken = []
    for l in same:
        # Products whose current leg goes to the same machine, started before this exit and ended after this re-entry.
        ahead = [o for o in legs if o["B"] == l["A"] and o["who"] != l["who"] and o["exit"] < l["exit"] and o["entry"] > l["entry"]]
        overtaken.append(len(ahead))
    gaps = [l["entry"] - l["exit"] for l in same]
    summary = {
        "legs": len(legs), "same_machine": len(same),
        "same_by_machine": dict(sorted(defaultdict(int, {m: sum(1 for l in same if l["A"] == m) for m in {l["A"] for l in same}}).items())),
        "gap_counts": dict(sorted({g: gaps.count(g) for g in set(gaps)}.items())),
        "cases_with_products_left_behind": sum(1 for n in overtaken if n), "products_left_behind": sum(overtaken),
    }
    return rows, summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--ticks", type=int, default=30000)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--block", type=int, default=2000)
    parser.add_argument("--free-gap", type=int, default=2, help="ticks B must have been free before the entry")
    parser.add_argument("--no-csv", action="store_true")
    args = parser.parse_args()

    t0 = time.perf_counter()
    events, distances = collect(args.ticks, args.seed, args.block)
    rows, summary = analyze(events, distances, args.free_gap)
    print(f"wall {time.perf_counter() - t0:.1f} s, events {len(events)}")
    if not args.no_csv:
        OUTPUT.parent.mkdir(parents=True, exist_ok=True)
        with OUTPUT.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        print(f"saved {OUTPUT.relative_to(REPO_ROOT)}")
    print("from to trips b_free min median formula")
    for r in rows[:10]:
        print(f"{r['from']} {r['to']} {r['trips']:5d} {r['trips_b_free']:5d} {r['min_ticks']!s:>5} {r['median_ticks']!s:>6} {r['formula_ticks']:7}")
    print(json.dumps(summary))
    return 0


if __name__ == "__main__":
    sys.exit(main())
