"""A1 measurement: does the same seed give the same conditions to rule 3 and rule 4 + a random decider?

Runs rule 3 and then rule 4 answered by a random decider (Python's random.Random(seed), as in
scripts/rule4_checks.py) with the same seed, one tick at a time, and records for each run:
- the products created, in order: (who, type, creation tick);
- the processing time drawn at each machine entry, per product: (tick, who, type, n-th entry of
  the product = operation index, machine, operation, drawn), where
  drawn = Next.Completion - entry time - base time (200; 100 on M1, which has no random part).
It prints where the two runs start to differ and saves both runs to
results/a1/measure_rng_<horizon>.json.

Reads go through platform-local / with-local-randomness reporters, so measuring does not change
the simulation. Stepping one tick at a time is slow (~2 min for 10,000 ticks per run).

Usage (from the repository root):
    python scripts/a1/measure_rng.py --horizon 10000 --seed 42
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path
from typing import Any

from aclopi.sim import SimulationSession
from aclopi.sim.decisions import clear_decisions, pending_decisions, set_next_machine

REPO_ROOT = Path(__file__).resolve().parents[2]
OUTPUT_DIR = REPO_ROOT / "results" / "a1"
TICK = 0.31
BASE_TIME = {"M1": 100.0}  # every other machine: 200
NC_REPORTER = "platform-local [ -> json-any map [m -> (list [Machine.Name] of m [Next.Completion] of m)] sort machines ]"
PRODUCTS_REPORTER = "platform-local [ -> json-any map [p -> [(list who ProductType ProductCreationTime)] of p] sort products ]"


def measure(session: SimulationSession, rule: int, seed: int, horizon: int) -> dict[str, Any]:
    session.setup(seed=seed, rule=rule, horizon_ticks=horizon)
    rng = random.Random(seed)
    entries: list[tuple] = []
    nth: dict[int, int] = {}
    decisions: list[tuple] = []  # (tick, who, seq, origin, chosen)
    while True:
        result = session.step(1)
        if rule == 4:
            for req in pending_decisions(session):
                machine = rng.choice(req.candidates)
                assert set_next_machine(session, req.who, machine, req.seq) == "ok"
                decisions.append((req.tick, req.who, req.seq, req.origin, machine))
            clear_decisions(session)
        events = [e for e in session.events() if e["event"] == "ProductEntersMachine"]
        if events:
            completion = dict(json.loads(str(session.link.report(NC_REPORTER))))
            for e in events:
                machine = e["location"]
                drawn = round(completion[machine] - e["time"] - BASE_TIME.get(machine, 200.0), 2)
                k = nth.get(e["who"], 0)
                nth[e["who"]] = k + 1
                entries.append((e["tick"], e["who"], e["product_type"], k, machine, e["operation"], drawn))
        if result.finished:
            break
    products = [(w, t, round(c / TICK)) for w, t, c in json.loads(str(session.link.report(PRODUCTS_REPORTER)))]
    return {"entries": entries, "products": products, "decisions": decisions}


def first_diff(a: list, b: list) -> int | None:
    for i, (x, y) in enumerate(zip(a, b)):
        if x != y:
            return i
    return None if len(a) == len(b) else min(len(a), len(b))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--horizon", type=int, default=10000)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    with SimulationSession("measure_rng") as s:
        r3 = measure(s, 3, args.seed, args.horizon)
        r4 = measure(s, 4, args.seed, args.horizon)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUTPUT_DIR / f"measure_rng_{args.horizon}.json"
    out.write_text(json.dumps({"rule3": r3, "rule4": r4}), encoding="utf-8")

    print(f"seed {args.seed}, {args.horizon} ticks")
    p3, p4 = r3["products"], r4["products"]
    print(f"products created: rule 3 {len(p3)}, rule 4 {len(p4)}")
    i = first_diff(p3, p4)
    print("first product difference:", "none" if i is None else
          f"index {i}: rule3 {p3[i] if i < len(p3) else None} rule4 {p4[i] if i < len(p4) else None}")
    print("rule 3 products:", p3)
    print("rule 4 products:", p4)

    e3, e4 = r3["entries"], r4["entries"]
    print(f"machine entries: rule 3 {len(e3)}, rule 4 {len(e4)}")
    i = first_diff(e3, e4)
    print("first entry difference (tick, who, type, nth, machine, op, drawn):")
    if i is not None:
        for j in range(max(0, i - 2), min(i + 4, len(e3), len(e4))):
            print(f"  #{j}: rule3 {e3[j]}  rule4 {e4[j]}")
    # The stream of exponential draws in order (M2-M7), regardless of which product got them.
    d3 = [e[6] for e in e3 if e[4] != "M1"]
    d4 = [e[6] for e in e4 if e[4] != "M1"]
    k = first_diff(d3, d4)
    print(f"exponential draws in order (M2-M7): first difference at draw #{k}")
    print("  rule3:", d3[: (k or 0) + 5])
    print("  rule4:", d4[: (k or 0) + 5])
    # Per product and operation index: the machine and the draw each product got.
    by3 = {(e[1], e[3]): e for e in e3}
    by4 = {(e[1], e[3]): e for e in e4}
    common = sorted(set(by3) & set(by4), key=lambda key: by3[key][0])
    same = [key for key in common if by3[key][4] == by4[key][4] and by3[key][6] == by4[key][6]]
    print(f"(who, n-th entry) present in both: {len(common)}; same machine and same draw: {len(same)}")
    for key in common:
        if by3[key][4:] != by4[key][4:]:
            print(f"  first per-product difference: who {key[0]} entry {key[1]}: rule3 {by3[key]} rule4 {by4[key]}")
            break
    # First agent decision different from what rule 3 did (decision for seq = the seq-th entry).
    entry_machine3 = {(e[1], e[3]): e[4] for e in e3}
    for tick, who, seq, origin, machine in r4["decisions"]:
        if entry_machine3.get((who, seq)) not in (None, machine):
            print(f"first agent choice different from rule 3: request tick {tick}, who {who}, op index {seq}, "
                  f"from {origin}: agent {machine}, rule 3 {entry_machine3[(who, seq)]}")
            break
    print(f"saved: {out.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
