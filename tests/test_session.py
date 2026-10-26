"""SimulationSession: API, horizon, per-session folders, several sessions per process and cloning."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterator

import pytest

from aclopi.sim import SimulationSession
from compare_baseline import sha256 as content_sha256

BASELINE = Path(__file__).resolve().parent / "fixtures" / "baseline"


@pytest.fixture(scope="module")
def sessions_root(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return tmp_path_factory.mktemp("sessions")


@pytest.fixture(scope="module")
def s1(sessions_root: Path) -> Iterator[SimulationSession]:
    with SimulationSession("s1", results_root=sessions_root) as session:
        yield session


@pytest.fixture(scope="module")
def s2(sessions_root: Path) -> Iterator[SimulationSession]:
    with SimulationSession("s2", results_root=sessions_root) as session:
        yield session


def snapshot(session: SimulationSession) -> dict[str, Any]:
    """Observable state plus the next random numbers (equal only if the RNG state is equal)."""
    link = session.link
    return {
        "state": str(link.report("platform-state")),
        "pending_events": str(link.report("platform-events")),
        "events_csv": str(link.report("(word EventFrameInfo)")),
        "data_csv": str(link.report("(word DataFrameInfo)")),
        "rng": [int(link.report("random 2147483647")) for _ in range(3)],
    }


def test_context_manager_closes(sessions_root: Path) -> None:
    with SimulationSession("ctx", results_root=sessions_root) as session:
        session.setup(seed=1, rule=1)
        assert session.step(10).ticks == 10
    assert session.closed
    with pytest.raises(RuntimeError):
        session.state()
    session.close()  # idempotent


def test_requires_setup(sessions_root: Path, s1: SimulationSession) -> None:
    with SimulationSession("nosetup", results_root=sessions_root) as session:
        with pytest.raises(RuntimeError):
            session.step(1)
    with pytest.raises(ValueError):
        s1.setup(seed=1, rule=5)


def test_step_stops_cleanly_at_horizon(s1: SimulationSession) -> None:
    s1.setup(seed=42, rule=3, horizon_ticks=500)
    first = s1.step(300)
    assert (first.ticks, first.advanced, first.finished) == (300, 300, False)
    last = s1.step(1000)
    assert (last.ticks, last.advanced, last.finished) == (500, 200, True)
    again = s1.step(10)
    assert (again.ticks, again.advanced, again.finished) == (500, 0, True)
    names = {p.name for p in s1.exported_csvs()}
    assert names == {"Data_100_Sto_R 3_0.csv", "Event_100_Sto_R 3_0.csv"}


def test_run_to_end_and_reset(s1: SimulationSession) -> None:
    s1.setup(seed=42, rule=1, horizon_ticks=400)
    result = s1.run_to_end()
    assert (result.ticks, result.advanced, result.finished) == (400, 400, True)
    kpis_first = s1.kpis()
    s1.reset()
    assert s1.ticks == 0 and not s1.finished
    s1.run_to_end()
    assert s1.kpis() == kpis_first


def test_state_events_layout(s1: SimulationSession) -> None:
    s1.setup(seed=42, rule=3)
    layout = s1.layout()
    assert len(layout["nodes"]) == 94 and len(layout["machines"]) == 7
    s1.step(2000)
    state = s1.state()
    assert state["tick"] == 2000 and len(state["machines"]) == 7
    events = s1.events()
    assert events and set(events[0]) == {
        "tick", "event", "who", "product_type", "location", "operation", "next_operation", "destination", "time",
    }
    assert s1.events() == []  # read empties the buffer
    assert s1.layout() is layout  # cached


def test_sessions_export_to_their_own_folders(s1: SimulationSession, s2: SimulationSession) -> None:
    # Same rule, so both write the same file name; different horizons give different contents.
    # PrintData logs every 100 time units (~323 ticks): 1000 ticks -> 3 rows, 300 ticks -> none.
    s1.setup(seed=42, rule=2, horizon_ticks=1000)
    s2.setup(seed=42, rule=2, horizon_ticks=300)
    s1.run_to_end()
    s2.run_to_end()  # exported after s1: must not overwrite s1's file
    name = "Data_100_Sto_R 2_0.csv"
    data1 = s1.directory / "Results" / "Data" / name
    data2 = s2.directory / "Results" / "Data" / name
    assert len(data1.read_text(encoding="utf-8").splitlines()) == 3
    assert data2.exists() and data2.read_text(encoding="utf-8") == ""
    assert all(p.is_relative_to(s1.directory) for p in s1.exported_csvs())
    assert all(p.is_relative_to(s2.directory) for p in s2.exported_csvs())


def test_two_sessions_alternating_match_solo(s1: SimulationSession, s2: SimulationSession) -> None:
    horizon = 3000
    s1.setup(seed=42, rule=3, horizon_ticks=horizon)
    s2.setup(seed=7, rule=3, horizon_ticks=horizon)
    while not (s1.finished and s2.finished):
        s1.step(100)
        s2.step(100)
    alternating = (s1.kpis(), snapshot(s1), s2.kpis(), snapshot(s2))

    s1.setup(seed=42, rule=3, horizon_ticks=horizon)
    s1.run_to_end()
    solo_42 = (s1.kpis(), snapshot(s1))
    s1.setup(seed=7, rule=3, horizon_ticks=horizon)
    s1.run_to_end()
    solo_7 = (s1.kpis(), snapshot(s1))

    assert alternating[:2] == solo_42
    assert alternating[2:] == solo_7
    assert solo_42[0] != solo_7[0]


def test_kpis_mid_run_do_not_alter_simulation(s1: SimulationSession, s2: SimulationSession) -> None:
    for session, read in ((s1, True), (s2, False)):
        session.setup(seed=42, rule=3)
        for _ in range(10):
            session.step(300)
            if read:
                session.kpis()
                session.state()
    assert snapshot(s1) == snapshot(s2)


def test_clone_at_3000_matches_original_after_1000_ticks(s1: SimulationSession, s2: SimulationSession) -> None:
    s1.setup(seed=42, rule=3)
    s1.step(3000)
    s2.setup(seed=999, rule=1)  # unrelated state in the target
    seconds = s1.clone_to(s2)
    assert seconds > 0
    assert s2.events() == []  # the clone starts with an empty event buffer
    assert s2.parameters.rule == 3 and s2.parameters.seed == 42 and s2.ticks == 3000
    assert s2.state() == s1.state()

    s1.events()  # leave both buffers empty before advancing
    s1.step(1000)
    s2.step(1000)
    assert s2.kpis() == s1.kpis()
    assert snapshot(s2) == snapshot(s1)
    assert not list((s1.directory / "worlds").glob("*.csv"))  # clone_to removes its temporary file


def test_export_once_import_many(s1: SimulationSession, s2: SimulationSession) -> None:
    s1.setup(seed=42, rule=2)
    s1.step(3000)
    path = s1.export_world()
    s1.events()  # imports start with an empty buffer; empty the original's too before comparing
    try:
        results = []
        for _ in range(2):
            s2.import_world(path)
            s2.step(300)
            results.append((s2.kpis(), snapshot(s2)))
        s1.step(300)
        assert results[0] == results[1] == (s1.kpis(), snapshot(s1))
    finally:
        path.unlink()


@pytest.mark.parametrize("rule", [1, 2, 3])
def test_horizon_10000_matches_baseline(s1: SimulationSession, rule: int) -> None:
    s1.setup(seed=42, rule=rule)
    s1.run_to_end()
    baseline_run = json.loads((BASELINE / f"rule{rule}" / f"validation_{rule}_42.json").read_text(encoding="utf-8"))["runs"][0]
    kpis = s1.kpis()
    assert kpis.ticks == baseline_run["ticks"] == 10000
    assert (kpis.finished, kpis.wip, kpis.throughput, kpis.mean_flow_time) == (
        baseline_run["finished"], baseline_run["wip"], baseline_run["throughput"], baseline_run["mean_flow_time"],
    )
    assert kpis.utilization == baseline_run["utilization"]
    events_csv = s1.directory / "Results" / "Events" / f"Event_100_Sto_R {rule}_0.csv"
    baseline_events = BASELINE / f"rule{rule}" / f"Event_100_Sto_R {rule}_0.csv"
    assert content_sha256(events_csv) == content_sha256(baseline_events)  # line endings normalized
