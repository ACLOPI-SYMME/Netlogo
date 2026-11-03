"""Persistent results (L5.7): the in-memory store, runs saved by the API, and DynamoDB Local
(skipped when ACLOPI_DYNAMODB_ENDPOINT is not set or not reachable)."""

from __future__ import annotations

import os
import time
import uuid
from typing import Any

import httpx
import pytest

from aclopi.api.results import DynamoProductSetStore, DynamoResultsStore, InMemoryResultsStore
from apiserver import ApiServer, start_server, wait_session_workers_free


def _run(i: int, **extra: Any) -> dict[str, Any]:
    return {"run_id": f"r{i}", "session_id": "s", "created_at": 1000.0 + i, "finished_at": 1001.0 + i,
            "status": "finished", "reason": "horizon", "rule": 3, "strategy": None, "seed": 42, "seed_source": "user",
            "horizon_ticks": 1000, "mode": "fast", "kpis": {"finished": i, "mean_flow_time": 1.5 * i}, **extra}


def _exercise_store(store: Any) -> None:
    for i in range(5):
        store.save_run(_run(i, seed=42 if i < 3 else 7), [{"tick": 10 * i, "product": 200, "seq_op": 1, "late": False}])
    assert store.get_run("r2")["kpis"] == {"finished": 2, "mean_flow_time": 3.0}
    assert store.get_run("nope") is None
    rows, cursor = store.list_runs({"seed": 42}, 2, None)
    assert [r["run_id"] for r in rows] == ["r2", "r1"]  # newest first
    seen = [r["run_id"] for r in rows]
    while cursor:
        more, cursor = store.list_runs({"seed": 42}, 2, cursor)
        seen += [r["run_id"] for r in more]
    assert sorted(seen) == ["r0", "r1", "r2"]
    assert [r["run_id"] for r in store.list_runs({"seed": 7}, 10, None)[0]] == ["r4", "r3"]
    assert store.get_decisions("r3") == [{"tick": 30, "product": 200, "seq_op": 1, "late": False, "seq": 0,
                                          **({"run_id": "r3"} if isinstance(store, DynamoResultsStore) else {})}]


def test_in_memory_store() -> None:
    _exercise_store(InMemoryResultsStore())


def _dynamo_endpoint() -> str | None:
    endpoint = os.environ.get("ACLOPI_DYNAMODB_ENDPOINT", "").strip()
    if not endpoint:
        return None
    try:
        httpx.get(endpoint, timeout=2)
    except httpx.HTTPError:
        return None
    return endpoint


def test_dynamodb_local() -> None:
    endpoint = _dynamo_endpoint()
    if endpoint is None:
        pytest.skip("DynamoDB Local not available (ACLOPI_DYNAMODB_ENDPOINT)")
    os.environ.setdefault("AWS_ACCESS_KEY_ID", "local")
    os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "local")
    prefix = f"test_{uuid.uuid4().hex[:8]}_"
    _exercise_store(DynamoResultsStore(endpoint, prefix, create_tables=True))
    sets = DynamoProductSetStore(endpoint, prefix)
    created = sets.create("a", [{"type": "A", "priority": 80}, {"type": "T", "priority": 61}])
    assert sets.get(created["id"])["products"] == [{"type": "A", "priority": 80}, {"type": "T", "priority": 61}]
    assert [s["id"] for s in sets.list()] == [created["id"]]
    assert sets.update(created["id"], "b", [{"type": "E", "priority": 90}])["total"] == 1
    assert sets.delete(created["id"]) and sets.get(created["id"]) is None


# ----- runs saved by the API -----

@pytest.fixture(scope="module")
def api(tmp_path_factory: pytest.TempPathFactory) -> Any:
    server = start_server(tmp_path_factory.mktemp("results"), 2, 1, warm=False, idle_s=600)
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


def test_runs_are_saved(client: httpx.Client) -> None:
    seed = 424242
    sid = client.post("/sessions", json={"seed": seed, "rule": 3, "horizon_ticks": 1500,
                                         "products": [{"type": "A"}, {"type": "E", "priority": 70}]}).json()["session_id"]
    client.post(f"/sessions/{sid}/run", json={"mode": "fast"}).raise_for_status()
    info = _wait(client, sid, "finished")
    deadline = time.monotonic() + 10
    while not client.get("/runs", params={"seed": seed}).json()["runs"]:
        assert time.monotonic() < deadline
        time.sleep(0.2)
    run = client.get("/runs", params={"seed": seed}).json()["runs"][0]
    assert run["run_id"] == client.get(f"/sessions/{sid}").json()["last_run_id"]
    assert run["status"] == "finished" and run["mode"] == "fast" and run["seed_source"] == "user"
    assert run["kpis"]["ticks"] == info["ticks"] and run["kpis"]["products_total"] == 2
    assert run["products"] == [{"type": "A", "priority": 80}, {"type": "E", "priority": 70}]
    assert client.get(f"/runs/{run['run_id']}").json()["run_id"] == run["run_id"]
    assert client.get(f"/runs/{run['run_id']}/decisions").json() == []
    # a run stopped by DELETE is saved as stopped
    client.post(f"/sessions/{sid}/reset").raise_for_status()
    client.post(f"/sessions/{sid}/run", json={"mode": "live", "speed": 1}).raise_for_status()
    time.sleep(1.0)
    client.delete(f"/sessions/{sid}")
    deadline = time.monotonic() + 10
    while len(client.get("/runs", params={"seed": seed}).json()["runs"]) < 2:
        assert time.monotonic() < deadline
        time.sleep(0.2)
    statuses = sorted((r["status"], r["reason"]) for r in client.get("/runs", params={"seed": seed}).json()["runs"])
    assert statuses == [("finished", "all_products_done"), ("stopped", "deleted")] or \
        statuses == [("finished", "horizon"), ("stopped", "deleted")]
    assert client.get("/runs/nope").status_code == 404
