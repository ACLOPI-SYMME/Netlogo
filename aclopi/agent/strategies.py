"""Decision makers without an LLM, behind one interface: decide(context) -> Decision | None.

    b1     lowest finish                          decision_level "heuristic"
    b1b    lowest finish_plus_next                decision_level "heuristic"
    agent  code part only: obvious decisions (or a single candidate) -> best by finish,
           "code-obvious"; otherwise None (the LLM flow in aclopi.agent.core decides)
Ties: lowest machine number. Context candidates are dicts as the API returns them
(aclopi/contracts/candidates.py).

Reasons (the text the platform's decision panel shows): in Spanish, at most REASON_MAX characters
(short_reason cuts longer ones). Code levels write a fixed text with the number that justifies the
decision, e.g. "Obvia: M3 termina 230 u.t. antes" or "Respaldo (el LLM no respondió): M3 termina antes (+310 u.t.)".
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Callable

from aclopi.agent.triage import Triage, TriageParams, classify, fpn, ranked

REASON_MAX = 120
# why the agent fell back to the best by finish, by the start of its error (aclopi.agent.core)
FALLBACK_CAUSES = (("llm-timeout", "el LLM no respondió a tiempo"), ("deadline", "el LLM no respondió a tiempo"),
                   ("llm-call-limit", "límite de llamadas al LLM"), ("llm-invalid-json", "respuesta del LLM no válida"),
                   ("invalid-answer", "respuesta del LLM no válida"), ("what-if-not-offered", "respuesta del LLM no válida"),
                   ("machine-not-candidate", "el LLM eligió una máquina no candidata"), ("invalid-machine", "el LLM eligió una máquina no candidata"),
                   ("llm-", "el LLM no respondió"), ("platform", "error al leer la planta"))


def short_reason(text: str | None, limit: int = REASON_MAX) -> str:
    """One line of at most `limit` characters (cut with an ellipsis)."""
    text = " ".join((text or "").split())
    return text if len(text) <= limit else text[:limit - 1].rstrip() + "…"


def _rel(value: float, ctx_time: Any) -> str:
    return f"+{float(value) - float(ctx_time or 0.0):.0f} u.t."


def obvious_reason(t: Triage, candidates: list[dict[str, Any]], current_machine: str | None = None) -> str:
    """candidates: all the capable machines (before the discard); current_machine: where the product is."""
    m = t.best_by_finish
    if len(candidates) == 1:
        return f"Única máquina capaz: {m}"
    if len(t.finalists) == 1:  # the discard left one: real gap to the second best by finish
        gap = sorted(float(c["finish"]) for c in candidates)[1] - float(t.finalists[0]["finish"])
        stay = "se queda en la misma máquina; " if m == current_machine else ""
        return short_reason(f"Obvia: {m} ({stay}las demás ≥{gap:.0f} u.t. peor)")
    return f"Obvia: {m} termina {t.gap_finish:.0f} u.t. antes"


def fallback_reason(error: str | None, best: dict[str, Any], now: Any) -> str:
    cause = next((text for prefix, text in FALLBACK_CAUSES if (error or "").startswith(prefix)), "sin respuesta del LLM")
    return short_reason(f"Respaldo ({cause}): {best['machine']} termina antes ({_rel(best['finish'], now)})")


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
                    f"B1: {best['machine']} termina antes ({_rel(best['finish'], ctx.candidates.get('time'))})")


def decide_b1b(ctx: DecisionContext) -> Decision:
    best = ranked(_candidates(ctx), "finish_plus_next")[0]
    return Decision(best["machine"], ctx.seq, "heuristic",
                    f"B1b: {best['machine']}, menor fin con el siguiente paso ({_rel(fpn(best), ctx.candidates.get('time'))})")


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
