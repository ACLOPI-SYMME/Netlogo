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
