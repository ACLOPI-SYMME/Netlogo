"""A1 measurement: does the same seed give the same conditions to rule 3 and rule 4 + a random decider?

Runs rule 3 and then rule 4 answered by a random decider (Python's random.Random(seed), as in
scripts/rule4_checks.py) with the same seed, one tick at a time, and records for each run:
- the products created, in order: (who, type, creation tick, priority);
- the processing time drawn at each machine entry, per product: (tick, who, type, n-th entry of
  the product = operation index, machine, operation, drawn), where
  drawn = Next.Completion - entry time - base time (200; 100 on M1, which has no random part).
It prints where the two runs start to differ and saves both runs to
results/a1/measure_rng_<horizon>_s<seed>_seq-<on|off>.json (products_... with --products-only).

Reads go through platform-local / with-local-randomness reporters, so measuring does not change
the simulation. Stepping one tick at a time is slow (~2 min for 10,000 ticks per run).

--sequence on|off (default off, the original model as measured in A1) switches the fixed
product sequence (docs/product-sequence.md). --products-only skips the tick-by-tick part: it
runs each rule of --rules straight to the end (rule 4 with the random decider) and checks that
every product n created in all runs has the same type and priority, and reports how the
creation ticks differ.

Usage (from the repository root):
    python scripts/a1/measure_rng.py --horizon 10000 --seed 42
    python scripts/a1/measure_rng.py --products-only --sequence on --rules 1 3 4 --horizon 100000
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path
from typing import Any

from aclopi.sim import SimulationSession
from aclopi.sim.decisions import clear_decisions, pending_decisions, run_until_decision, set_next_machine

REPO_ROOT = Path(__file__).resolve().parents[2]
OUTPUT_DIR = REPO_ROOT / "results" / "a1"
TICK = 0.31
BASE_TIME = {"M1": 100.0}  # every other machine: 200
NC_REPORTER = "platform-local [ -> json-any map [m -> (list [Machine.Name] of m [Next.Completion] of m)] sort machines ]"
PRODUCTS_REPORTER = (
    "platform-local [ -> json-any map [p -> [(list who ProductType ProductCreationTime priority)] of p] sort products ]"
)


def created_products(session: SimulationSession) -> list[tuple[int, str, int, int]]:
    """(who, type, creation tick, priority) of every product, in creation order (who order)."""
    return [(w, t, round(c / TICK), p) for w, t, c, p in json.loads(str(session.link.report(PRODUCTS_REPORTER)))]


def run_products(session: SimulationSession, rule: int, seed: int, horizon: int, fixed: bool) -> list[tuple]:
    """Run to the end (rule 4 answered by the random decider) and return the created products."""
    session.setup(seed=seed, rule=rule, horizon_ticks=horizon, fixed_product_sequence=fixed)
    if rule == 4:
        rng = random.Random(seed)
        while True:
            result = run_until_decision(session, horizon)
            for req in pending_decisions(session):
                assert set_next_machine(session, req.who, rng.choice(req.candidates), req.seq) == "ok"
            clear_decisions(session)
            if result.finished:
                break
    else:
        session.run_to_end()
    return created_products(session)


def compare_products(runs: dict[int, list[tuple]]) -> bool:
    """Print and check that (n, type, priority) match for every n created in all runs."""
    rules = sorted(runs)
    common = min(len(p) for p in runs.values())
    print("products created: " + ", ".join(f"rule {r} {len(runs[r])}" for r in rules))
    same = all([(p[1], p[3]) for p in runs[r][:common]] == [(p[1], p[3]) for p in runs[rules[0]][:common]] for r in rules)
    print(f"(n, type, priority) identical for the {common} products n = 1..{common} created in every run: {same}")
    for r in rules[1:]:
        diff = [n for n in range(common) if runs[r][n][2] != runs[rules[0]][n][2]]
        first = f"; first at n={diff[0] + 1}: rule {rules[0]} tick {runs[rules[0]][diff[0]][2]}, rule {r} tick {runs[r][diff[0]][2]}" if diff else ""
        print(f"creation ticks, rule {r} vs rule {rules[0]}: {len(diff)} of {common} differ{first}")
    for r in rules:
        print(f"rule {r} first products (who, type, tick, priority): {runs[r][:6]}")
    return same and common > 0


def measure(session: SimulationSession, rule: int, seed: int, horizon: int, fixed: bool = False) -> dict[str, Any]:
    session.setup(seed=seed, rule=rule, horizon_ticks=horizon, fixed_product_sequence=fixed)
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
    return {"entries": entries, "products": created_products(session), "decisions": decisions}


def first_diff(a: list, b: list) -> int | None:
    for i, (x, y) in enumerate(zip(a, b)):
        if x != y:
            return i
    return None if len(a) == len(b) else min(len(a), len(b))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--horizon", type=int, default=10000)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--sequence", choices=("on", "off"), default="off", help="fixed product sequence")
    parser.add_argument("--products-only", action="store_true")
    parser.add_argument("--rules", type=int, nargs="+", default=[1, 3, 4], help="with --products-only")
    args = parser.parse_args()
    fixed = args.sequence == "on"
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    tag = f"{args.horizon}_s{args.seed}_seq-{args.sequence}"

    if args.products_only:
        with SimulationSession("measure_rng") as s:
            runs = {rule: run_products(s, rule, args.seed, args.horizon, fixed) for rule in args.rules}
        (OUTPUT_DIR / f"products_{tag}.json").write_text(json.dumps({str(r): p for r, p in runs.items()}), encoding="utf-8")
        print(f"seed {args.seed}, {args.horizon} ticks, fixed product sequence {args.sequence}")
        return 0 if compare_products(runs) or not fixed else 1

    with SimulationSession("measure_rng") as s:
        r3 = measure(s, 3, args.seed, args.horizon, fixed)
        r4 = measure(s, 4, args.seed, args.horizon, fixed)
    out = OUTPUT_DIR / f"measure_rng_{tag}.json"
    out.write_text(json.dumps({"rule3": r3, "rule4": r4}), encoding="utf-8")

    print(f"seed {args.seed}, {args.horizon} ticks, fixed product sequence {args.sequence}")
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
