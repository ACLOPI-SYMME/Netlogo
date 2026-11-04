"""b1 / b1b as rule 4 deciders on a local SimulationSession (fast mode, main thread only: P7).

    session.setup(seed=42, rule=4, horizon_ticks=100000)
    stats = run_with_strategy(session, "b1")

Every request is answered at once with candidates computed on the current state
(aclopi.sim.candidates); the run advances with platform-run-until-decision.
"""

from __future__ import annotations

import logging
from collections import Counter
from typing import Any

from aclopi.agent.strategies import DecisionContext, decide
from aclopi.sim.candidates import candidates_for_session, read_model_static
from aclopi.sim.decisions import clear_decisions, pending_decisions, run_until_decision, set_next_machine

logger = logging.getLogger(__name__)


def run_with_strategy(session: Any, strategy: str, max_ticks: int | None = None) -> dict[str, Any]:
    """Run to the end answering every request with `strategy`. Returns counters of the answers."""
    if strategy not in ("b1", "b1b"):
        raise ValueError("local runs support b1 and b1b (the agent runs as a service)")
    static = read_model_static(session)
    max_ticks = max_ticks or session.parameters.horizon_ticks
    answers: Counter[str] = Counter()
    while True:
        result = run_until_decision(session, max_ticks)
        for req in pending_decisions(session):
            cands = candidates_for_session(session, req.who, req.seq, static).as_dict()
            if not cands["valid"]:
                answers[f"invalid:{cands['reason']}"] += 1
                continue
            decision = decide(DecisionContext(None, req.who, req.seq, strategy, "fast", cands))
            answers[set_next_machine(session, req.who, decision.machine, req.seq)] += 1
        clear_decisions(session)
        if result.finished:
            return {"ticks": result.ticks, "answers": dict(answers)}
