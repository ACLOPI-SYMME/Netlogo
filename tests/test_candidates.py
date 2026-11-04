"""aclopi.sim.candidates (stub of Línea A's signatures): results and no random numbers consumed."""

from __future__ import annotations

from typing import Any

import pytest

from aclopi.contracts.candidates import CandidatesResult
from aclopi.sim import SimulationSession
from aclopi.sim.candidates import candidates_for_session, compute_candidates, read_model_static
from aclopi.sim.decisions import clear_decisions, pending_decisions, run_until_decision


def _in_machine(state: dict[str, Any]) -> list[tuple[int, int]]:
    """(product, pending seq) of the products being processed whose next operation exists."""
    busy = {m.get("product") for m in state["machines"]}
    return [(p["id"], int(p["sequence_order"]) + 1) for p in state["products"]
            if p["id"] in busy and int(p["sequence_order"]) + 1 < len(p["operations"])]


def test_candidates_match_the_rule4_hook() -> None:
    with SimulationSession() as s:
        s.setup(seed=42, rule=4)
        static = read_model_static(s)
        assert static.capable_machines["O1"] == ["M2", "M3", "M5", "M7"]
        assert static.nominal_times["O8"] == 100.0 and static.modeling_type == "Stochastic"
        checked = 0
        while checked < 5:
            run_until_decision(s, 5000)
            for req in pending_decisions(s):
                result = candidates_for_session(s, req.who, req.seq, static)
                assert isinstance(result, CandidatesResult) and result.valid, result
                assert result.operation == req.operation
                assert sorted(c.machine for c in result.candidates) == sorted(req.candidates)
                finishes = [c.finish for c in result.candidates]
                assert finishes == sorted(finishes) and result.candidates[0].delta_finish == 0
                for c in result.candidates:
                    assert c.start >= c.arrival and c.finish > c.start
                    if result.next_operation is None:
                        assert c.next_machine is None
                    else:
                        assert c.next_machine in static.capable_machines[result.next_operation]
                checked += 1
            clear_decisions(s)
        state = s.state()
        product = state["products"][0]["id"]
        assert compute_candidates(state, 99999, 1, static).reason == "unknown-or-finished-product"
        assert compute_candidates(state, product, 99, static).reason == "invalid-seq"


def test_candidates_do_not_consume_random_numbers() -> None:
    def run(call_every: int | None) -> tuple[dict[str, Any], int]:
        calls = 0
        with SimulationSession() as s:
            s.setup(seed=42, rule=3)
            static = read_model_static(s)
            while not s.step(500).finished:
                if call_every:
                    state = s.state()
                    for product, seq in _in_machine(state):
                        candidates_for_session(s, product, seq, static)
                        calls += 1
            return s.kpis().as_dict(), calls

    plain, _ = run(None)
    with_calls, calls = run(500)
    assert calls > 10
    assert with_calls == plain


@pytest.mark.parametrize("bad_seq", [0, 5])
def test_seq_must_be_the_pending_one(bad_seq: int) -> None:
    with SimulationSession() as s:
        s.setup(seed=42, rule=4)
        static = read_model_static(s)
        run_until_decision(s, 5000)
        req = pending_decisions(s)[0]
        if bad_seq == req.seq:
            bad_seq += 1
        assert candidates_for_session(s, req.who, bad_seq, static).valid is False
