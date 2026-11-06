"""Triage levels and the b1 / b1b / agent-code deciders (no NetLogo)."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from aclopi.agent import local
from aclopi.agent.strategies import DecisionContext, decide, decide_agent_code, decide_b1, decide_b1b
from aclopi.agent.triage import TriageParams, classify


def cand(machine: str, finish: float, fpn: float | None = None) -> dict[str, Any]:
    return {"machine": machine, "finish": finish, "finish_plus_next": finish if fpn is None else fpn}


def ctx(cands: list[dict[str, Any]], strategy: str = "agent") -> DecisionContext:
    return DecisionContext("s", 200, 2, strategy, "fast", {"candidates": cands})


def test_default_thresholds() -> None:
    from aclopi.agent.service import AgentSettings

    assert (TriageParams().u_wide, TriageParams().u_narrow) == (100.0, 50.0)
    triage = AgentSettings.from_env({}).config.triage
    assert (triage.u_wide, triage.u_narrow) == (100.0, 50.0)


def test_obvious_when_both_criteria_agree_by_far() -> None:
    t = classify([cand("M3", 1000, 1100), cand("M2", 1300, 1400), cand("M5", 1400, 1500)])
    assert t.level == "obvious" and t.best_by_finish == "M3"


def test_discard_needs_both_criteria() -> None:
    # M7 is far by finish but close by finish_plus_next: it stays.
    t = classify([cand("M3", 1000, 1300), cand("M2", 1040, 1350), cand("M7", 1400, 1320), cand("M5", 1500, 1600)])
    assert t.discarded == ["M5"] and t.machines == ["M3", "M2", "M7"]


def test_no_discard_with_two_candidates() -> None:
    t = classify([cand("M3", 1000), cand("M2", 1500)])
    assert t.discarded == [] and len(t.finalists) == 2 and t.level == "obvious"


def test_single_candidate_after_discard_is_obvious() -> None:
    t = classify([cand("M3", 1000), cand("M2", 1200), cand("M5", 1300)])
    assert t.level == "obvious" and t.machines == ["M3"] and t.discarded == ["M2", "M5"]


def test_very_close_by_either_criterion() -> None:
    assert classify([cand("M3", 1000, 1500), cand("M2", 1040, 1800)]).level == "very_close"  # finish gap 40
    assert classify([cand("M3", 1000, 1500), cand("M2", 1100, 1520)]).level == "very_close"  # fpn gap 20


def test_uncertain_cases() -> None:
    assert classify([cand("M3", 1000, 1500), cand("M2", 1100, 1600)]).level == "uncertain"  # gaps 100
    # Gaps over u_wide but each criterion picks another machine.
    assert classify([cand("M3", 1000, 1700), cand("M2", 1200, 1500)]).level == "uncertain"


def test_what_if_options() -> None:
    t = classify([cand("M3", 1000, 1600), cand("M2", 1020, 1500), cand("M5", 1030, 1700)])
    assert t.what_if_options == ("M3", "M2")  # best by finish, best by finish_plus_next
    t = classify([cand("M3", 1000, 1500), cand("M2", 1020, 1550), cand("M5", 1030, 1520)])
    assert t.what_if_options == ("M3", "M2")  # same best: the two best by finish


def test_ties_lowest_machine_number() -> None:
    t = classify([cand("M5", 1000), cand("M3", 1000)])
    assert t.best_by_finish == "M3"
    assert decide_b1(ctx([cand("M7", 900), cand("M2", 900)])).machine == "M2"


def test_thresholds_are_configurable() -> None:
    cands = [cand("M3", 1000, 1100), cand("M2", 1100, 1200)]
    assert classify(cands).level == "uncertain"
    assert classify(cands, TriageParams(u_wide=80, u_narrow=20)).level == "obvious"
    assert classify(cands, TriageParams(u_wide=300, u_narrow=120)).level == "very_close"


def test_b1_b1b_and_agent_code() -> None:
    cands = [cand("M3", 1000, 1700), cand("M2", 1100, 1300)]
    b1, b1b = decide_b1(ctx(cands, "b1")), decide_b1b(ctx(cands, "b1b"))
    assert (b1.machine, b1.decision_level) == ("M3", "heuristic")
    assert (b1b.machine, b1b.decision_level) == ("M2", "heuristic")
    assert decide(ctx(cands)) is None  # agent: not obvious -> LLM
    d, t = decide_agent_code(ctx([cand("M3", 1000), cand("M2", 1300)]))
    assert d is not None and (d.machine, d.decision_level) == ("M3", "code-obvious") and t.level == "obvious"
    with pytest.raises(ValueError):
        decide(ctx(cands, "rule3"))


def test_local_run_with_strategy(monkeypatch: pytest.MonkeyPatch) -> None:
    """run_with_strategy answers every request with the strategy's choice (functions faked)."""
    sent: list[tuple[int, str, int]] = []
    steps = iter([SimpleNamespace(ticks=100, finished=False), SimpleNamespace(ticks=200, finished=True)])
    monkeypatch.setattr(local, "read_model_static", lambda s: None)
    monkeypatch.setattr(local, "run_until_decision", lambda s, n: next(steps))
    monkeypatch.setattr(local, "pending_decisions", lambda s: [SimpleNamespace(who=201, seq=1)])
    monkeypatch.setattr(local, "clear_decisions", lambda s: None)
    monkeypatch.setattr(local, "candidates_for_session", lambda s, w, q, st: SimpleNamespace(
        as_dict=lambda: {"valid": True, "candidates": [cand("M3", 1000, 1700), cand("M2", 1100, 1300)]}))
    monkeypatch.setattr(local, "set_next_machine", lambda s, w, m, q: sent.append((w, m, q)) or "ok")
    session = SimpleNamespace(parameters=SimpleNamespace(horizon_ticks=200))
    out = local.run_with_strategy(session, "b1b")
    assert out == {"ticks": 200, "answers": {"ok": 2}} and sent == [(201, "M2", 1), (201, "M2", 1)]
