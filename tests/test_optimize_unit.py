"""Optimize order without NetLogo (docs/optimize-order.md): orders of the AI (invalid and repeated), the
strategy of each rule, the 409 / 422 / 503 rules, the settings and the mock agent's orders."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from aclopi.agent_mock.app import mock_orders
from aclopi.api import Settings, create_app
from aclopi.api.errors import FastRunLimit, OptimizeNotAllowed, OptimizeTooManyProducts
from aclopi.api.hub import SessionHub
from aclopi.api.optimize import check_can_optimize, classify, is_permutation, reordered, sim_strategy
from aclopi.api.registry import SessionRecord, SessionRegistry

LIST = [{"type": t, "priority": 80} for t in "IAEB"]


def test_permutations() -> None:
    assert is_permutation([2, 0, 1], 3)
    for bad in ([0, 1], [0, 1, 1], [0, 1, 3], [0, 1, "2"], [True, 0, 2], None, "012"):
        assert not is_permutation(bad, 3), bad


def test_classify_invalid_and_repeated() -> None:
    known = [([0, 1, 2, 3], "Original"), ([1, 3, 2, 0], "Heuristic")]
    orders = [{"order": [3, 2, 1, 0], "reasoning": "a"}, {"order": [0, 1, 2], "reasoning": "short"},
              {"order": [1, 3, 2, 0], "reasoning": "same as heuristic"}, {"order": [3, 2, 1, 0], "reasoning": "again"},
              {"order": [0, 0, 1, 2]}, "not a dict", {"order": [2, 3, 0, 1], "reasoning": "b"}]
    new, discarded = classify(orders, 4, known, "AI round 1 · {}")
    assert new == [{"order": [3, 2, 1, 0], "reasoning": "a"}, {"order": [2, 3, 0, 1], "reasoning": "b"}]
    assert [(d["reason"], d["same_as"]) for d in discarded] == [
        ("invalid", None), ("same_as", "Heuristic"), ("same_as", "AI round 1 · 1"), ("invalid", None), ("invalid", None)]


@pytest.mark.parametrize("rule, strategy, expected", [
    (1, None, "rule1"), (2, None, "rule2"), (3, None, "rule3"),
    (4, "agent", "b1b"), (4, "b1b", "b1b"), (4, "b1", "b1"), (4, "none", "b1b"), (4, None, "b1b"),
])
def test_strategy_of_each_rule(rule: int, strategy: str | None, expected: str) -> None:
    assert sim_strategy(rule, strategy) == expected


def test_reordered_is_a_copy() -> None:
    out = reordered(LIST, [1, 3, 2, 0])
    assert [p["type"] for p in out] == list("ABEI") and out[0] is not LIST[1]
    assert reordered(LIST, None) == LIST


# ----- the rules of POST /sessions/{id}/optimize-order -----

class _Agent:
    available = True


def _record(sid: str, rule: int = 3, products: Any = LIST, run_state: str = "idle", strategy: str | None = None,
            ticks: int = 0) -> SessionRecord:
    now = time.time()
    r = SessionRecord(session_id=sid, parameters={"seed": 1, "rule": rule, "modeling_type": "Stochastic",
                                                  "horizon_ticks": 10000},
                      worker_slot=0, created_at=now, last_activity=now, last_activity_mono=time.monotonic(),
                      hub=SessionHub(sid), strategy=strategy, product_list=[dict(p) for p in products] if products else None)
    r.run_state, r.ticks = run_state, ticks
    return r


def _registry(*records: SessionRecord, max_fast_runs: int = 1) -> SessionRegistry:
    reg = SessionRegistry(pool=None, idle_timeout_s=600, limiter=None, max_fast_runs=max_fast_runs)  # type: ignore[arg-type]
    for r in records:
        reg._records[r.session_id] = r
    return reg


def test_allowed_when_idle_with_a_list() -> None:
    me = _record("me")
    check_can_optimize(_registry(me), me, Settings())


@pytest.mark.parametrize("state", ["running_live", "running_fast", "waiting_decision", "paused", "finished", "failed"])
def test_409_when_not_idle(state: str) -> None:
    me = _record("me", run_state=state)
    with pytest.raises(OptimizeNotAllowed, match="idle"):
        check_can_optimize(_registry(me), me, Settings())


def test_409_after_advancing_and_without_a_list() -> None:
    me = _record("me", ticks=500)
    with pytest.raises(OptimizeNotAllowed, match="reset it first"):
        check_can_optimize(_registry(me), me, Settings())
    me = _record("me", products=None)
    with pytest.raises(OptimizeNotAllowed, match="needs a product list"):
        check_can_optimize(_registry(me), me, Settings())


def test_409_with_live_agent_sessions_unless_configured() -> None:
    me = _record("me")
    live = _record("live", rule=4, strategy="agent", run_state="running_live")
    with pytest.raises(OptimizeNotAllowed, match="live simulations with the agent") as exc:
        check_can_optimize(_registry(me, live), me, Settings())
    assert exc.value.status_code == 409
    check_can_optimize(_registry(me, live), me, Settings(optimize_block_when_live_agent=False))
    # live with b1b, or the agent paused / fast: not blocked
    for other in (_record("x", rule=4, strategy="b1b", run_state="running_live"),
                  _record("x", rule=4, strategy="agent", run_state="paused")):
        check_can_optimize(_registry(me, other), me, Settings())


def test_422_too_many_products() -> None:
    me = _record("me", products=[{"type": "A", "priority": 80}] * 51)
    with pytest.raises(OptimizeTooManyProducts) as exc:
        check_can_optimize(_registry(me), me, Settings())
    assert exc.value.status_code == 422
    check_can_optimize(_registry(_record("me", products=[{"type": "A", "priority": 80}] * 50)),
                       _record("me", products=[{"type": "A", "priority": 80}] * 50), Settings())
    small = _record("me")
    with pytest.raises(OptimizeTooManyProducts):
        check_can_optimize(_registry(small), small, Settings(optimize_max_products=3))


def test_503_when_the_fast_quota_is_full() -> None:
    me = _record("me")
    fast = _record("fast", run_state="running_fast")
    with pytest.raises(FastRunLimit, match="another fast simulation or optimization") as exc:
        check_can_optimize(_registry(me, fast), me, Settings())
    assert exc.value.status_code == 503
    check_can_optimize(_registry(me, fast, max_fast_runs=2), me, Settings())

    class _Busy:
        active = True
        status = "running"

    other = _record("other")
    other.optimizer = _Busy()  # an optimization in progress counts as a fast run
    reg = _registry(me, other)
    with pytest.raises(FastRunLimit):
        check_can_optimize(reg, me, Settings())
    assert reg.fast_slots_in_use(me) == 1 and reg.fast_slots_in_use(other) == 0


def test_settings_from_env() -> None:
    s = Settings.from_env({})
    assert (s.optimize_rounds, s.optimize_max_products, s.optimize_block_when_live_agent,
            s.optimize_max_wait_s, s.optimize_ai_timeout_s) == (2, 50, True, 300.0, 90.0)
    s = Settings.from_env({"ACLOPI_OPTIMIZE_ROUNDS": "3", "ACLOPI_OPTIMIZE_MAX_PRODUCTS": "20",
                           "ACLOPI_OPTIMIZE_BLOCK_WHEN_LIVE_AGENT": "0", "ACLOPI_OPTIMIZE_MAX_WAIT_S": "60"})
    assert (s.optimize_rounds, s.optimize_max_products, s.optimize_block_when_live_agent,
            s.optimize_max_wait_s) == (3, 20, False, 60.0)


def test_mock_orders_are_new() -> None:
    evaluated = [{"order": [0, 1, 2], "makespan_ticks": 10}, {"order": [2, 1, 0], "makespan_ticks": 9}]
    out = mock_orders(3, evaluated)
    assert len(out) == 2 and all(sorted(o) == [0, 1, 2] and o not in ([0, 1, 2], [2, 1, 0]) for o in out)
    assert out[0] != out[1]


@pytest.fixture()
def http(tmp_path: Path) -> Any:
    app = create_app(Settings(port=0, work_dir=tmp_path), pool_factory=lambda s: None, on_fatal=lambda e: None)
    return TestClient(app)


def test_request_validation(http: TestClient) -> None:
    # a single mode: no body, an empty one, or an old client's "mode" are all accepted (here the platform is
    # not started, so they get 503, never 422)
    for kwargs in ({}, {"json": {}}, {"json": {"mode": "quick"}}, {"json": {"mode": "anything"}}):
        assert http.post("/sessions/x/optimize-order", **kwargs).status_code == 503, kwargs
    assert http.post("/sessions/x/apply-order", json={"candidate": -1}).status_code == 422


def test_old_runs_with_a_mode_still_read() -> None:
    from aclopi.api.models import RunRecord

    old = {"run_id": "r", "session_id": "s", "created_at": 0.0, "finished_at": 1.0, "status": "finished", "rule": 3,
           "seed": 1, "seed_source": "user", "horizon_ticks": 100, "kpis": {},
           "optimization": {"optimized": True, "mode": "quick", "order": [1, 0], "origin": "heuristic"}}
    run = RunRecord(**old).model_dump()
    assert run["optimization"]["mode"] == "quick" and run["optimization"]["order"] == [1, 0]
    new = {**old, "optimization": {"optimized": True, "order": [1, 0], "origin": "heuristic"}}
    assert "mode" not in RunRecord(**new).model_dump()["optimization"]


def test_agent_kind_from_the_url_and_compose_stops_everything() -> None:
    """The kind shown in /health comes from the configured URL; the real agent never restarts on its own and
    the down scripts include every profile (docs/deploy-local.md, "The profile trap")."""
    import yaml

    from aclopi.api.agent import AgentClient, agent_kind

    assert [agent_kind(u) for u in ("http://agent-mock:8100", "http://agent:8100/", "http://127.0.0.1:8100", None)] == \
        ["mock", "real", "other", None]
    info = AgentClient("http://agent:8100", "secret").info()
    assert info["kind"] == "real" and info["url"] == "http://agent:8100" and "secret" not in str(info)
    root = Path(__file__).resolve().parents[1]
    compose = yaml.safe_load((root / "docker-compose.yml").read_text(encoding="utf-8"))
    assert compose["services"]["agent"]["profiles"] == ["agent"] and compose["services"]["agent"]["restart"] == "no"
    # the real agent is the platform's default; the mock only starts with its own profile (automatic tests)
    assert compose["services"]["agent-mock"]["profiles"] == ["mock"]
    assert "agent:8100" in compose["services"]["platform"]["environment"]["ACLOPI_AGENT_URL"]
    assert '[string]$Agent = "real"' in (root / "docker" / "up.ps1").read_text(encoding="utf-8")
    for script in ("down.ps1", "down.sh"):
        assert '--profile "*" down' in (root / "docker" / script).read_text(encoding="utf-8"), script
