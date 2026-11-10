"""simulate_list (aclopi.sim.sequencing) with NetLogo: reproducible, cancellable, progress every
<= 1000 ticks. The comparison with b1b through the platform is in test_sequencing_platform (api)."""

from __future__ import annotations

from typing import Any

import pytest

from aclopi.sim import SimulationSession
from aclopi.sim.sequencing import simulate_list

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

    out = simulate_list(session, LIST_10, "b1", "Stochastic", 7, on_progress=progress)
    assert out["cancelled"] and not out["all_done"] and out["makespan_ticks"] is None
    assert 2000 <= out["ticks"] < 3000 and calls[-1] == out["ticks"]


def test_unknown_strategy(session: SimulationSession) -> None:
    with pytest.raises(ValueError):
        simulate_list(session, LIST_10, "agent")
