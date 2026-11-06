"""Scenarios without NetLogo: validation (defaults, ranges, S1 partial/empty), the S3 calendar,
POST /sessions -> 422 invalid_scenario, GET /scenarios, and the registry (scenario event published
before the /decide request; summary saved with the run)."""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any

import anyio
import pytest
from fastapi.testclient import TestClient

from aclopi.api import Settings, create_app
from aclopi.api.hub import SessionHub
from aclopi.api.registry import SessionRecord, SessionRegistry
from aclopi.api.results import InMemoryResultsStore
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


# ----- HTTP (the platform is not started: validation answers before) -----

@pytest.fixture()
def http(tmp_path: Path) -> Any:
    app = create_app(Settings(port=0, work_dir=tmp_path), pool_factory=lambda s: None, on_fatal=lambda e: None)
    return TestClient(app)  # no lifespan: phase "starting"


def test_post_sessions_invalid_scenario_is_422(http: TestClient) -> None:
    r = http.post("/sessions", json={"rule": 3, "scenario": {"id": "S2", "params": {"factor": 9}}})
    assert r.status_code == 422 and r.json()["code"] == "invalid_scenario"
    assert r.json()["detail"].startswith("factor: must be between 1 and 5")
    r = http.post("/sessions", json={"rule": 3, "scenario": {"id": "S3", "params": {"machines": []}}})
    assert r.status_code == 422 and "machines" in r.json()["detail"]
    r = http.post("/sessions", json={"rule": 3, "scenario": {"id": "nope"}})
    assert r.status_code == 422 and "unknown scenario" in r.json()["detail"]
    # valid (S1 partial, S1 empty): passes validation and only then meets the platform starting
    for sc in ({"id": "S1", "params": {"times": {"M5": 400}}}, {"id": "S1", "params": {"times": {}}}, {"id": "S0"}):
        assert http.post("/sessions", json={"rule": 3, "scenario": sc}).status_code == 503


def test_get_scenarios(http: TestClient) -> None:
    body = http.get("/scenarios").json()
    assert [s["id"] for s in body] == [s.id for s in list_scenarios()] == ["S0", "S1", "S2", "S3"]
    s2 = next(s for s in body if s["id"] == "S2")
    assert s2["name"] == "Degradación"
    assert {p["name"]: (p["type"], p["default"], p["min"], p["max"]) for p in s2["params"]} == {
        "machine": ("machine", "M7", None, None), "factor": ("float", 1.75, 1.0, 5.0),
        "start_tick": ("int", 10000, 0, 1_000_000)}
    s3 = next(s for s in body if s["id"] == "S3")
    assert [p["type"] for p in s3["params"]] == ["int", "int", "machine_list"]
    assert next(s for s in body if s["id"] == "S1")["params"][0]["type"] == "machine_times"


# ----- registry -----

def _event(tick: int, applied: bool = True) -> dict[str, Any]:
    return {"type": "scenario", "tick": tick, "kind": "repair", "machine": "M4", "value": 300.0,
            "label": "Falla en M4: +300 u.t.", "applied": applied,
            "skip_reason": None if applied else "machine-idle", "before": None, "after": None}


def _registry() -> tuple[SessionRegistry, SessionRecord, list[str]]:
    registry = SessionRegistry(pool=None, idle_timeout_s=600, limiter=anyio.CapacityLimiter(1))  # type: ignore[arg-type]
    order: list[str] = []

    class Agent:
        available = True

        async def decide(self, payload: dict[str, Any]) -> bool:
            order.append("decide")
            return True

    registry.agent = Agent()
    registry.results = InMemoryResultsStore()
    now = time.time()
    record = SessionRecord("s1", {"seed": 7, "rule": 4, "modeling_type": "Stochastic", "horizon_ticks": 1000}, 0,
                           now, now, time.monotonic(), SessionHub("s1", 32), strategy="b1", agent=registry.agent,
                           scenario={"id": "S3", "params": {"interval_ticks": 500}})
    record.hub.publish = lambda message, raw=None: order.append(message["type"])  # type: ignore[method-assign]
    registry._records["s1"] = record
    return registry, record, order


def test_scenario_event_is_published_before_the_decide_request() -> None:
    registry, record, order = _registry()
    request = {"who": 300, "seq": 1, "operation": "O2", "origin": "M2", "tick": 499, "candidates": ["M3", "M4"]}

    async def main() -> None:
        registry.on_push("s1", "progress", {"tick": 500, "advanced": 500, "finished_products": 0, "events": [],
                                            "scenario_events": [_event(500)], "decision_requests": [request]})
        await asyncio.sleep(0.05)

    asyncio.run(main())
    assert order.index("scenario_event") < order.index("decide")
    assert record.events[-1]["type"] == "scenario" and record.scenario_events == [_event(500)]


def test_skipped_events_go_to_the_run_summary() -> None:
    registry, record, _ = _registry()
    record.run_started_at = time.time()
    registry.on_push("s1", "tick", {"tick": 500, "advanced": 3, "events": [], "scenario_events": [_event(500)]})
    registry.after_step(record, {"ticks": 1000, "advanced": 500, "finished": False,
                                 "scenario_events": [_event(1000, applied=False)]})
    assert record.info()["scenario_summary"] == {"applied": 1, "skipped": 1}
    registry.save_run(record, "finished", "horizon")  # no running loop: written at once
    rows, _ = registry.results.list_runs({"scenario_id": "S3"}, 10, None)
    assert len(rows) == 1 and registry.results.list_runs({"scenario_id": "S2"}, 10, None)[0] == []
    run = rows[0]
    assert run["scenario"] == {"id": "S3", "params": {"interval_ticks": 500}}
    assert run["scenario_summary"] == {"applied": 1, "skipped": 1}
    assert [(e["tick"], e["applied"], e["skip_reason"]) for e in run["scenario_events"]] == [
        (500, True, None), (1000, False, "machine-idle")]
