"""decision_context (POST /decide product context and plant summary) on a hand-built platform-state."""

from __future__ import annotations

import pytest

from aclopi.contracts.agent import DECIDE_CONTEXT_FIELDS, DecideRequest
from aclopi.sim.decisions import decision_context
from test_candidates_unit import ME, OPS_E, machine, product, state


def test_context_in_machine() -> None:
    s = state({"M2": machine("M2", ME, 1100.0), "M1": machine("M1", 300, 1040.0, queue=[301, 302])},
              [product(ME, OPS_E, 1, "M2"), product(300, OPS_E, 0, "M1"), product(301, OPS_E, 0, "M1")])
    c = decision_context(s, ME, 2)
    assert set(c) == set(DECIDE_CONTEXT_FIELDS)
    assert c["current_machine"] == "M2" and c["current_operation"] == "O1" and c["own_remaining"] == pytest.approx(100)
    assert c["next_operation"] == "O1" and c["pending_operations"] == OPS_E[2:]
    assert c["products_in_plant"] == 3 and c["context_tick"] == 3226
    assert c["m1"] == {"busy": True, "remaining": pytest.approx(40), "queue_length": 2}
    body = DecideRequest(session_id="s", product=ME, seq=2, strategy="b1", mode="fast", ticks_per_second=None,
                         tick=3226, simulated_time=1000.0, **c)
    assert body.model_dump()["m1"]["queue_length"] == 2


def test_context_last_operation_and_left_machine() -> None:
    s = state({}, [product(ME, OPS_E, 6, "M1")])
    c = decision_context(s, ME, 7)  # O9, the last one; the product is travelling
    assert c["current_machine"] is None and c["own_remaining"] == 0 and c["current_operation"] == "O4"
    assert c["next_operation"] is None and c["pending_operations"] == ["O9"]
    assert c["m1"] == {"busy": False, "remaining": 0, "queue_length": 0}
    gone = decision_context(s, 999, 2)  # finished product: no product data
    assert gone["current_operation"] is None and gone["pending_operations"] == []
