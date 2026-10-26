"""A1 measurement: wall time of a long run with rule 3 vs rule 4 + a random decider.

After a short warm-up run (JVM JIT), alternates --rounds runs of rule 3 and of rule 4 answered by
the random decider of scripts/rule4_checks.py, same seed and horizon, in one session. Alternating
spreads machine noise over both cases. Note that the two runs are different simulations (other
routes), so the difference is not only the cost of the decision hook.

Usage (from the repository root):
    python scripts/a1/timing.py --horizon 100000 --seed 42 --rounds 3
"""

from __future__ import annotations

import argparse
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # scripts/, for rule4_checks

from rule4_checks import random_decider, run  # noqa: E402

from aclopi.sim import SimulationSession  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--horizon", type=int, default=100000)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--rounds", type=int, default=3)
    args = parser.parse_args()

    walls: dict[str, list[float]] = {"rule 3": [], "rule 4 + random decider": []}
    with SimulationSession("timing") as s:
        run(s, 3, args.seed, 10000)  # warm-up
        for i in range(args.rounds):
            a = run(s, 3, args.seed, args.horizon)
            b = run(s, 4, args.seed, args.horizon, decider=random_decider(args.seed))
            walls["rule 3"].append(a.wall_s)
            walls["rule 4 + random decider"].append(b.wall_s)
            print(f"round {i}: rule 3 {a.wall_s:.1f} s | rule 4 + random decider {b.wall_s:.1f} s "
                  f"({b.requests} requests, finished {b.kpis['finished']})", flush=True)
    for name, values in walls.items():
        print(f"{name}: median {statistics.median(values):.1f} s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
