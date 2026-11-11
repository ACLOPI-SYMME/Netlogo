"""Order search in rounds with the real LLM, without the UI (docs/sequencing.md, "Flujo por rondas").

Per list (20 products, 8 A, 6 B, 3 I, 3 E): round 0 simulates the original order and the heuristic;
rounds 1..R send everything evaluated (with simulate_list's details) to propose() and simulate the 2
new orders. b1b, Deterministic, seed 42 by default. The LLM comes from .env.agent (the key is never
printed). Writes results/sequencing/rounds_<list>.json (with the prompt of every round) and prints a
table per list. Progress at least every 30 s.

    python scripts/a4/sequence_rounds.py [--rounds 3] [--lists grouped interleaved] [--reasoning none]
--reasoning (none | low | medium; default ACLOPI_SEQUENCE_REASONING) as the request's "reasoning": "none"
uses the fast timeout and max_tokens. Other than medium, the files are rounds_<list>_<reasoning>.json.
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
from typing import Any

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[2]
LISTS = {"grouped": "AAAAAAAABBBBBBIIIEEE", "interleaved": "ABIEABIEABIEABABABAA"}


class Clock:
    def __init__(self, sims: int) -> None:
        self.t0, self.last, self.sims, self.done, self.sim_s = time.monotonic(), time.monotonic(), sims, 0, 0.0
        self.what = ""

    def tick(self, what: str | None = None) -> None:
        if what:
            self.what = what
        now = time.monotonic()
        if now - self.last >= 30:
            self.last = now
            left = (self.sim_s / self.done * (self.sims - self.done)) if self.done else float("nan")
            print(f"[{now - self.t0:5.0f} s] {100 * self.done / self.sims:.0f}% of the simulations "
                  f"({self.done}/{self.sims}), now {self.what}, ~{left:.0f} s of simulation left", flush=True)


async def ask(llm: Any, products: list[dict[str, Any]], evaluated: list[dict[str, Any]], clock: Clock,
              effort: str, timeout_s: float, min_tokens: int | None) -> dict[str, Any]:
    from aclopi.agent.sequencing import propose

    task = asyncio.ensure_future(propose(llm, products, evaluated, "b1b", "Deterministic", timeout_s, effort, min_tokens))
    while not task.done():
        await asyncio.sleep(1)
        clock.tick()
    return task.result()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--rounds", type=int, default=3)
    parser.add_argument("--lists", nargs="+", default=list(LISTS), choices=list(LISTS))
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--reasoning", choices=("none", "low", "medium"))
    parser.add_argument("--out", default=str(REPO_ROOT / "results" / "sequencing"))
    args = parser.parse_args()
    logging.basicConfig(level=logging.WARNING)
    load_dotenv(os.environ.get("ACLOPI_AGENT_ENV_FILE") or REPO_ROOT / ".env.agent", override=False)

    from aclopi.agent.llm import client_from_env
    from aclopi.agent.sequencing import build_messages, largest_first
    from aclopi.agent.service import AgentSettings
    from aclopi.sim import SimulationSession
    from aclopi.sim.sequencing import simulate_list

    settings = AgentSettings.from_env()
    llm = client_from_env()
    effort = args.reasoning or settings.sequence_reasoning
    fast = effort == "none"
    timeout_s = settings.sequence_fast_timeout_s if fast else settings.sequence_timeout_s
    min_tokens = settings.sequence_fast_max_tokens if fast else None
    suffix = "" if effort == "medium" else f"_{effort}"
    print(f"LLM: {llm!r}, reasoning {effort!r}, timeout {timeout_s} s", flush=True)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    clock = Clock(len(args.lists) * (2 + 2 * args.rounds))

    with SimulationSession() as session:
        def simulate(products: list[dict[str, Any]], order: list[int], label: str) -> dict[str, Any]:
            clock.tick(label)
            t = time.monotonic()
            r = simulate_list(session, [products[i] for i in order], "b1b", "Deterministic", args.seed,
                              on_progress=lambda *a: clock.tick() or True, details=True)
            clock.done += 1
            clock.sim_s += time.monotonic() - t
            if clock.done == 1:
                print(f"first simulation {r['wall_s']} s: estimate ~{r['wall_s'] * (clock.sims - 1):.0f} s of "
                      f"simulation more", flush=True)
            return r

        for name in args.lists:
            types = LISTS[name]
            products = [{"type": t, "priority": 80} for t in types]
            n = len(products)
            rows: list[dict[str, Any]] = []
            calls: list[dict[str, Any]] = []
            for who, order, why in (("original", list(range(n)), "list order"),
                                    ("heuristic", largest_first(products), "Longest first")):
                r = simulate(products, order, f"{name} round 0 {who}")
                rows.append({"round": 0, "by": who, "order": order, "types": "".join(types[i] for i in order),
                             "reasoning": why, "makespan_ticks": r["makespan_ticks"], "details": r["details"]})
                print(f"{name} r0 {who}: {r['makespan_ticks']}", flush=True)
            for rnd in range(1, args.rounds + 1):
                evaluated = [{"order": x["order"], "makespan_ticks": x["makespan_ticks"], "details": x["details"]} for x in rows]
                clock.tick(f"{name} round {rnd} LLM")
                answer = asyncio.run(ask(llm, products, evaluated, clock, effort, timeout_s, min_tokens))
                calls.append({"round": rnd, "latency_s": round(answer["latency_ms"] / 1000, 1), "error": answer["error"],
                              "kept": len(answer["orders"]), "analysis": answer["analysis"],
                              "prompt": build_messages(products, evaluated, "b1b", "Deterministic")})
                print(f"{name} r{rnd} LLM: {answer['latency_ms'] / 1000:.1f} s, {len(answer['orders'])} order(s), "
                      f"error {answer['error']}; analysis: {answer['analysis']}", flush=True)
                for k, o in enumerate(answer["orders"], 1):
                    r = simulate(products, o["order"], f"{name} round {rnd} LLM {k}")
                    rows.append({"round": rnd, "by": f"LLM {k}", "order": o["order"],
                                 "types": "".join(types[i] for i in o["order"]), "reasoning": o["reasoning"],
                                 "makespan_ticks": r["makespan_ticks"], "details": r["details"]})
                    print(f"{name} r{rnd} LLM {k}: {r['makespan_ticks']}  {rows[-1]['types']}", flush=True)
            heuristic = rows[1]["makespan_ticks"]
            beat = [x for x in rows if x["by"].startswith("LLM") and x["makespan_ticks"] < heuristic]
            summary = {"list": name, "types": types, "seed": args.seed, "reasoning": effort, "rows": rows, "calls": calls,
                       "beats_heuristic": bool(beat), "first_round_beating": min((x["round"] for x in beat), default=None)}
            (out_dir / f"rounds_{name}{suffix}.json").write_text(json.dumps(summary, indent=1, ensure_ascii=False), encoding="utf-8")
            print(f"\n## {name} ({types})\n| round | by | order (types) | makespan | reasoning |\n|---|---|---|---|---|")
            for x in rows:
                print(f"| {x['round']} | {x['by']} | {x['types']} | {x['makespan_ticks']} | {x['reasoning']} |")
            print("latency per call: " + ", ".join(f"r{c['round']} {c['latency_s']} s" for c in calls))
            print(f"LLM beat the heuristic ({heuristic}): {summary['beats_heuristic']}, "
                  f"first round {summary['first_round_beating']}\n", flush=True)
    print(f"simulation time {clock.sim_s:.0f} s, total {time.monotonic() - clock.t0:.0f} s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
