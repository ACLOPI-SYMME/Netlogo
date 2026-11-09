"""Direct check of the configured LLM, without simulation: the first N agent decisions of the smoke test
log that went to the LLM (triage uncertain / very_close) are asked again with the real prompt and schema.

Configuration: .env.agent at the repo root (or --env-file); variables already set in the environment win.
The key is never printed. Per decision: valid JSON, valid machine (a finalist; or what_if when offered),
latency and the reason. Stops at the first connection / key error and prints it.

Usage:
    python scripts/a4/llm_direct_check.py --decisions results/a4/smoke_decisions.jsonl --n 5
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from aclopi.agent.llm import LLMError, client_from_env
from aclopi.agent.prompts import answer_schema, build_messages, parse_answer
from aclopi.agent.triage import classify

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG = ("ACLOPI_LLM_PROVIDER", "ACLOPI_LLM_BASE_URL", "ACLOPI_LLM_MODEL", "ACLOPI_LLM_API_KEY")


def cases(path: Path, n: int) -> list[dict[str, Any]]:
    rows = [json.loads(line) for line in path.open(encoding="utf-8")]
    return [r for r in rows if r.get("strategy") == "agent" and r.get("triage") in ("uncertain", "very_close")][:n]


def messages_for(rec: dict[str, Any]) -> tuple[list[dict[str, str]], list[str], bool]:
    """Prompt of call 1 rebuilt from the decision record (the log has no plant context: left empty)."""
    t = classify(rec["candidates"])
    cands = {"product": rec["product"], "seq": rec["seq"], "time": rec["now"], "operation": rec.get("operation"),
             "current_machine": rec.get("current_machine"), "own_remaining": 0.0,
             "gap_finish": rec.get("gap_finish"), "gap_finish_plus_next": rec.get("gap_finish_plus_next")}
    allow = bool(rec.get("what_if_offered"))
    msgs = build_messages({}, cands, t.finalists, allow, t.what_if_options)
    return msgs, t.machines, allow


async def main_async(args: argparse.Namespace) -> int:
    load_dotenv(args.env_file, override=False)
    missing = [k for k in CONFIG if not os.environ.get(k)]
    if missing:
        print(f"configuration missing ({args.env_file} exists: {Path(args.env_file).exists()}): {', '.join(missing)}")
        return 2
    llm = client_from_env()
    print(f"provider {os.environ['ACLOPI_LLM_PROVIDER']}, model {os.environ['ACLOPI_LLM_MODEL']}")
    ok_json = ok_machine = 0
    rows = cases(Path(args.decisions), args.n)
    for i, rec in enumerate(rows, 1):
        msgs, machines, allow = messages_for(rec)
        data, latency = await llm.complete_json(msgs, answer_schema(machines, allow), args.timeout)
        if isinstance(data, LLMError):
            print(f"{i}. product {rec['product']} seq {rec['seq']}: ERROR {data.kind}: {data.detail} ({latency:.2f} s)")
            if data.kind in ("provider", "timeout"):
                print("stopped: connection / key error")
                return 1
            continue
        ok_json += 1
        answer = parse_answer(data, machines, allow)
        valid = not isinstance(answer, str)
        ok_machine += valid
        what = f"{answer.action} {answer.machine or ''}".strip() if valid else answer
        reason = (answer.reason or "") if valid else ""
        print(f"{i}. product {rec['product']} seq {rec['seq']} ({rec['triage']}, finalists {machines}): {what}; "
              f"{latency:.2f} s; reason ({len(reason)} chars): {reason}")
    print(f"valid JSON {ok_json}/{len(rows)}, valid machine {ok_machine}/{len(rows)}, "
          f"JSON mode {getattr(llm, 'json_mode', '-')}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--decisions", default=str(REPO_ROOT / "results" / "a4" / "smoke_decisions.jsonl"))
    parser.add_argument("--n", type=int, default=5)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--env-file", default=str(REPO_ROOT / ".env.agent"))
    return asyncio.run(main_async(parser.parse_args()))


if __name__ == "__main__":
    sys.exit(main())
