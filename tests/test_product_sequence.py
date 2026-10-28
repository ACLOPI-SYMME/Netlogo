"""Fixed product sequence and work completed (A2). Reference: docs/product-sequence.md."""

from __future__ import annotations

import json
from collections import Counter
from typing import Any, Iterator

import pytest

from a1.measure_rng import created_products, run_products
from aclopi.sim import SimulationSession
from compare_baseline import sha256 as content_sha256

TYPES = {"A", "I", "P", "B", "E", "L", "T"}
HORIZONS = [10000, pytest.param(100000, marks=pytest.mark.slow)]


@pytest.fixture(scope="module")
def session(tmp_path_factory: pytest.TempPathFactory) -> Iterator[SimulationSession]:
    with SimulationSession("sequence", results_root=tmp_path_factory.mktemp("sequence_sessions")) as s:
        yield s


def sequence(session: SimulationSession, first: int, last: int) -> list[tuple[int, str, int]]:
    rows = json.loads(str(session.link.report(f"platform-product-sequence {first} {last}")))
    return [(r["n"], r["type"], r["priority"]) for r in rows]


def test_setup_switch(session: SimulationSession) -> None:
    session.setup(seed=42, rule=3)
    state = session.state()
    assert state["fixed_product_sequence"] is True and state["product_sequence_seed"] == 42
    assert session.parameters.fixed_product_sequence is True
    session.setup(seed=42, rule=3, fixed_product_sequence=False)
    state = session.state()
    assert state["fixed_product_sequence"] is False and state["product_sequence_seed"] == 42
    session.reset()
    assert session.state()["fixed_product_sequence"] is False  # reset keeps the setting


def test_sub_seed_formula(session: SimulationSession) -> None:
    session.setup(seed=42, rule=3)
    seeds = [int(session.link.report(f"Product.Sequence.Seed {n}")) for n in range(1, 6)]
    assert seeds == [(42 * 1000003 + n) % 2**31 for n in range(1, 6)]
    session.setup(seed=-5, rule=3)
    assert int(session.link.report("Product.Sequence.Seed 1")) == (-5 * 1000003 + 1) % 2**31


@pytest.mark.parametrize("horizon", HORIZONS)
def test_same_products_for_every_strategy(session: SimulationSession, horizon: int) -> None:
    """Rules 1 and 3 and rule 4 with the random decider get the same product n (type, priority)."""
    runs = {rule: run_products(session, rule, 42, horizon, fixed=True) for rule in (1, 3, 4)}
    common = min(len(p) for p in runs.values())
    assert common >= 8
    reference = [(p[1], p[3]) for p in runs[3][:common]]
    assert all([(p[1], p[3]) for p in runs[rule][:common]] == reference for rule in (1, 4))
    # ... and they are exactly the products of the sequence, n = 1, 2, ...
    session.setup(seed=42, rule=3)
    assert [(t, p) for _, t, p in sequence(session, 1, common)] == reference


@pytest.mark.parametrize("horizon", HORIZONS)
def test_same_seed_same_run_other_seed_other_set(session: SimulationSession, horizon: int) -> None:
    def full_run(seed: int) -> tuple[Any, ...]:
        session.setup(seed=seed, rule=3, horizon_ticks=horizon)
        session.run_to_end()
        results = session.directory / "Results"
        return (session.kpis(), created_products(session),
                content_sha256(results / "Events" / "Event_100_Sto_R 3_0.csv"),
                content_sha256(results / "Data" / "Data_100_Sto_R 3_0.csv"))

    first, again = full_run(42), full_run(42)
    assert first == again
    other = full_run(7)
    assert [(p[1], p[3]) for p in other[1]] != [(p[1], p[3]) for p in first[1]]
    session.setup(seed=7, rule=3)
    seven = sequence(session, 1, 50)
    session.setup(seed=42, rule=3)
    assert seven != sequence(session, 1, 50)


def snapshot(session: SimulationSession) -> dict[str, Any]:
    link = session.link
    return {
        "state": str(link.report("platform-state")),
        "events_csv": str(link.report("(word EventFrameInfo)")),
        "data_csv": str(link.report("(word DataFrameInfo)")),
        "rng": [int(link.report("random 2147483647")) for _ in range(3)],
    }


def test_sequence_reporter_matches_and_does_not_interfere(session: SimulationSession) -> None:
    session.setup(seed=42, rule=3, horizon_ticks=10000)
    session.step(5000)
    untouched = snapshot(session)

    session.setup(seed=42, rule=3, horizon_ticks=10000)
    preview = sequence(session, 1, 40)
    for _ in range(10):
        session.step(500)
        assert sequence(session, 1, 40) == preview  # read mid-run, many times
    assert snapshot(session) == untouched

    created = created_products(session)
    assert created and [(t, p) for _, t, _, p in created] == [(t, p) for _, t, p in preview[: len(created)]]
    assert session.state()["products_created"] == len(created)


def test_type_distribution_1000(session: SimulationSession) -> None:
    session.setup(seed=42, rule=3)
    products = sequence(session, 1, 1000)
    counts = Counter(t for _, t, _ in products)
    print("type counts in 1000 products, seed 42:", dict(sorted(counts.items())))
    assert set(counts) == TYPES
    assert all(100 <= c <= 190 for c in counts.values())  # expected 1000/7 = 143 each
    assert all(60 <= p <= 100 for _, _, p in products)


def test_work_completed_known_state(session: SimulationSession) -> None:
    """One product: O8 on M1 done (100), O1 done (200), O2 half processed on M2 (100 of 200)."""
    session.setup(seed=1, rule=3, fixed_product_sequence=False)
    link = session.link
    link.command(
        'create-products 1 [ set ProductOperations ["O8" "O1" "O2" "O9"] set Product.State "Processing.Product" '
        'set ProductRealStart [0 150 400] set ProductRealCompletion [100 360] set Machine.Used ["M1" "M2"] '
        'set Heading.Workstation "M2" set Next.Product.Operation "O2" ]'
    )
    link.command('ask machines with [Machine.Name = "M2"] [ set Machine.State "Machine.Processing" set Next.Completion 600 ]')
    link.command("set Simulated.Time 500")
    kpis = session.kpis()
    assert kpis.work_completed == pytest.approx(100 + 200 + 100)
    assert kpis.created == 1 and kpis.wip == 1 and kpis.finished == 0

    # Finished: the product dies after O9 (all four operations count in full).
    link.command('ask products [ set ProductRealStart [0 150 400 650] set ProductRealCompletion [100 360 610 760] '
                 'set Machine.Used ["M1" "M2" "M2" "M1"] set Product.State "death" ]')
    assert session.kpis().work_completed == pytest.approx(100 + 200 + 200 + 100)


def test_work_completed_in_a_run(session: SimulationSession) -> None:
    session.setup(seed=42, rule=3, fixed_product_sequence=False)
    session.run_to_end()
    kpis = session.kpis()
    assert kpis.created == kpis.finished + kpis.wip
    # At least the nominal work of the finished products, at most the busy time of the machines.
    finished_work = float(session.link.report(
        'sum map [p -> [sum map [o -> item ((read-from-string (last o)) - 1) OperationDuration] ProductOperations] of p] '
        'sort products with [Product.State = "death"]'))
    busy = sum(kpis.utilization.values()) * kpis.simulated_time
    assert finished_work <= kpis.work_completed <= busy + 1e-6
