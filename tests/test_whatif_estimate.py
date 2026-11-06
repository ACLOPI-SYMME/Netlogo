"""What-if entry estimate (no NetLogo): travel = distances in u.t., and the snapshot prefers
Línea A's candidates `start`, with aclopi.sim.whatif.estimate_entry as the fallback."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest

from aclopi.sim.candidates import compute_candidates, estimate_start, travel_time
from aclopi.workers.worker import WorkerState
from test_candidates_unit import ME, OPS_E, machine, product, state, static


def test_travel_is_distances_in_time_units() -> None:
    st = static()
    assert travel_time(st, "M2", "M3") == pytest.approx(124.6)  # not 124.6 / 0.3 * 0.31
    assert travel_time(st, "M2", "M2") == 0 and travel_time(st, None, "M3") == 0
    s = state({"M2": machine("M2", ME, 1100.0)}, [product(ME, OPS_E, 1, "M2")])
    e = estimate_start(s, ME, "M3", "O1", st)
    assert e["travel"] == pytest.approx(124.6) and e["arrival"] == pytest.approx(1000 + 100 + 124.6)


def _times_session(times: dict[str, dict[str, float]]) -> Any:
    """Answers the reporter of current_operation_times with these times (the ones in force)."""
    rows = [[m, list(ops), list(ops.values())] for m, ops in times.items()]
    return SimpleNamespace(_report=lambda code: json.dumps(rows))


def test_snapshot_uses_candidates_start_with_fallback() -> None:
    st = static()
    fake = SimpleNamespace(static=st, session=_times_session(st.operation_times))
    # In its machine: the candidates of Línea A give the start of every capable machine.
    s = state({"M2": machine("M2", ME, 1100.0), "M3": machine("M3", 300, 1500.0)},
              [product(ME, OPS_E, 1, "M2"), product(300, OPS_E, 2, "M3")])
    starts = {c.machine: c.start for c in compute_candidates(s, ME, 2, st).candidates}
    entry, source = WorkerState._estimated_entries(fake, s, ME, 2, "O1", ["M3", "M5"])
    assert source == {"M3": "candidates", "M5": "candidates"}
    assert entry == {"M3": starts["M3"], "M5": starts["M5"]}
    # Not in a machine (candidates not valid): the platform's estimate.
    s2 = state({}, [product(ME, OPS_E, 2, "M3")])
    entry, source = WorkerState._estimated_entries(fake, s2, ME, 2, "O1", ["M3", "M5"])
    assert source == {"M3": "fallback", "M5": "fallback"}
    assert entry["M3"] == pytest.approx(estimate_start(s2, ME, "M3", "O1", st)["start"])


def test_fallback_counts_the_job_in_process() -> None:
    """platform-state gives next_completion (no "remaining" field): own job and the candidate's job count."""
    st = static()
    s = state({"M2": machine("M2", ME, 1100.0), "M3": machine("M3", 300, 1500.0)},
              [product(ME, OPS_E, 1, "M2"), product(300, OPS_E, 2, "M3")])
    e = estimate_start(s, ME, "M3", "O1", st)
    assert e["own_remaining"] == pytest.approx(100) and e["arrival"] == pytest.approx(1000 + 100 + 124.6)
    assert e["queue_time"] == pytest.approx(500) and e["start"] == pytest.approx(1500)
