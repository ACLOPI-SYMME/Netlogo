"""simulate_list (aclopi.sim.sequencing) with NetLogo: reproducible, cancellable, progress every
<= 1000 ticks, details; plant_context.json equal to the model. The comparison with b1b through the
platform is in test_sequencing_platform (api)."""

from __future__ import annotations

import json
from typing import Any

import pytest

from aclopi.agent.sequencing_context import entry_checks, load_plant, read_plant
from aclopi.sim import SimulationSession
from aclopi.sim.sequencing import DETAILS_REPORTER, simulate_list

LIST_10 = [{"type": t, "priority": 80} for t in "ABIEAPBTLA"]


@pytest.fixture(scope="module")
def session() -> Any:
    with SimulationSession() as s:
        yield s


def test_same_seed_and_list_give_the_same_makespan(session: SimulationSession) -> None:
    calls: list[tuple[int, int, int]] = []
    first = simulate_list(session, LIST_10, "b1b", "Deterministic", 42, on_progress=lambda *a: calls.append(a))
    second = simulate_list(session, LIST_10, "b1b", "Deterministic", 42)
    assert first["all_done"] and not first["cancelled"] and first["makespan_ticks"] > 0
    assert (first["makespan_ticks"], first["makespan_time"]) == (second["makespan_ticks"], second["makespan_time"])
    ticks = [0] + [c[0] for c in calls]
    assert max(b - a for a, b in zip(ticks, ticks[1:])) <= 1000
    assert calls[-1][1:] == (10, 10)  # done, total
    rule3 = simulate_list(session, LIST_10, "rule3", "Deterministic", 42)
    assert rule3["all_done"] and rule3["makespan_ticks"] != first["makespan_ticks"]


def test_cancel(session: SimulationSession) -> None:
    calls: list[int] = []

    def progress(ticks: int, done: int, total: int) -> bool:
        calls.append(ticks)
        return ticks < 2000

    out = simulate_list(session, LIST_10, "b1", "Stochastic", 7, on_progress=progress, details=True)
    assert out["cancelled"] and not out["all_done"] and out["makespan_ticks"] is None and out["details"] is None
    assert 2000 <= out["ticks"] < 3000 and calls[-1] == out["ticks"]


def test_unknown_strategy(session: SimulationSession) -> None:
    with pytest.raises(ValueError):
        simulate_list(session, LIST_10, "agent")


def test_details(session: SimulationSession) -> None:
    plain = simulate_list(session, LIST_10, "b1b", "Deterministic", 42)
    out = simulate_list(session, LIST_10, "b1b", "Deterministic", 42, details=True)
    assert out["makespan_ticks"] == plain["makespan_ticks"] and "details" not in plain  # reading them changes nothing
    d = out["details"]
    assert [p["type"] for p in d["products"]] == [p["type"] for p in LIST_10] and [p["index"] for p in d["products"]] == list(range(10))
    assert all(p["entry_tick"] < p["start_tick"] < p["end_tick"] for p in d["products"])
    assert d["products"][d["last"]]["end_tick"] == out["makespan_ticks"]
    # O8 + O9 of each product (a completion is recorded in the tick it is detected: a little over 100 u.t.)
    assert d["occupancy"]["M1"] == pytest.approx(100 * 10 * 200 / out["makespan_time"], abs=0.5)
    assert d["m1_idle"]["total_ticks"] == pytest.approx(out["makespan_ticks"] * (1 - d["occupancy"]["M1"] / 100), abs=30)
    w = d["entry_windows"]
    assert w["created"] == 10 and w["checks"] == w["created"] + w["zone_busy"] + w["wip_full"]
    created = [round(float(r[2]), 2) for r in json.loads(str(session._report(DETAILS_REPORTER)))]
    checks = [round(c, 2) for c in entry_checks(load_plant(), 200)]
    assert set(created) <= set(checks) and checks.index(created[-1]) + 1 == w["checks"]  # creations land on checks


def test_plant_file_equals_the_model(session: SimulationSession) -> None:
    """If this fails after a change to the model: python scripts/a4/export_plant_context.py"""
    assert read_plant(session) == load_plant()
