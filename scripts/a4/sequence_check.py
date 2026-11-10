"""Order proposal with the real LLM and its makespan (docs/sequencing.md), without the UI.

1. propose(): the LLM of .env.agent (ACLOPI_LLM_*; the key is never printed) on a list of 20 products
   (8 A, 6 B, 3 I, 3 E, in that order): latency and whether the 2 orders are valid.
2. simulate_list(): makespan of the original order, the LLM's orders and the heuristic, with b1b,
   Deterministic, seed 42.
Writes results/sequencing/check_s<seed>.json. Progress at least every 30 s.

    python scripts/a4/sequence_check.py [--seed 42] [--strategy b1b] [--mode Deterministic]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[2]
LIST_20 = ["A"] * 8 + ["B"] * 6 + ["I"] * 3 + ["E"] * 3


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--strategy", default="b1b")
    parser.add_argument("--mode", default="Deterministic")
    parser.add_argument("--out", default=str(REPO_ROOT / "results" / "sequencing"))
    args = parser.parse_args()
    logging.basicConfig(level=logging.WARNING)
    load_dotenv(os.environ.get("ACLOPI_AGENT_ENV_FILE") or REPO_ROOT / ".env.agent", override=False)

    from aclopi.agent.llm import client_from_env
    from aclopi.agent.sequencing import propose
    from aclopi.sim import SimulationSession
    from aclopi.sim.sequencing import simulate_list

    products = [{"type": t, "priority": 80} for t in LIST_20]
    llm = client_from_env()
    print(f"LLM: {llm!r}", flush=True)
    proposal = asyncio.run(propose(llm, products))
    n = len(products)
    valid = [sorted(o["order"]) == list(range(n)) for o in proposal["orders"]]
    print(f"propose: {proposal['latency_ms'] / 1000:.2f} s, {len(proposal['orders'])} order(s) kept, valid {valid}, "
          f"error {proposal['error']}", flush=True)
    for k, o in enumerate(proposal["orders"], 1):
        print(f"  LLM {k}: {''.join(LIST_20[i] for i in o['order'])}  \"{o['reasoning']}\"")
    print(f"  heuristic: {''.join(LIST_20[i] for i in proposal['heuristic']['order'])}")

    cases = [("original", list(range(n)))] + [(f"LLM {k}", o["order"]) for k, o in enumerate(proposal["orders"], 1)]
    cases.append(("heuristic", proposal["heuristic"]["order"]))
    rows = []
    t0 = time.monotonic()
    last = [t0]

    def progress(ticks: int, done: int, total: int) -> bool:
        now = time.monotonic()
        if now - last[0] >= 30:
            last[0] = now
            ran = len(rows) + done / total
            eta = (now - t0) / ran * (len(cases) - ran) if ran else float("nan")
            print(f"[{now - t0:5.0f} s] {100 * ran / len(cases):.0f}% (case {len(rows) + 1}/{len(cases)}, tick {ticks}, "
                  f"{done}/{total} done), ~{eta:.0f} s left", flush=True)
        return True

    with SimulationSession() as session:
        for name, order in cases:
            out = simulate_list(session, [products[i] for i in order], args.strategy, args.mode, args.seed,
                                on_progress=progress)
            rows.append({"case": name, "order": order, "types": "".join(LIST_20[i] for i in order), **out})
            print(f"{name}: makespan {out['makespan_ticks']} ticks ({out['makespan_time']} u.t.), all_done "
                  f"{out['all_done']}, {out['wall_s']} s", flush=True)
            if len(rows) == 1:
                print(f"estimate: ~{out['wall_s'] * (len(cases) - 1):.0f} s more", flush=True)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"check_s{args.seed}.json"
    path.write_text(json.dumps({"seed": args.seed, "strategy": args.strategy, "mode": args.mode, "products": LIST_20,
                                "proposal": proposal, "valid": valid, "runs": rows}, indent=1), encoding="utf-8")
    print(f"written {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
