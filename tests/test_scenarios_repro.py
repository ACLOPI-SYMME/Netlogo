"""Reproducibility of the real scenarios (Línea A's aclopi.sim.scenarios) in the worker: fast mode,
rule 3, seed 42, 6000 ticks. Two runs give identical KPIs, model events and scenario events; S3
repairs add repair_ut to Next.Completion; after S2's start_tick the M7 operations that start take
the degraded time. (Not seed 4 with S1: rule 3 gets stuck there, docs/known-issues.md.)"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from aclopi.workers.worker import WorkerConfig, WorkerState

SEED, RULE, HORIZON = 42, 3, 6000
SCENARIOS = {
    "S1": {"id": "S1"},
    "S2": {"id": "S2", "params": {"start_tick": 1000}},
    "S3": {"id": "S3", "params": {"interval_ticks": 1000}},
}


@pytest.fixture(scope="module")
def worker(tmp_path_factory: pytest.TempPathFactory) -> Any:
    state = WorkerState(WorkerConfig(slot=0, role="session", generation=0,
                                     work_dir=str(tmp_path_factory.mktemp("repro")), warm=False))
    yield state
    state.session.close()


def _run(w: WorkerState, scenario: dict[str, Any]) -> dict[str, Any]:
    """One fast run to the horizon: KPIs, model events (event-buffer) and scenario events."""
    setup = w.op_setup(seed=SEED, rule=RULE, horizon_ticks=HORIZON, scenario=scenario)
    params = dict(w.runner.scenario.params)
    w.op_run("fast")
    pushes: list[tuple[str, Any]] = []
    for _ in range(1000):
        if not w.runner.running:
            break
        pushes += w.runner.run_block()
    assert w.runner.state == "finished", w.runner.state
    data = [d for _, d in pushes if isinstance(d, dict)]
    return {"kpis": w.op_kpis(), "params": params,
            "events": [e for d in data for e in d.get("events") or []],
            "scenario_events": setup["scenario_events"] + [e for d in data for e in d.get("scenario_events") or []]}


@pytest.fixture(scope="module")
def runs(worker: WorkerState) -> dict[str, tuple[dict[str, Any], dict[str, Any]]]:
    return {name: (_run(worker, sc), _run(worker, sc)) for name, sc in SCENARIOS.items()}


@pytest.mark.parametrize("name", list(SCENARIOS))
def test_two_runs_are_identical(runs: dict[str, Any], name: str) -> None:
    first, second = runs[name]
    assert first["kpis"] == second["kpis"]
    assert first["events"] == second["events"] and first["events"]
    assert first["scenario_events"] == second["scenario_events"] and first["scenario_events"]


def test_s3_repairs_add_repair_ut(runs: dict[str, Any]) -> None:
    run = runs["S3"][0]
    repair = run["params"]["repair_ut"]
    events = run["scenario_events"]
    assert [e["tick"] for e in events] == [1000, 2000, 3000, 4000, 5000]
    applied = [e for e in events if e["applied"]]
    assert applied, events
    for e in applied:
        assert e["kind"] == "repair" and e["after"] - e["before"] == pytest.approx(repair)
    assert all(e["skip_reason"] == "machine-idle" and e["before"] is None for e in events if not e["applied"])


def test_s2_operations_on_m7_after_start_take_the_degraded_time(runs: dict[str, Any]) -> None:
    run = runs["S2"][0]
    params = run["params"]
    [event] = run["scenario_events"]
    assert (event["tick"], event["machine"], event["applied"]) == (params["start_tick"], "M7", True)
    degraded = event["after"]
    assert degraded == {op: pytest.approx(t * params["factor"]) for op, t in event["before"].items()}
    # Processing time of each M7 operation: from ProductEntersMachine to its ProductExitsMachine.
    # Stochastic: time + random-exponential 10 (+ tick rounding), so it is at least the time in force.
    started: dict[int, dict[str, Any]] = {}
    durations: list[tuple[int, str, float]] = []
    for e in run["events"]:
        if e["location"] != "M7":
            continue
        if e["event"] == "ProductEntersMachine":
            started[e["who"]] = e
        elif e["event"] == "ProductExitsMachine" and e["who"] in started:
            s = started.pop(e["who"])
            durations.append((s["tick"], s["operation"], e["time"] - s["time"]))
    after = [(tick, op, d) for tick, op, d in durations if tick >= params["start_tick"]]
    assert after, durations
    for tick, op, d in after:
        assert degraded[op] <= d < degraded[op] + 100, (tick, op, d, degraded[op])  # not the old time + extra
