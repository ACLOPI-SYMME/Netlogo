"""Rule 4 (AI Agent) decision hook: equivalence with rule 3, a random decider and rejections."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterator

import pytest

from aclopi.sim import SimulationSession
from aclopi.sim.decisions import (
    clear_decisions,
    decision_log,
    pending_decisions,
    run_until_decision,
    set_next_machine,
)
from compare_baseline import sha256 as content_sha256
from make_long_fixtures import FIXTURES
from rule4_checks import RULE_NAME_COLUMN, SINGLE_MACHINE_OPERATIONS, compare, random_decider, run

RULE3_NAME, RULE4_NAME = "Rule 3 - Potential Fields", "Rule 4 - AI Agent"


@pytest.fixture(scope="module")
def session(tmp_path_factory: pytest.TempPathFactory) -> Iterator[SimulationSession]:
    with SimulationSession("decisions", results_root=tmp_path_factory.mktemp("decision_sessions")) as s:
        yield s


@pytest.mark.parametrize("seed", [42, 7])
def test_rule4_without_decider_matches_rule3(session: SimulationSession, seed: int) -> None:
    reference = run(session, 3, seed, 10000)
    # Requests are read and cleared every time one appears, but never answered.
    rule4 = run(session, 4, seed, 10000, poll=True)
    assert rule4.requests > 0 and rule4.answers == {}
    # Without answers every multi-machine assignment is a rule 3 fallback; the step to O9 (only M1)
    # is single-option, at least once per finished product.
    assert set(rule4.sources) == {"rule3-fallback", "single-option"}
    assert rule4.sources["single-option"] >= rule4.kpis["finished"] > 0

    eq = compare(reference, rule4)
    assert eq.kpi_differences == {}
    assert eq.events_identical
    assert eq.data_rows[0] == eq.data_rows[1] > 0
    # The rule name (block 0) is the only difference, and it differs in every row.
    assert eq.data_column_differences == {RULE_NAME_COLUMN: eq.data_rows[0]}


@pytest.mark.slow
@pytest.mark.parametrize("seed", [42, 7])
def test_rule4_without_decider_matches_rule3_long(session: SimulationSession, seed: int) -> None:
    """100,000 ticks against the rule 3 long-run fixtures (tests/fixtures/long)."""
    expected = json.loads((Path(FIXTURES) / f"rule3_seed{seed}.json").read_text(encoding="utf-8"))
    rule4 = run(session, 4, seed, 100000, poll=True)
    assert {k: rule4.kpis[k] for k in expected["kpis"]} == expected["kpis"]  # fixture keys only
    assert content_sha256(rule4.events_csv) == expected["events_sha256"]

    # Data: put the rule 3 name back in column 2; the rest must then be byte-identical.
    data = rule4.data_csv.read_bytes()
    rows = data.replace(b"\r\n", b"\n").splitlines()
    assert rows and all(row.split(b",")[RULE_NAME_COLUMN - 1] == RULE4_NAME.encode() for row in rows)
    normalized = rule4.data_csv.with_name("normalized.csv")
    normalized.write_bytes(data.replace(f",{RULE4_NAME},".encode(), f",{RULE3_NAME},".encode()))
    assert content_sha256(normalized) == expected["data_sha256"]


def test_random_decider_short_run(session: SimulationSession) -> None:
    session.setup(seed=42, rule=4, horizon_ticks=5000)
    choose = random_decider(42)
    answered: dict[tuple[int, int], str] = {}
    while True:
        result = run_until_decision(session, 5000)
        for request in pending_decisions(session):
            assert len(request.candidates) > 1 and request.origin.startswith("M")
            machine = choose(request)
            assert set_next_machine(session, request.who, machine, request.seq) == "ok"
            answered[(request.who, request.seq)] = machine
        clear_decisions(session)
        if result.finished:
            break
    assert result.ticks == 5000 and answered

    log = decision_log(session)
    for record in log:
        if record.operation in SINGLE_MACHINE_OPERATIONS:
            assert record.source == "single-option" and (record.who, record.seq) not in answered
        else:
            # Every multi-machine assignment was answered in time and applied as given.
            assert record.source == "agent"
            assert answered[(record.who, record.seq)] == record.chosen
    assert sum(r.source == "agent" for r in log) > 0
    # After the assignment the stored choice is consumed.
    for product in session.state()["products"]:
        assert product["decision_source"] in {"", "agent", "single-option"}


def test_rejections(session: SimulationSession) -> None:
    session.setup(seed=42, rule=3)
    assert set_next_machine(session, 200, "M2", 1) == "rule4-not-active"

    session.setup(seed=42, rule=4, horizon_ticks=10000)
    # Advance to the first request and keep it pending while the product is processed.
    result = run_until_decision(session, 10000)
    assert result.pending == 1
    request = pending_decisions(session)[0]
    clear_decisions(session)
    not_capable = next(m for m in ("M1", "M2", "M3", "M4", "M5", "M6", "M7") if m not in request.candidates)

    assert set_next_machine(session, request.who, request.candidates[0], request.seq - 1) == "stale-seq"
    assert set_next_machine(session, request.who, request.candidates[0], request.seq + 1) == "seq-mismatch"
    assert set_next_machine(session, request.who, not_capable, request.seq) == "machine-not-capable"
    assert set_next_machine(session, request.who, "M9", request.seq) == "unknown-machine"
    assert set_next_machine(session, 99999, request.candidates[0], request.seq) == "unknown-product"
    assert set_next_machine(session, 0, request.candidates[0], request.seq) == "unknown-product"  # a node
    product = next(p for p in session.state()["products"] if p["id"] == request.who)
    assert product["ai_next_machine"] == "" and product["ai_decision_seq"] == -1  # nothing stored
    assert set_next_machine(session, request.who, request.candidates[0], request.seq) == "ok"

    # Run on until a product has finished; answers for it are rejected.
    while session.state()["finished"] == 0:
        result = run_until_decision(session, 500)
        clear_decisions(session)
        assert not result.finished
    dead = int(session.link.report('platform-local [ -> min [who] of products with [Product.State = "death"]]'))
    assert set_next_machine(session, dead, "M2", 1) == "product-finished"

    # An answer arriving after the operation completed refers to an operation that already has
    # its machine: rejected as stale.
    record = decision_log(session)[0]
    assert set_next_machine(session, record.who, record.chosen, record.seq) in {"stale-seq", "product-finished"}
