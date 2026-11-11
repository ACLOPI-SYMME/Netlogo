"""Do ordering calls slow down machine decisions on the LLM server? One quick check, real LLM (.env.agent;
the key is never printed).

1. Baseline: 5 machine decisions (the first LLM cases of the smoke test, as llm_direct_check.py), one
   after the other.
2. The same 5 decisions while a real /sequence/propose call (20 products, evaluated: original and
   heuristic, reasoning medium) is running; each decision notes whether the ordering call was still on.
Prints the latencies and the medians. Runs about 1-2 minutes; progress every 30 s at most.

    python scripts/a4/sequence_load_check.py
"""

from __future__ import annotations

import asyncio
import os
import statistics
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
LIST_20 = ["A"] * 8 + ["B"] * 6 + ["I"] * 3 + ["E"] * 3


async def decisions(llm, rows, label: str, busy: asyncio.Task | None = None) -> list[float | None]:
    from aclopi.agent.llm import LLMError
    from aclopi.agent.prompts import answer_schema
    from llm_direct_check import messages_for

    out = []
    for i, rec in enumerate(rows, 1):
        msgs, machines, allow = messages_for(rec)
        on = busy is not None and not busy.done()
        data, latency = await llm.complete_json(msgs, answer_schema(machines, allow), 30)
        out.append(None if isinstance(data, LLMError) else latency)
        state = f"ERROR {data.kind}: {data.detail[:80]}" if isinstance(data, LLMError) else "ok"
        print(f"{label} {i}: {latency:.2f} s ({state}){', ordering call running' if on else ''}", flush=True)
    return out


async def main_async() -> int:
    load_dotenv(os.environ.get("ACLOPI_AGENT_ENV_FILE") or REPO_ROOT / ".env.agent", override=False)
    from aclopi.agent.llm import client_from_env
    from aclopi.agent.sequencing import largest_first, propose
    from llm_direct_check import cases

    llm = client_from_env()
    print(f"LLM: {llm!r}", flush=True)
    rows = cases(REPO_ROOT / "results" / "a4" / "smoke_decisions.jsonl", 5)
    base = await decisions(llm, rows, "baseline")
    if any(lat is None for lat in base):
        print("stopped: the LLM does not answer (see the errors above); nothing to compare")
        return 1
    products = [{"type": t, "priority": 80} for t in LIST_20]
    evaluated = [{"order": list(range(20)), "makespan_ticks": 27745}, {"order": largest_first(products), "makespan_ticks": 26612}]
    t0 = time.monotonic()
    seq = asyncio.ensure_future(propose(llm, products, evaluated, "b1b", "Deterministic", 90, "medium"))
    await asyncio.sleep(2)  # the ordering call is on the server
    loaded = await decisions(llm, rows, "with ordering call", seq)
    while not seq.done():
        await asyncio.sleep(1)
        if int(time.monotonic() - t0) % 30 == 0:
            print(f"[{time.monotonic() - t0:.0f} s] waiting for the ordering call", flush=True)
    answer = seq.result()
    print(f"ordering call: {answer['latency_ms'] / 1000:.1f} s, {len(answer['orders'])} order(s), error {answer['error']}")
    loaded_ok = [x for x in loaded if x is not None]
    print(f"median baseline {statistics.median(base):.2f} s (max {max(base):.2f}), "
          f"with ordering call {statistics.median(loaded_ok):.2f} s (max {max(loaded_ok):.2f}), "
          f"{len(loaded) - len(loaded_ok)} error(s)" if loaded_ok else "every decision failed during the ordering call")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main_async()))
