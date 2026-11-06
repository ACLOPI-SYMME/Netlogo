"""Level of a decision, decided by code from the candidates' differences in u.t. (never by the LLM).

    discard   (more than 2 candidates) a candidate more than u_wide behind the best by finish AND
              more than u_wide behind the best by finish_plus_next (each against its own best)
    obvious   among the rest: gap > u_wide in both criteria and both pick the same machine; or a
              single candidate left -> code decides (code-obvious)
    very_close  gap <= u_narrow in either criterion -> LLM, which may ask for a what-if
    uncertain   the rest -> LLM without what-if

What-if options (exactly 2, chosen by code): the best by finish and the best by finish_plus_next;
if they are the same machine, the two best by finish. Ties: lowest machine number.
Candidates are dicts with the fields of aclopi/contracts/candidates.py (as the API returns them).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

Level = Literal["obvious", "uncertain", "very_close"]


@dataclass(frozen=True)
class TriageParams:
    u_wide: float = 100.0
    u_narrow: float = 50.0


@dataclass(frozen=True)
class Triage:
    level: Level
    finalists: list[dict[str, Any]]  # sorted by finish
    discarded: list[str] = field(default_factory=list)
    best_by_finish: str | None = None
    best_by_finish_plus_next: str | None = None
    gap_finish: float | None = None  # among the finalists
    gap_finish_plus_next: float | None = None
    what_if_options: tuple[str, str] | None = None

    @property
    def machines(self) -> list[str]:
        return [c["machine"] for c in self.finalists]


def _number(c: dict[str, Any]) -> int:
    return int(str(c["machine"])[1:])


def fpn(c: dict[str, Any]) -> float:
    """finish_plus_next, or finish when the candidate has no next machine data."""
    v = c.get("finish_plus_next")
    return float(c["finish"]) if v is None else float(v)


def ranked(candidates: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    value = (lambda c: float(c["finish"])) if key == "finish" else fpn
    return sorted(candidates, key=lambda c: (value(c), _number(c)))


def classify(candidates: list[dict[str, Any]], params: TriageParams = TriageParams()) -> Triage:
    if not candidates:
        raise ValueError("no candidates")
    by_f, by_n = ranked(candidates, "finish"), ranked(candidates, "finish_plus_next")
    best_f, best_n = float(by_f[0]["finish"]), fpn(by_n[0])
    discarded: list[str] = []
    finalists = by_f
    if len(candidates) > 2:
        finalists = [c for c in by_f if not (float(c["finish"]) - best_f > params.u_wide and fpn(c) - best_n > params.u_wide)]
        discarded = [c["machine"] for c in by_f if c not in finalists]
    by_f, by_n = ranked(finalists, "finish"), ranked(finalists, "finish_plus_next")
    bf, bn = by_f[0]["machine"], by_n[0]["machine"]
    if len(finalists) == 1:
        return Triage("obvious", finalists, discarded, bf, bn)
    gap_f = float(by_f[1]["finish"]) - float(by_f[0]["finish"])
    gap_n = fpn(by_n[1]) - fpn(by_n[0])
    options = (bf, bn) if bf != bn else (by_f[0]["machine"], by_f[1]["machine"])
    if gap_f > params.u_wide and gap_n > params.u_wide and bf == bn:
        level: Level = "obvious"
    elif gap_f <= params.u_narrow or gap_n <= params.u_narrow:
        level = "very_close"
    else:
        level = "uncertain"
    return Triage(level, finalists, discarded, bf, bn, round(gap_f, 4), round(gap_n, 4), options)
