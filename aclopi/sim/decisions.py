"""Rule 4 decision hook: Python chooses the next machine of each product.

With Reactivity.rule = "Rule 4 - AI Agent" the model queues a request when a product enters a
machine and the following operation can be done by more than one machine. Python reads the
requests, answers with set_next_machine while the product is being processed, and the model uses
the answer when the operation completes (rule 3 is applied if there is no valid answer).
Interface reference: docs/rule4-decision-hook.md.

Typical loop:

    session.setup(seed=42, rule=4)
    while True:
        result = run_until_decision(session, max_ticks=session.parameters.horizon_ticks)
        for request in pending_decisions(session):
            set_next_machine(session, request.who, choose(request), request.seq)
        clear_decisions(session)
        if result.finished:
            break
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from aclopi.sim.session import SimulationSession, netlogo_string

# agent: the machine chosen from Python; rule3-fallback: several capable machines and no valid
# answer; single-option: only one capable machine (no request is made), assigned by the rule 3 code.
DECISION_SOURCES = ("agent", "rule3-fallback", "single-option")


@dataclass(frozen=True)
class DecisionStepResult:
    ticks: int
    advanced: int
    finished: bool
    pending: int  # requests in the queue when the call returned


@dataclass(frozen=True)
class DecisionRequest:
    who: int
    seq: int  # index in ProductOperations of the operation to decide
    operation: str  # "O1".."O9"
    origin: str  # machine the product is in when the request was made
    tick: int
    candidates: tuple[str, ...]  # machines capable of the operation


@dataclass(frozen=True)
class DecisionRecord:
    tick: int
    who: int
    seq: int
    operation: str
    origin: str  # machine that completed the previous operation
    chosen: str  # machine assigned (Heading.Workstation)
    source: str  # one of DECISION_SOURCES


# The session's private helpers are used on purpose: they hold the session lock and check that
# the session is open and set up, exactly as SimulationSession's own methods do.


def run_until_decision(session: SimulationSession, max_ticks: int) -> DecisionStepResult:
    """Advance until there is a pending request, max_ticks have run or the run ends (one call).

    Does not advance while requests are pending: read them and call clear_decisions first.
    """
    if max_ticks < 0:
        raise ValueError("max_ticks must be >= 0")
    with session._lock:
        session._require_params()
        ticks, advanced, finished, pending = (
            int(v) for v in session._report(f"platform-run-until-decision {int(max_ticks)}")
        )
    return DecisionStepResult(ticks=ticks, advanced=advanced, finished=finished == 1, pending=pending)


def pending_decisions(session: SimulationSession) -> list[DecisionRequest]:
    """Requests queued since the last clear_decisions (the queue is not emptied)."""
    session._require_params()
    payload = session._report_json("platform-pending-decisions")
    return [
        DecisionRequest(int(who), int(seq), str(op), str(origin), int(tick), tuple(str(m) for m in candidates))
        for who, seq, op, origin, tick, candidates in payload["requests"]
    ]


def clear_decisions(session: SimulationSession) -> None:
    """Empty the request queue."""
    session._require_params()
    session._command("platform-clear-decisions")


def set_next_machine(session: SimulationSession, who: int, machine: str, seq: int) -> str:
    """Choose the machine for operation seq of product who. Returns "ok" or the rejection reason."""
    session._require_params()
    return str(session._report(f"platform-set-next-machine {int(who)} {netlogo_string(machine)} {int(seq)}"))


def decision_log(session: SimulationSession, clear: bool = False) -> list[DecisionRecord]:
    """Assignments made by rule 4 since the last clear (optionally emptying the log)."""
    with session._lock:
        session._require_params()
        payload: dict[str, Any] = session._report_json("platform-decision-log")
        if clear:
            session._command("platform-clear-decision-log")
    return [
        DecisionRecord(int(tick), int(who), int(seq), str(op), str(origin), str(chosen), str(source))
        for tick, who, seq, op, origin, chosen, source in payload["decisions"]
    ]


def clear_decision_log(session: SimulationSession) -> None:
    """Empty the decision log."""
    session._require_params()
    session._command("platform-clear-decision-log")


def _job_left(machine: dict[str, Any] | None, now: float) -> float:
    """What is left of the machine's job (u.t.), from platform-state's next_completion."""
    if not machine or machine.get("state") != "Machine.Processing" or machine.get("next_completion") is None:
        return 0.0
    return max(0.0, float(machine["next_completion"]) - now)


def product_priorities(session: SimulationSession, whos: list[int]) -> dict[int, int | None]:
    """Product variable `priority` of each product (null if it no longer exists). A reporter: no random
    numbers (platform-state has the type but not the priority)."""
    if not whos:
        return {}
    ids = " ".join(str(int(w)) for w in whos)
    values = json.loads(str(session._report(
        f"platform-local [ -> json-any map [w -> ifelse-value is-turtle? turtle w [[priority] of turtle w] [-1]] [{ids}] ]")))
    return {int(w): (None if v is None or float(v) < 0 else int(v)) for w, v in zip(whos, values)}


def decision_context(state: dict[str, Any], who: int, seq: int, priority: int | None = None) -> dict[str, Any]:
    """Context of a decision request for POST /decide, from one platform-state (pure; no random numbers).

    Product: current_machine (where it is processed; null if it is no longer in a machine),
    current_operation (seq - 1), own_remaining (u.t. left of it), next_operation (seq + 1, the one
    after the operation decided; null if seq is the last), pending_operations (seq onwards, in order,
    the decided one first), product_type (A, I, P, B, E, L or T) and priority (read apart by
    product_priorities). Plant: products_in_plant (alive) and m1 = {busy, remaining (u.t.),
    queue_length}. context_tick: tick of the state (in live, the end of the block that read the request).
    """
    now = float(state["time"])
    product = next((p for p in state["products"] if int(p["id"]) == int(who)), None)
    operations = [str(o) for o in (product.get("operations") or [])] if product else []
    current = next((m for m in state["machines"] if m.get("product") == int(who)), None)
    m1 = next((m for m in state["machines"] if m.get("name") == "M1"), None)
    return {
        "context_tick": int(state["tick"]),
        "product_type": str(product["type"]) if product and product.get("type") is not None else None,
        "priority": priority,
        "current_machine": current["name"] if current else None,
        "current_operation": operations[seq - 1] if 0 < seq <= len(operations) else None,
        "own_remaining": round(_job_left(current, now), 4),
        "next_operation": operations[seq + 1] if 0 <= seq + 1 < len(operations) else None,
        "pending_operations": operations[seq:] if 0 <= seq < len(operations) else [],
        "products_in_plant": len(state["products"]),
        "m1": {"busy": bool(m1 and m1.get("state") == "Machine.Processing"),
               "remaining": round(_job_left(m1, now), 4),
               "queue_length": len((m1 or {}).get("queue") or [])},
    }
