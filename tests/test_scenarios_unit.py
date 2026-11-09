"""Scenarios without NetLogo. aclopi.sim.scenarios (Línea A, experiments only): validation (defaults,
ranges, S1 partial/empty), the specs and the S3 calendar. The platform (scenarios not available,
docs/scenarios.md): POST /sessions with a scenario other than S0 -> 422 scenarios_unavailable,
no GET /scenarios, and the registry refuses any scenario other than S0."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import anyio
import pytest
from fastapi.testclient import TestClient

from aclopi.api import Settings, create_app
from aclopi.api.registry import SessionRegistry
from aclopi.sim.scenarios import list_scenarios, scenario_events, validate_params


# ----- validation -----

def test_defaults_are_filled_in() -> None:
    assert validate_params("S0", None) == {}
    assert validate_params("S1", None)["times"] == {"M2": 160, "M3": 180, "M4": 200, "M5": 220, "M6": 240, "M7": 260}
    assert validate_params("S2", {"factor": 2}) == {"machine": "M7", "factor": 2.0, "start_tick": 10000}
    assert validate_params("S3", {}) == {"interval_ticks": 5000, "repair_ut": 300,
                                         "machines": ["M2", "M3", "M4", "M5", "M6", "M7"]}


@pytest.mark.parametrize("scenario_id, params, message", [
    ("S9", None, "unknown scenario"),
    ("S2", {"factor": 0.5}, "factor: must be between 1 and 5"),
    ("S2", {"machine": "M1"}, "machine: must be one of"),
    ("S2", {"start_tick": 1.5}, "start_tick: must be an integer"),
    ("S2", {"speed": 3}, "unknown parameter"),
    ("S3", {"machines": []}, "machines: must be a non-empty list"),
    ("S3", {"interval_ticks": 100}, "interval_ticks: must be between 500"),
    ("S1", {"times": {"M3": 20}}, "times.M3: must be between 50 and 1000"),
    ("S1", {"times": {"M1": 200}}, "times: must be one of"),
])
def test_invalid_params(scenario_id: str, params: dict[str, Any] | None, message: str) -> None:
    with pytest.raises(ValueError, match=message.replace(".", r"\.")):
        validate_params(scenario_id, params)


def test_s1_partial_and_empty_are_valid() -> None:
    assert validate_params("S1", {"times": {"M4": 300}}) == {"times": {"M4": 300.0}}
    assert validate_params("S1", {"times": {}}) == {"times": {}}
    assert scenario_events("S1", {"times": {}}, 1, 0, 1000) == []  # like S0
    events = scenario_events("S1", {"times": {"M4": 300, "M2": 120}}, 1, 0, 1000)
    assert [(e.tick, e.kind, e.machine, e.value) for e in events] == [(0, "set_times", "M2", 120.0),
                                                                        (0, "set_times", "M4", 300.0)]


def test_s3_calendar_is_deterministic_and_range_independent() -> None:
    params = {"interval_ticks": 500, "machines": ["M3", "M5"]}
    full = scenario_events("S3", params, 7, 0, 5000)
    assert [e.tick for e in full] == list(range(500, 5000, 500))
    assert full == scenario_events("S3", params, 7, 0, 5000)
    assert scenario_events("S3", params, 7, 1500, 3000) == [e for e in full if 1500 <= e.tick < 3000]
    assert {e.machine for e in full} <= {"M3", "M5"} and full[0].label == f"Falla en {full[0].machine}: +300 u.t."
    assert [e.machine for e in scenario_events("S3", params, 8, 0, 5000)] != [e.machine for e in full]


def test_scenario_specs() -> None:
    specs = {s.id: s for s in list_scenarios()}
    assert list(specs) == ["S0", "S1", "S2", "S3"] and specs["S2"].name == "Degradación"
    assert {p.name: (p.type, p.default, p.min, p.max) for p in specs["S2"].params} == {
        "machine": ("machine", "M7", None, None), "factor": ("float", 1.75, 1.0, 5.0),
        "start_tick": ("int", 10000, 0, 1_000_000)}
    assert [p.type for p in specs["S3"].params] == ["int", "int", "machine_list"]
    assert specs["S1"].params[0].type == "machine_times"


# ----- platform: scenarios not available (the platform is not started: the check answers before) -----

@pytest.fixture()
def http(tmp_path: Path) -> Any:
    app = create_app(Settings(port=0, work_dir=tmp_path), pool_factory=lambda s: None, on_fatal=lambda e: None)
    return TestClient(app)  # no lifespan: phase "starting"


@pytest.mark.parametrize("scenario", [{"id": "S1"}, {"id": "S2", "params": {"start_tick": 1000}},
                                      {"id": "S3", "params": {"interval_ticks": 1000}}, {"id": "nope"},
                                      {"id": "S0", "params": {"x": 1}}])
def test_post_sessions_with_a_scenario_is_422(http: TestClient, scenario: dict[str, Any]) -> None:
    r = http.post("/sessions", json={"rule": 3, "scenario": scenario})
    assert r.status_code == 422, r.text
    assert r.json()["code"] == "scenarios_unavailable" and r.json()["detail"] == "los escenarios no están disponibles"


def test_post_sessions_s0_or_no_scenario_passes(http: TestClient) -> None:
    # passes the check and only then meets the platform starting
    for body in ({"rule": 3}, {"rule": 3, "scenario": {"id": "S0"}}, {"rule": 4, "scenario": {"id": "S0", "params": {}}}):
        assert http.post("/sessions", json=body).status_code == 503


def test_no_get_scenarios(http: TestClient) -> None:
    assert http.get("/scenarios").status_code == 404
    assert "/scenarios" not in http.get("/openapi.json").json()["paths"]


def test_registry_refuses_scenarios() -> None:
    registry = SessionRegistry(pool=None, idle_timeout_s=600, limiter=anyio.CapacityLimiter(1))  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="only S0"):
        asyncio.run(registry.create(1, 3, "Stochastic", 1000, scenario={"id": "S2", "params": {"start_tick": 0}}))


# ----- strategy (not a user option: rule 4 is the agent) -----

def test_rule_4_without_strategy_is_agent() -> None:
    from aclopi.api.models import SessionCreate
    assert SessionCreate(rule=4).strategy == "agent"
    assert [SessionCreate(rule=4, strategy=s).strategy for s in ("b1", "b1b", "none", "agent")] == ["b1", "b1b", "none", "agent"]
    assert SessionCreate(rule=3).strategy is None
