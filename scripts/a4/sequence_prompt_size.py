"""Size of the /sequence/propose prompt (tokens ~ characters / 4) by number of products and of evaluated
orders, with synthetic details shaped as simulate_list's (5-digit ticks, 7 machines, 2 M1 idle
intervals per product). No LLM, no NetLogo.

    python scripts/a4/sequence_prompt_size.py [--budget 30000]
"""

from __future__ import annotations

import argparse
import random
import sys
from typing import Any

from aclopi.agent.sequencing import PROMPT_BUDGET, build_messages, prompt_tokens

MIX = "AABBIEALBTPEAB"  # types cycled to make a list


def details(n: int, rng: random.Random) -> dict[str, Any]:
    return {"products": [{"index": k, "type": "A", "entry_tick": 323 + 645 * k, "start_tick": 367 + 645 * k,
                          "end_tick": 7182 + 645 * k + rng.randint(0, 9999)} for k in range(n)],
            "last": n - 1, "occupancy": {f"M{m}": round(rng.uniform(30, 75), 1) for m in range(1, 8)},
            "m1_idle": {"intervals": [[a, a + rng.randint(100, 900)] for a in range(0, 1000 * 2 * n, 1000)],
                        "total_ticks": 13692},
            "entry_windows": {"checks": 2 * n + 5, "created": n, "zone_busy": n + 5, "wip_full": 0}}


def evaluated(types: str, k: int, rng: random.Random) -> list[dict[str, Any]]:
    out = []
    for j in range(k):
        order = list(range(len(types)))
        rng.shuffle(order)
        d = details(len(types), rng)
        for p in d["products"]:
            p["type"] = types[order[p["index"]]]
        out.append({"order": order, "makespan_ticks": 25000 + 100 * j, "details": d})
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--budget", type=int, default=PROMPT_BUDGET)
    args = parser.parse_args()
    rng = random.Random(1)
    print(f"| products | evaluated | tokens (full) | tokens (budget {args.budget}) |\n|---|---|---|---|")
    for n in (10, 20, 50, 100):
        types = (MIX * 10)[:n]
        for k in (2, 4, 8):
            ev = evaluated(types, k, rng)
            full = prompt_tokens(build_messages(types, ev, budget=None))
            cut = prompt_tokens(build_messages(types, ev, budget=args.budget))
            print(f"| {n} | {k} | {full} | {cut}{' (cut)' if cut < full else ''} |")
    return 0


if __name__ == "__main__":
    sys.exit(main())
