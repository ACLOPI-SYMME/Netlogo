"""Wall time of a full 10,000-tick run with and without reading platform-state.

For each rule, after one warm-up run, two runs are timed with the same Python-driven loop
(blocks of --every ticks); the second one also reads and parses platform-state after each block.
Both runs must end in the same state, which is checked as well.

Usage (from the repository root, with the venv active):
    python scripts/benchmark_platform_state.py
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[1]
MODEL_PATH = REPO_ROOT / "model" / "Paper.nlogo"
RESULTS_DIR = REPO_ROOT / "results"
RULES = {
    1: "Rule 1 - Random Machine",
    2: "Rule 2 - Nearest Machine",
    3: "Rule 3 - Potential Fields",
}
MAX_BLOCKS = 2000  # safety cap: 10,001 go calls / 10 ticks per block is ~1,001 blocks

logger = logging.getLogger("benchmark_platform_state")


def setup(netlogo: Any, rule: int, seed: int, modeling_type: str) -> None:
    netlogo.command(f"random-seed {seed}")
    netlogo.command(f'set Reactivity.rule "{RULES[rule]}"')
    netlogo.command(f'set Modeling.Type "{modeling_type}"')
    netlogo.command("setup")


def timed_run(netlogo: Any, args: argparse.Namespace, rule: int, read_every: int | None) -> tuple[float, int, str]:
    """Run until ExportData. Return (seconds, number of platform-state reads, final state)."""
    setup(netlogo, rule, args.seed, args.modeling_type)
    reads = 0
    start = time.perf_counter()
    if read_every is None:
        netlogo.command(f'repeat {10000 + 10} [ if terminado = "No" [ go ] ]')
    else:
        for _ in range(MAX_BLOCKS):
            netlogo.command(f'repeat {read_every} [ if terminado = "No" [ go ] ]')
            if args.read:
                json.loads(str(netlogo.report("platform-state")))
                reads += 1
            if str(netlogo.report("terminado")) == "Si":
                break
        else:
            raise RuntimeError("ExportData was not reached")
    seconds = time.perf_counter() - start
    if int(netlogo.report("ticks")) != 10000:
        raise RuntimeError("Run did not end at tick 10000")
    return seconds, reads, str(netlogo.report("platform-state"))


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--rules", type=int, nargs="+", default=[1, 2, 3])
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--modeling-type", choices=("Deterministic", "Stochastic"), default="Stochastic")
    parser.add_argument("--every", type=int, default=10, help="ticks between platform-state reads (default: 10)")
    args = parser.parse_args()

    load_dotenv(REPO_ROOT / ".env")
    import pynetlogo

    netlogo = pynetlogo.NetLogoLink(
        gui=False, netlogo_home=os.environ["NETLOGO_HOME"], jvm_path=os.environ["JVM_PATH"]
    )
    rows: list[dict[str, Any]] = []
    try:
        netlogo.load_model(str(MODEL_PATH))
        for rule in args.rules:
            logger.info("Rule %d: warm-up run", rule)
            args.read = False
            timed_run(netlogo, args, rule, read_every=None)
            single, _, state_single = timed_run(netlogo, args, rule, read_every=None)
            no_read, _, state_no_read = timed_run(netlogo, args, rule, read_every=args.every)
            args.read = True
            with_read, reads, state_read = timed_run(netlogo, args, rule, read_every=args.every)
            same = state_single == state_no_read == state_read
            rows.append(
                {
                    "rule": rule,
                    "single_command_s": round(single, 2),
                    "blocks_without_read_s": round(no_read, 2),
                    "blocks_with_read_s": round(with_read, 2),
                    "reads": reads,
                    "ms_per_read": round(1000 * (with_read - no_read) / reads, 2),
                    "same_final_state": same,
                }
            )
    finally:
        netlogo.kill_workspace()

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out = RESULTS_DIR / "benchmark_platform_state.json"
    out.write_text(json.dumps({"every": args.every, "seed": args.seed, "modeling_type": args.modeling_type, "rows": rows}, indent=2), encoding="utf-8")

    headers = list(rows[0])
    widths = [max(len(h), *(len(str(r[h])) for r in rows)) for h in headers]
    print()
    print(f"10,000 ticks, seed {args.seed}, {args.modeling_type}, platform-state every {args.every} ticks")
    print("  ".join(h.rjust(w) for h, w in zip(headers, widths)))
    for r in rows:
        print("  ".join(str(r[h]).rjust(w) for h, w in zip(headers, widths)))
    print(f"Saved: {out.relative_to(REPO_ROOT)}")
    return 0 if all(r["same_final_state"] for r in rows) else 1


if __name__ == "__main__":
    sys.exit(main())
