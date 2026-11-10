"""Decision makers without an LLM, behind one interface: decide(context) -> Decision | None.

    b1     lowest finish                          decision_level "heuristic"
    b1b    lowest finish_plus_next                decision_level "heuristic"
    agent  code part only: obvious decisions (or a single candidate) -> best by finish,
           "code-obvious"; otherwise None (the LLM flow in aclopi.agent.core decides)
Ties: lowest machine number. Context candidates are dicts as the API returns them
(aclopi/contracts/candidates.py).

Reasons (the text the platform's decision panel shows): in English, at most REASON_MAX characters
(short_reason cuts longer ones). Code levels write a fixed text with the number that justifies the
decision, e.g. "Obvious: M3 finishes 230 u.t. earlier" or "Fallback (LLM did not answer): M3 finishes first (+310 u.t.)".
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Callable

from aclopi.agent.triage import Triage, TriageParams, classify, fpn, ranked

REASON_MAX = 120
# why the agent fell back to the best by finish, by the start of its error (aclopi.agent.core)
FALLBACK_CAUSES = (("llm-timeout", "LLM timed out"), ("deadline", "LLM timed out"),
                   ("llm-call-limit", "LLM call limit"), ("llm-invalid-json", "invalid LLM answer"),
                   ("invalid-answer", "invalid LLM answer"), ("what-if-not-offered", "invalid LLM answer"),
                   ("machine-not-candidate", "LLM chose a non-candidate machine"), ("invalid-machine", "LLM chose a non-candidate machine"),
                   ("llm-", "LLM did not answer"), ("platform", "error reading the plant"))


def short_reason(text: str | None) -> str:
    """One line of at most REASON_MAX characters (cut with an ellipsis)."""
    text = " ".join((text or "").split())
    return text if len(text) <= REASON_MAX else text[:REASON_MAX - 1].rstrip() + "…"


def _rel(value: float, ctx_time: Any) -> str:
    return f"+{float(value) - float(ctx_time or 0.0):.0f} u.t."


def obvious_reason(t: Triage, candidates: list[dict[str, Any]], current_machine: str | None = None) -> str:
    """candidates: all the capable machines (before the discard); current_machine: where the product is."""
    m = t.best_by_finish
    if len(candidates) == 1:
        return f"Only capable machine: {m}"
    if len(t.finalists) == 1:  # the discard left one: real gap to the second best by finish
        gap = sorted(float(c["finish"]) for c in candidates)[1] - float(t.finalists[0]["finish"])
        stay = "stays on the same machine; " if m == current_machine else ""
        return short_reason(f"Obvious: {m} ({stay}the others ≥{gap:.0f} u.t. worse)")
    return f"Obvious: {m} finishes {t.gap_finish:.0f} u.t. earlier"


def fallback_reason(error: str | None, best: dict[str, Any], now: Any) -> str:
    cause = next((text for prefix, text in FALLBACK_CAUSES if (error or "").startswith(prefix)), "no LLM answer")
    return short_reason(f"Fallback ({cause}): {best['machine']} finishes first ({_rel(best['finish'], now)})")


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
    return Decision(best["machine"], ctx.seq, "heuristic",
                    f"B1: {best['machine']} finishes first ({_rel(best['finish'], ctx.candidates.get('time'))})")


def decide_b1b(ctx: DecisionContext) -> Decision:
    best = ranked(_candidates(ctx), "finish_plus_next")[0]
    return Decision(best["machine"], ctx.seq, "heuristic",
                    f"B1b: {best['machine']}, earliest finish with the next step ({_rel(fpn(best), ctx.candidates.get('time'))})")


def decide_agent_code(ctx: DecisionContext, params: TriageParams = TriageParams()) -> tuple[Decision | None, Triage]:
    """The code level of the agent: a Decision when obvious, else None plus the triage for the LLM."""
    t = classify(_candidates(ctx), params)
    if t.level == "obvious":
        return Decision(t.best_by_finish, ctx.seq, "code-obvious",
                        obvious_reason(t, _candidates(ctx), ctx.candidates.get("current_machine")), triage=t), t
    return None, t


def best_by_finish(ctx: DecisionContext, level: str, reason: str) -> Decision:
    """Fallback used by the agent when the LLM cannot decide in time (code-fallback)."""
    best = ranked(_candidates(ctx), "finish")[0]
    return Decision(best["machine"], ctx.seq, level, short_reason(reason))


HEURISTICS: dict[str, Callable[[DecisionContext], Decision]] = {"b1": decide_b1, "b1b": decide_b1b}


def decide(ctx: DecisionContext) -> Decision | None:
    """Common entry point without an LLM: b1 / b1b always decide; agent only obvious cases."""
    if ctx.strategy in HEURISTICS:
        return HEURISTICS[ctx.strategy](ctx)
    if ctx.strategy == "agent":
        return decide_agent_code(ctx)[0]
    raise ValueError(f"unknown strategy {ctx.strategy!r}")
