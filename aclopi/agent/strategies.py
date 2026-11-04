"""Decision makers without an LLM, behind one interface: decide(context) -> Decision | None.

    b1     lowest finish                          decision_level "heuristic"
    b1b    lowest finish_plus_next                decision_level "heuristic"
    agent  code part only: obvious decisions (or a single candidate) -> best by finish,
           "code-obvious"; otherwise None (the LLM flow in aclopi.agent.core decides)
Ties: lowest machine number. Context candidates are dicts as the API returns them
(aclopi/contracts/candidates.py).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Callable

from aclopi.agent.triage import Triage, TriageParams, classify, ranked


@dataclass(frozen=True)
class DecisionContext:
    session_id: str | None
    product: int
    seq: int
    strategy: str
    mode: str  # live | fast
    candidates: dict[str, Any]  # CandidatesResult as a dict
    ticks_per_second: float | None = None


@dataclass
class Decision:
    machine: str
    seq: int
    decision_level: str
    reason: str
    latencies: dict[str, Any] = field(default_factory=dict)
    triage: Triage | None = None

    def as_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d.pop("triage")
        return d


def _candidates(ctx: DecisionContext) -> list[dict[str, Any]]:
    cands = ctx.candidates.get("candidates") or []
    if not cands:
        raise ValueError(f"no candidates for product {ctx.product} seq {ctx.seq}")
    return cands


def decide_b1(ctx: DecisionContext) -> Decision:
    best = ranked(_candidates(ctx), "finish")[0]
    return Decision(best["machine"], ctx.seq, "heuristic", f"b1: lowest finish ({best['finish']:.1f})")


def decide_b1b(ctx: DecisionContext) -> Decision:
    best = ranked(_candidates(ctx), "finish_plus_next")[0]
    return Decision(best["machine"], ctx.seq, "heuristic", "b1b: lowest finish_plus_next")


def decide_agent_code(ctx: DecisionContext, params: TriageParams = TriageParams()) -> tuple[Decision | None, Triage]:
    """The code level of the agent: a Decision when obvious, else None plus the triage for the LLM."""
    t = classify(_candidates(ctx), params)
    if t.level == "obvious":
        why = "single candidate" if len(t.finalists) == 1 else f"gaps {t.gap_finish} / {t.gap_finish_plus_next} u.t."
        return Decision(t.best_by_finish, ctx.seq, "code-obvious", f"obvious: {why}", triage=t), t
    return None, t


def best_by_finish(ctx: DecisionContext, level: str, reason: str) -> Decision:
    """Fallback used by the agent when the LLM cannot decide in time (code-fallback)."""
    best = ranked(_candidates(ctx), "finish")[0]
    return Decision(best["machine"], ctx.seq, level, reason)


HEURISTICS: dict[str, Callable[[DecisionContext], Decision]] = {"b1": decide_b1, "b1b": decide_b1b}


def decide(ctx: DecisionContext) -> Decision | None:
    """Common entry point without an LLM: b1 / b1b always decide; agent only obvious cases."""
    if ctx.strategy in HEURISTICS:
        return HEURISTICS[ctx.strategy](ctx)
    if ctx.strategy == "agent":
        return decide_agent_code(ctx)[0]
    raise ValueError(f"unknown strategy {ctx.strategy!r}")
