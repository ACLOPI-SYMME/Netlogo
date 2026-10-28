"""Long-run regression (rule 3, 100,000 ticks, seeds 42 and 7) against tests/fixtures/long.

Exercises what 10,000-tick runs barely touch: ~80 finished products stacked at (2,2).
Excluded from the normal run; execute with:  python -m pytest -m slow
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterator

import pytest

from aclopi.sim import SimulationSession
from make_long_fixtures import FIXTURES, SEEDS, long_run

pytestmark = pytest.mark.slow


@pytest.fixture(scope="module")
def session(tmp_path_factory: pytest.TempPathFactory) -> Iterator[SimulationSession]:
    with SimulationSession("long", results_root=tmp_path_factory.mktemp("long_sessions")) as s:
        yield s


@pytest.mark.parametrize("seed", SEEDS)
def test_long_run_matches_fixture(session: SimulationSession, seed: int) -> None:
    expected = json.loads((Path(FIXTURES) / f"rule3_seed{seed}.json").read_text(encoding="utf-8"))
    result = long_run(session, seed)
    # KPIs added after the fixtures were made (created, work_completed) are not compared.
    assert {k: result["kpis"][k] for k in expected["kpis"]} == expected["kpis"]
    assert result["events_sha256"] == expected["events_sha256"]
    assert result["data_sha256"] == expected["data_sha256"]
