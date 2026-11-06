"""Scenarios in the worker (in-process WorkerState, real NetLogo, the stub of aclopi.sim.scenarios):
the tick rule, block cuts in fast / live / manual step, the S3 calendar, reset, event before the
decision request and before the what-if snapshot, skipped events (docs/scenarios.md)."""

from __future__ import annotations

import itertools
import time
from pathlib import Path
from typing import Any

import pytest

import aclopi.workers.runner as runner_module
import aclopi.workers.worker as worker_module
from aclopi.sim import scenarios
from aclopi.workers.worker import WorkerConfig, WorkerState


@pytest.fixture(scope="module")
def worker(tmp_path_factory: pytest.TempPathFactory) -> Any:
    state = WorkerState(WorkerConfig(slot=0, role="session", generation=0,
                                     work_dir=str(tmp_path_factory.mktemp("scenarios")), warm=False))
    yield state
    state.session.close()


@pytest.fixture()
def spy(worker: WorkerState, monkeypatch: pytest.MonkeyPatch) -> dict[str, list[Any]]:
    """apply_events calls (model tick, event ticks), blocks (start, end) and an ordered log."""
    seen: dict[str, list[Any]] = {"apply": [], "blocks": [], "log": []}
    original_apply, original_step = scenarios.apply_events, worker.session.step
    original_until, original_pending = runner_module.run_until_decision, runner_module.pending_decisions

    def apply(session: Any, events: list[Any]) -> list[Any]:
        tick = int(session.ticks)
        seen["apply"].append((tick, [e.tick for e in events]))
        seen["log"].append(("apply", tick))
        return original_apply(session, events)

    def step(n: int) -> Any:
        start = int(worker.session.ticks)
        r = original_step(n)
        seen["blocks"].append((start, r.ticks))
        return r

    def until(session: Any, n: int) -> Any:
        start = int(session.ticks)
        r = original_until(session, n)
        seen["blocks"].append((start, r.ticks))
        return r

    def pending(session: Any) -> Any:
        seen["log"].append(("pending", int(session.ticks)))
        return original_pending(session)

    monkeypatch.setattr(scenarios, "apply_events", apply)
    monkeypatch.setattr(worker.session, "step", step)
    monkeypatch.setattr(runner_module, "run_until_decision", until)
    monkeypatch.setattr(runner_module, "pending_decisions", pending)
    return seen


def _setup(w: WorkerState, scenario: dict[str, Any] | None, seed: int = 5, rule: int = 3,
           horizon: int = 1000) -> dict[str, Any]:
    return w.op_setup(seed=seed, rule=rule, horizon_ticks=horizon, scenario=scenario)


def _drive(w: WorkerState, max_blocks: int = 5000) -> list[tuple[str, Any]]:
    """Run blocks until the run stops running (or waits for a decision)."""
    pushes: list[tuple[str, Any]] = []
    for _ in range(max_blocks):
        if not w.runner.running or w.runner.state == "waiting_decision":
            return pushes
        pushes += w.runner.run_block()
    raise AssertionError("the run did not end")


def _applied(pushes: list[tuple[str, Any]]) -> list[dict[str, Any]]:
    return [e for _, data in pushes if isinstance(data, dict) for e in data.get("scenario_events") or []]


def _no_block_crosses(blocks: list[tuple[int, int]], tick: int) -> None:
    assert not [b for b in blocks if b[0] < tick < b[1]], f"a block went past tick {tick}: {blocks}"
    assert any(b[1] == tick for b in blocks), blocks


S2 = {"id": "S2", "params": {"start_tick": 200}}


def test_s2_fast(worker: WorkerState, spy: dict[str, list[Any]]) -> None:
    assert _setup(worker, S2)["scenario_events"] == []
    worker.op_run("fast")
    pushes = _drive(worker)
    assert worker.runner.state == "finished"
    assert spy["apply"] == [(200, [200])]
    _no_block_crosses(spy["blocks"], 200)
    [ev] = _applied(pushes)
    assert (ev["type"], ev["tick"], ev["kind"], ev["machine"], ev["value"], ev["applied"]) == (
        "scenario", 200, "scale_times", "M7", 1.75, True)
    assert ev["label"] == "Degradación en M7: ×1.75"


def test_s2_live(worker: WorkerState, spy: dict[str, list[Any]]) -> None:
    _setup(worker, S2)
    clock = itertools.count(0.0, 1.0)
    worker.runner.clock = lambda: float(next(clock))  # every block is due at once
    try:
        worker.op_run("live", speed=4.0)
        pushes = _drive(worker)
    finally:
        worker.runner.clock = time.monotonic
    assert worker.runner.state == "finished"
    assert spy["apply"] == [(200, [200])]
    _no_block_crosses(spy["blocks"], 200)
    assert [(e["tick"], e["kind"]) for e in _applied(pushes)] == [(200, "scale_times")]
    assert [d["tick"] for e, d in pushes if e == "tick" and d.get("scenario_events")] == [200]


def test_s2_manual_step(worker: WorkerState, spy: dict[str, list[Any]]) -> None:
    _setup(worker, S2)
    r = worker.op_step(150)
    assert (r["ticks"], r["scenario_events"]) == (150, [])
    r = worker.op_step(500)  # 150 -> 650, cut at 200
    assert (r["ticks"], r["advanced"]) == (650, 500)
    assert [(e["tick"], e["kind"]) for e in r["scenario_events"]] == [(200, "scale_times")]
    assert spy["apply"] == [(200, [200])]
    assert spy["blocks"] == [(0, 150), (150, 200), (200, 650)]
    assert worker.op_step(100)["scenario_events"] == []


# interval_ticks 500: the smallest the S3 range allows (500-1,000,000)
S3 = {"id": "S3", "params": {"interval_ticks": 500}}
S3_HORIZON = 1600


def _fast_events(w: WorkerState, rule: int, seed: int = 11) -> list[dict[str, Any]]:
    _setup(w, S3, seed=seed, rule=rule, horizon=S3_HORIZON)
    w.op_run("fast")
    return _applied(_drive(w))


def test_s3_same_calendar(worker: WorkerState, spy: dict[str, list[Any]]) -> None:
    calendar = [(e.tick, e.machine) for e in scenarios.scenario_events("S3", S3["params"], 11, 0, S3_HORIZON)]
    assert [t for t, _ in calendar] == [500, 1000, 1500]
    first, second = _fast_events(worker, 3), _fast_events(worker, 3)
    assert first == second and [(e["tick"], e["machine"]) for e in first] == calendar
    assert [(e["tick"], e["machine"]) for e in _fast_events(worker, 1)] == calendar  # another strategy
    assert [t for t, _ in spy["apply"]] == [500, 1000, 1500] * 3
    for tick in (500, 1000, 1500):
        _no_block_crosses(spy["blocks"], tick)


def test_reset_recomputes_and_reapplies_tick_zero(worker: WorkerState, spy: dict[str, list[Any]]) -> None:
    s1 = {"id": "S1", "params": {"times": {"M3": 150, "M6": 400}}}
    first = _setup(worker, s1)["scenario_events"]
    assert [(e["tick"], e["kind"], e["machine"], e["value"]) for e in first] == [
        (0, "set_times", "M3", 150.0), (0, "set_times", "M6", 400.0)]
    events = list(worker.runner.scenario.events)
    worker.op_step(300)
    again = worker.op_reset()["scenario_events"]
    assert again == first and worker.runner.scenario.events == events
    assert spy["apply"] == [(0, [0, 0]), (0, [0, 0])]
    assert worker.op_step(300)["scenario_events"] == []


def test_event_before_decision_and_whatif_snapshot(worker: WorkerState, spy: dict[str, list[Any]],
                                                   monkeypatch: pytest.MonkeyPatch) -> None:
    # Pilot (S0): tick of the first decision stop in fast mode.
    _setup(worker, None, seed=3, rule=4, horizon=3000)
    worker.op_run("fast", decisions=True)
    pushes = _drive(worker)
    assert worker.runner.state == "waiting_decision", [e for e, _ in pushes]
    decision_tick = next(d["tick"] for e, d in pushes if e == "decision_required")
    # The same run with an S2 event exactly at that tick.
    _setup(worker, {"id": "S2", "params": {"start_tick": decision_tick}}, seed=3, rule=4, horizon=3000)
    spy["log"].clear()
    original_export = worker.session.export_world
    monkeypatch.setattr(worker.session, "export_world",
                        lambda path=None: (spy["log"].append(("export", int(worker.session.ticks))), original_export(path))[1])
    worker.op_run("fast", decisions=True)
    pushes = _drive(worker)
    assert worker.runner.state == "waiting_decision"
    block = next(d for e, d in pushes if e == "progress" and d["tick"] == decision_tick)
    assert [e["tick"] for e in block["scenario_events"]] == [decision_tick] and block["decision_requests"]
    log = spy["log"]
    assert log.index(("apply", decision_tick)) < log.index(("pending", decision_tick))
    # A what-if asked now: the snapshot is taken after the event.
    req = block["decision_requests"][0]
    snap = worker.op_whatif_snapshot(int(req["who"]), int(req["seq"]), list(req["candidates"][:2]))
    assert snap["valid"] and snap["tick"] == decision_tick, snap
    assert log.index(("apply", decision_tick)) < log.index(("export", decision_tick))
    Path(snap["path"]).unlink(missing_ok=True)
    worker.op_stop()


def test_skipped_events(worker: WorkerState, spy: dict[str, list[Any]], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ACLOPI_SCENARIO_STUB_SKIP", "1")
    events = _fast_events(worker, 3)
    assert [(e["tick"], e["applied"], e["skip_reason"]) for e in events] == [
        (500, False, "machine-idle"), (1000, False, "machine-idle"), (1500, False, "machine-idle")]


def test_whatif_entry_estimate_uses_the_times_in_force(worker: WorkerState, monkeypatch: pytest.MonkeyPatch) -> None:
    # S2 from tick 0 (factor 2): every decision that can go to M7 sees M7's degraded times.
    _setup(worker, {"id": "S2", "params": {"factor": 2.0, "start_tick": 0}}, seed=3, rule=4, horizon=4000)
    original = {op: t for op, t in worker.static.operation_times["M7"].items()}  # read after setup, before the event
    seen: list[Any] = []
    real_compute = worker_module.compute_candidates
    monkeypatch.setattr(worker_module, "compute_candidates",
                        lambda state, p, s, static: (seen.append(static), real_compute(state, p, s, static))[1])
    worker.op_run("fast", decisions=True)
    req = None
    for _ in range(200):  # answer the decisions (first candidate) until one can go to M7
        pushes = _drive(worker)
        assert worker.runner.state == "waiting_decision", worker.runner.state
        requests = [r for _, d in pushes if isinstance(d, dict) for r in d.get("decision_requests") or []]
        req = next((r for r in requests if "M7" in r["candidates"]), None)
        if req is not None:
            break
        for r in requests:
            worker.op_next_machine(int(r["who"]), int(r["seq"]), str(r["candidates"][0]))
    assert req is not None, "no decision with M7 among the candidates"
    snap = worker.op_whatif_snapshot(int(req["who"]), int(req["seq"]), ["M7"], skip_beyond_cap=True)
    assert snap["valid"] and snap["estimate_source"]["M7"] == "candidates", snap
    op = snap["operation"]
    assert seen[-1].operation_times["M7"][op] == pytest.approx(2.0 * original[op])
    cands = worker.op_candidates(int(req["who"]), int(req["seq"]))
    start = next(c["start"] for c in cands["candidates"] if c["machine"] == "M7")
    assert snap["estimated_entry"]["M7"] == pytest.approx(start)
    Path(snap.get("path") or "missing").unlink(missing_ok=True)
    worker.op_stop()
