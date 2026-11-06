"""aclopi.sim.scenarios.apply_events on the real model (in-process WorkerState, 10 products, fast mode):
repeatability, S1 processing times, S2 only on operations that start afterwards, S3 repairs (exactly
+value u.t., skipped on an idle machine) and candidates with the times in force."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

import pytest

from aclopi.sim import scenarios
from aclopi.sim.scenarios import ScenarioEvent
from aclopi.workers.worker import WorkerConfig, WorkerState

SEED = 7
N_PRODUCTS = 10
HORIZON = 200_000
TICK = 0.31


@pytest.fixture(scope="module")
def worker(tmp_path_factory: pytest.TempPathFactory) -> Any:
    state = WorkerState(WorkerConfig(slot=0, role="session", generation=0,
                                     work_dir=str(tmp_path_factory.mktemp("scenarios_model")), warm=False))
    yield state
    state.session.close()


@pytest.fixture(scope="module")
def products(worker: WorkerState) -> list[list[Any]]:
    return worker.op_product_sequence(SEED, N_PRODUCTS)


def _drive(w: WorkerState) -> list[tuple[str, Any]]:
    pushes: list[tuple[str, Any]] = []
    for _ in range(10_000):
        if not w.runner.running or w.runner.state == "waiting_decision":
            return pushes
        pushes += w.runner.run_block()
    raise AssertionError("the run did not end")


def _run(w: WorkerState, products: list[list[Any]], scenario: dict[str, Any] | None) -> dict[str, Any]:
    setup = w.op_setup(seed=SEED, rule=3, horizon_ticks=HORIZON, product_list=products, scenario=scenario)
    w.op_run("fast")
    pushes = _drive(w)
    kpis = w.op_kpis()
    assert w.runner.state == "finished" and kpis["all_done"]
    data = [d for _, d in pushes if isinstance(d, dict)]
    return {"kpis": kpis, "events": [e for d in data for e in d.get("events") or []],
            "applied": setup["scenario_events"] + [e for d in data for e in d.get("scenario_events") or []]}


def _operations(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One row per operation done: machine, entry/exit tick and time, duration (u.t.)."""
    open_: dict[tuple[int, str], dict[str, Any]] = {}
    done: list[dict[str, Any]] = []
    for ev in events:
        key = (int(ev["who"]), str(ev["location"]))
        if ev["event"] == "ProductEntersMachine":
            open_[key] = {"machine": key[1], "who": key[0], "entry_tick": int(ev["tick"]), "entry": float(ev["time"])}
        elif ev["event"] == "ProductExitsMachine" and key in open_:
            op = open_.pop(key)
            op.update(exit_tick=int(ev["tick"]), exit=float(ev["time"]), duration=float(ev["time"]) - op["entry"])
            done.append(op)
    return done


S1 = {"id": "S1", "params": {}}  # default times: M2 160 ... M7 260
S1_TIMES = scenarios.validate_params("S1", None)["times"]
S3 = {"id": "S3", "params": {"interval_ticks": 500}}


@pytest.fixture(scope="module")
def runs(worker: WorkerState, products: list[list[Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {"S0": _run(worker, products, None)}
    # S2 starts while M7 is processing its first job (the run is the same as S0 until then)
    first_m7 = next(op for op in _operations(out["S0"]["events"]) if op["machine"] == "M7")
    out["S2_tick"] = first_m7["entry_tick"] + 100
    out["S2_job"] = first_m7
    out["S2"] = {"id": "S2", "params": {"machine": "M7", "factor": 1.75, "start_tick": out["S2_tick"]}}
    for name, sc in (("S1", S1), ("S2", out["S2"]), ("S3", S3)):
        out[name + "_run"] = _run(worker, products, sc)
    return out


@pytest.mark.parametrize("name", ["S1", "S2", "S3"])
def test_same_scenario_and_seed_same_run(worker: WorkerState, products: list[list[Any]], runs: dict[str, Any],
                                         name: str) -> None:
    sc = S1 if name == "S1" else runs["S2"] if name == "S2" else S3
    again = _run(worker, products, sc)
    first = runs[name + "_run"]
    assert again["kpis"] == first["kpis"]
    assert again["events"] == first["events"]
    assert again["applied"] == first["applied"]
    assert again["kpis"] != runs["S0"]["kpis"]  # the scenario changed the run


def test_s1_real_times_are_the_configured_ones_plus_the_stochastic_extra(runs: dict[str, Any]) -> None:
    applied = runs["S1_run"]["applied"]
    assert [(e["machine"], e["applied"]) for e in applied] == [(m, True) for m in S1_TIMES]
    for e in applied:
        assert set(e["before"].values()) == {200.0} and set(e["after"].values()) == {S1_TIMES[e["machine"]]}
    extras: dict[str, list[float]] = defaultdict(list)
    for op in _operations(runs["S1_run"]["events"]):
        if op["machine"] != "M1":
            extras[op["machine"]].append(op["duration"] - S1_TIMES[op["machine"]])
    assert len(extras) >= 4
    every = [x for xs in extras.values() for x in xs]
    # duration = time + exponential extra (mean 10), detected on the next tick (<= 0.31 later)
    assert min(every) >= -1e-6, extras
    assert 3 < sum(every) / len(every) < 25, extras


def test_s2_only_the_operations_that_start_afterwards(runs: dict[str, Any]) -> None:
    tick, job = runs["S2_tick"], runs["S2_job"]
    [ev] = runs["S2_run"]["applied"]
    assert (ev["tick"], ev["kind"], ev["applied"]) == (tick, "scale_times", True)
    assert set(ev["before"].values()) == {200.0} and set(ev["after"].values()) == {350.0}
    m7 = [op for op in _operations(runs["S2_run"]["events"]) if op["machine"] == "M7"]
    in_process = [op for op in m7 if op["entry_tick"] < tick < op["exit_tick"]]
    assert len(in_process) == 1
    assert (in_process[0]["entry"], in_process[0]["exit"]) == (job["entry"], job["exit"])  # unchanged
    after = [op for op in m7 if op["entry_tick"] >= tick]
    assert after, "M7 got no job after the degradation"
    assert min(op["duration"] for op in after) >= 350 - 1e-6
    assert all(op["duration"] < 350 for op in m7 if op["exit_tick"] <= tick)


def test_s3_repairs_add_exactly_the_value(runs: dict[str, Any]) -> None:
    applied = runs["S3_run"]["applied"]
    done = [e for e in applied if e["applied"]]
    assert done and all(e["kind"] == "repair" for e in applied)
    assert all(abs(e["after"] - e["before"] - 300.0) < 1e-9 for e in done)
    assert all(e["before"] is None and e["skip_reason"] == "machine-idle" for e in applied if not e["applied"])
    exits = [ev for ev in runs["S3_run"]["events"] if ev["event"] == "ProductExitsMachine"]
    for e in done:  # the job ends at the new Next.Completion (detected on that tick)
        end = next(ev for ev in exits if ev["location"] == e["machine"] and int(ev["tick"]) >= e["tick"])
        # repairs of the same job add up: the last one before the exit gives the end
        last = [r for r in done if r["machine"] == e["machine"] and e["tick"] <= r["tick"] <= int(end["tick"])][-1]
        assert 0 <= float(end["time"]) - last["after"] < TICK + 1e-6, (e, last, end)


def test_s3_busy_machine_plus_300_idle_machine_skipped(worker: WorkerState, products: list[list[Any]]) -> None:
    worker.op_setup(seed=SEED, rule=3, horizon_ticks=HORIZON, product_list=products)
    for _ in range(40):
        worker.op_step(100)
        machines = {m["name"]: m for m in worker.op_state()["machines"] if m["name"] != "M1"}
        busy = [n for n, m in machines.items() if m["remaining"] is not None]
        idle = [n for n, m in machines.items() if m["remaining"] is None]
        if busy and idle:
            break
    else:
        pytest.fail("no tick with a busy and an idle machine")
    tick = worker.session.ticks
    before = machines[busy[0]]["next_completion"]
    out = scenarios.apply_events(worker.session, [ScenarioEvent(tick, "repair", busy[0], 300.0, "a"),
                                                  ScenarioEvent(tick, "repair", idle[0], 300.0, "b")])
    assert [(a.applied, a.skip_reason) for a in out] == [(True, None), (False, "machine-idle")]
    after = {m["name"]: m for m in worker.op_state()["machines"]}
    assert after[busy[0]]["next_completion"] - before == pytest.approx(300.0, abs=1e-9)
    assert (out[0].before, out[0].after) == (before, after[busy[0]]["next_completion"])
    assert after[idle[0]]["next_completion"] == machines[idle[0]]["next_completion"]
    assert after[idle[0]]["remaining"] is None


def test_candidates_use_the_times_in_force(worker: WorkerState, products: list[list[Any]]) -> None:
    worker.op_setup(seed=SEED, rule=4, horizon_ticks=HORIZON, product_list=products)
    worker.op_run("fast", decisions=True)
    pushes = _drive(worker)
    assert worker.runner.state == "waiting_decision"
    req = next(d for e, d in pushes if e == "decision_required")["requests"][0]
    product, seq = int(req["who"]), int(req["seq"])
    first = {c["machine"]: c for c in worker.op_candidates(product, seq)["candidates"]}
    machine = next(m for m in first if m != "M1")
    [ev] = scenarios.apply_events(worker.session, [ScenarioEvent(worker.session.ticks, "scale_times", machine, 2.0, "x")])
    time = ev.before[str(req["operation"])]
    second = {c["machine"]: c for c in worker.op_candidates(product, seq)["candidates"]}
    assert second[machine]["finish"] >= first[machine]["finish"] + time - 1e-6
    for m in first:
        if m != machine:
            assert second[m]["finish"] == pytest.approx(first[m]["finish"])
    worker.op_stop()
