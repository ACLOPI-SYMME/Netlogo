"""Long-run regression fixtures: rule 3, 100,000 ticks, seeds 42 and 7.

Writes tests/fixtures/long/rule3_seed<seed>.json with the KPIs and the SHA-256 of the exported
Events and Data CSVs (line endings normalized, see compare_baseline.sha256). Generated from the
model before a change, then compared by tests/test_long_regression.py (pytest -m slow).

Usage (from the repository root):
    python scripts/make_long_fixtures.py
"""

from __future__ import annotations

import argparse
import json
import logging
import subprocess
import sys
import time
from pathlib import Path

from compare_baseline import sha256 as content_sha256

from aclopi.sim import SimulationSession

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = REPO_ROOT / "tests" / "fixtures" / "long"
RULE = 3
HORIZON = 100000
SEEDS = (42, 7)


def long_run(session: SimulationSession, seed: int) -> dict:
    """Run rule 3 to HORIZON ticks and return the KPIs and the exported CSV hashes."""
    session.setup(seed=seed, rule=RULE, horizon_ticks=HORIZON)
    start = time.perf_counter()
    session.run_to_end()
    wall = time.perf_counter() - start
    events = session.directory / "Results" / "Events" / f"Event_100_Sto_R {RULE}_0.csv"
    data = session.directory / "Results" / "Data" / f"Data_100_Sto_R {RULE}_0.csv"
    return {
        "rule": RULE,
        "seed": seed,
        "horizon_ticks": HORIZON,
        "kpis": session.kpis().as_dict(),
        "events_sha256": content_sha256(events),
        "data_sha256": content_sha256(data),
        "wall_s": round(wall, 1),
    }


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--seeds", type=int, nargs="+", default=list(SEEDS))
    args = parser.parse_args()

    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, cwd=REPO_ROOT).stdout.strip()
    FIXTURES.mkdir(parents=True, exist_ok=True)
    with SimulationSession("long_fixtures") as session:
        for seed in args.seeds:
            result = long_run(session, seed)
            result["generated_from_commit"] = commit or None
            path = FIXTURES / f"rule{RULE}_seed{seed}.json"
            path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
            k = result["kpis"]
            print(f"seed {seed}: ticks={k['ticks']} finished={k['finished']} wip={k['wip']} "
                  f"mean_flow={k['mean_flow_time']} events={result['events_sha256'][:16]} "
                  f"data={result['data_sha256'][:16]} ({result['wall_s']} s) -> {path.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
