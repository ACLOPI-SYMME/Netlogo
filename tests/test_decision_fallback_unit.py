"""A decision the agent never answered (the model applied rule 3) is logged and published as late, without
NetLogo: the registry gets the block's assignments as the worker pushes them."""

from __future__ import annotations

import json
import time

from aclopi.api.hub import SessionHub
from aclopi.api.registry import SessionRecord, SessionRegistry


def _record() -> SessionRecord:
    now = time.time()
    r = SessionRecord(session_id="s", parameters={"seed": 1, "rule": 4, "modeling_type": "Stochastic", "horizon_ticks": 10000},
                      worker_slot=0, created_at=now, last_activity=now, last_activity_mono=time.monotonic(),
                      hub=SessionHub("s"), strategy="agent")
    r.run_state = "running_live"
    return r


def test_rule3_fallback_is_a_late_decision() -> None:
    reg = SessionRegistry(pool=None, idle_timeout_s=600, limiter=None)  # type: ignore[arg-type]
    record = _record()
    reg._records["s"] = record
    sub = record.hub.subscribe()
    # the request sent to the agent (no agent configured here: only kept as pending)
    reg._request_decision(record, {"who": 208, "seq": 1, "tick": 7400, "operation": "O3", "origin": "M2",
                                   "candidates": ["M3", "M4"], "product_type": "I"})
    assert (208, 1) in record.decision_requests
    # the next block: the model applied rule 3 to it, and the agent's own decision for another product
    reg._decision_push(record, "tick", {"assignments": [
        {"tick": 7463, "who": 208, "seq": 1, "operation": "O3", "origin": "M2", "chosen": "M4", "source": "rule3-fallback"},
        {"tick": 7470, "who": 209, "seq": 0, "operation": "O1", "origin": "M1", "chosen": "M3", "source": "agent"}]})
    assert record.decision_requests == {}
    [entry] = record.decision_log
    assert (entry["decision_level"], entry["machine"], entry["late"], entry["request_tick"]) == ("rule3-fallback", "M4", True, 7400)
    assert entry["product_type"] == "I" and entry["operation"] == "O3" and "rule 3" in entry["reason"]
    published = [json.loads(t) for t in sub.items]
    assert published[-1]["type"] == "decision" and published[-1]["level"] == "rule3-fallback" and published[-1]["late"]
    metrics = reg.decision_metrics(record)
    assert (metrics["late"], metrics["applied"], metrics["unanswered"]) == (1, 0, 0)
    assert metrics["sources"] == {"rule3-fallback": 1, "agent": 1} and metrics["rule3_fallback_pct"] == 50.0
