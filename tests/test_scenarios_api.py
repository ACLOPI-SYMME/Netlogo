"""Scenarios through the real platform (API + worker processes, stub of aclopi.sim.scenarios):
SessionInfo, WebSocket scenario_event and snapshot, runs saved with the scenario, the scenario
filter, and skipped events (the workers start with ACLOPI_SCENARIO_STUB_SKIP=1: repairs skipped)."""

from __future__ import annotations

import os
import time
from typing import Any

import httpx
import pytest

from apiserver import ApiServer, start_server, wait_session_workers_free
from test_live import Watcher


@pytest.fixture(scope="module")
def api(tmp_path_factory: pytest.TempPathFactory) -> Any:
    previous = os.environ.get("ACLOPI_SCENARIO_STUB_SKIP")
    os.environ["ACLOPI_SCENARIO_STUB_SKIP"] = "1"  # inherited by the worker processes started now
    try:
        server = start_server(tmp_path_factory.mktemp("scenarios"), 2, 1, warm=False, idle_s=600)
    finally:
        if previous is None:
            os.environ.pop("ACLOPI_SCENARIO_STUB_SKIP", None)
        else:
            os.environ["ACLOPI_SCENARIO_STUB_SKIP"] = previous
    yield server
    server.stop()


@pytest.fixture()
def client(api: ApiServer) -> Any:
    wait_session_workers_free(api.url)
    with httpx.Client(base_url=api.url, timeout=120) as c:
        yield c


def _wait(c: httpx.Client, sid: str, state: str) -> dict[str, Any]:
    deadline = time.monotonic() + 120
    while True:
        info = c.get(f"/sessions/{sid}").json()
        if info["run_state"] == state:
            return info
        assert time.monotonic() < deadline, info
        time.sleep(0.2)


def test_live_scenario_event_and_snapshot(api: ApiServer, client: httpx.Client) -> None:
    r = client.post("/sessions", json={"seed": 21, "rule": 3, "horizon_ticks": 600,
                                       "scenario": {"id": "S2", "params": {"start_tick": 300}}})
    assert r.status_code == 201, r.text
    info = r.json()
    assert info["scenario"] == {"id": "S2", "params": {"machine": "M7", "factor": 1.75, "start_tick": 300}}
    sid = info["session_id"]
    w = Watcher(api, sid)
    try:
        client.post(f"/sessions/{sid}/run", json={"mode": "live", "speed": 4}).raise_for_status()
        w.wait_for("finished", timeout_s=60)
        [msg] = w.of("scenario_event")
        assert msg["tick"] == 300 and msg["event"]["kind"] == "scale_times" and msg["event"]["applied"]
        kinds = [(m["type"], m.get("tick")) for _, m in w.messages]
        assert kinds.index(("scenario_event", 300)) < kinds.index(("tick", 300))  # before the block that ends there
    finally:
        w.close()
    assert client.get(f"/sessions/{sid}").json()["scenario_summary"] == {"applied": 1, "skipped": 0}
    late = Watcher(api, sid)  # a client that connects afterwards gets the events in the snapshot
    try:
        [snap] = late.of("snapshot")
        assert [e["tick"] for e in snap["scenario_events"]] == [300]
        assert snap["session"]["scenario"]["id"] == "S2"
        assert any(e.get("type") == "scenario" for e in snap["recent_events"])
    finally:
        late.close()
    client.delete(f"/sessions/{sid}")


def test_runs_keep_the_scenario_and_skipped_events(client: httpx.Client) -> None:
    assert client.post("/sessions", json={"rule": 3, "scenario": {"id": "S3", "params": {"machines": []}}}).status_code == 422
    seed = 515151
    sid = client.post("/sessions", json={"seed": seed, "rule": 3, "horizon_ticks": 1600,
                                         "scenario": {"id": "S3", "params": {"interval_ticks": 500}}}).json()["session_id"]
    client.post(f"/sessions/{sid}/run", json={"mode": "fast"}).raise_for_status()
    _wait(client, sid, "finished")
    deadline = time.monotonic() + 10
    while not client.get("/runs", params={"seed": seed, "scenario": "S3"}).json()["runs"]:
        assert time.monotonic() < deadline
        time.sleep(0.2)
    run = client.get("/runs", params={"seed": seed, "scenario": "S3"}).json()["runs"][0]
    assert run["scenario_id"] == "S3" and run["scenario"]["params"]["interval_ticks"] == 500
    assert run["scenario_summary"] == {"applied": 0, "skipped": 3}
    assert [(e["tick"], e["applied"], e["skip_reason"]) for e in run["scenario_events"]] == [
        (500, False, "machine-idle"), (1000, False, "machine-idle"), (1500, False, "machine-idle")]
    assert client.get("/runs", params={"seed": seed, "scenario": "S2"}).json()["runs"] == []
    client.delete(f"/sessions/{sid}")
