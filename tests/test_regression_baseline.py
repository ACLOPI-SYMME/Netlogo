"""Full 10,000-tick runs (rules 1-3, seed 42, Stochastic) against tests/fixtures/baseline.

The L2 platform changes must not alter the simulation: identical KPIs, identical Events CSV,
and the Data CSV may only differ in column 14 (the "Wating" -> "Waiting" fix).
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import asdict
from pathlib import Path
from typing import Any

import pytest

from conftest import REPO_ROOT, report_json, setup_run
from compare_baseline import DEFAULT_BASELINE, compare_run
from validate_headless import run_once

SEED = 42
ALLOWED_DATA_COLUMNS = {14}


@pytest.mark.parametrize("rule", [1, 2, 3])
def test_full_run_matches_baseline(netlogo: Any, rule: int) -> None:
    args = argparse.Namespace(rule=rule, seed=SEED, modeling_type="Stochastic")
    # run_once seeds and calls setup itself; setup_run is not needed here.
    result = run_once(netlogo, args, run_index=1)
    events = report_json(netlogo, "platform-events")["events"]

    comparison = compare_run(rule, SEED, DEFAULT_BASELINE, asdict(result), ALLOWED_DATA_COLUMNS)
    assert comparison.kpi_differences == {}
    assert comparison.events_identical
    assert comparison.data_rows[0] == comparison.data_rows[1]
    assert set(comparison.data_column_differences) <= ALLOWED_DATA_COLUMNS

    # The event buffer holds the same events as the exported CSV, plus tick and the real operation.
    with (REPO_ROOT / result.csv_files["Events"]).open(newline="", encoding="utf-8") as handle:
        csv_rows = list(csv.reader(handle))
    assert len(events) == len(csv_rows)
    for ev, row in zip(events, csv_rows):
        tick, kind, who, ptype, location, operation, next_op, destination, time = ev
        assert float(row[0]) == time and int(row[1]) == who and row[2] == ptype and row[3] == kind
        assert row[4] == location and row[7] == next_op and row[8] == destination
        if kind == "ProductExitsMachine":
            assert row[5:7] == ["XXX", "YYY"]
        else:
            assert row[6] == operation


def test_baseline_fixtures_present() -> None:
    for rule in (1, 2, 3):
        folder = Path(DEFAULT_BASELINE) / f"rule{rule}"
        assert (folder / f"validation_{rule}_{SEED}.json").exists()
        assert len(list(folder.glob("*.csv"))) == 2
