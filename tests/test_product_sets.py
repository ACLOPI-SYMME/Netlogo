"""Product sets and the optional seed (L5.6) through the API."""

from __future__ import annotations

import time
from typing import Any

import httpx
import pytest

from aclopi.sim import SimulationSession
from apiserver import ApiServer, start_server, wait_session_workers_free
from test_live import Watcher

FIVE = [{"type": "E", "priority": 70}, {"type": "A", "priority": 90}, {"type": "T", "priority": 60},
        {"type": "A", "priority": 100}, {"type": "L", "priority": 80}]


@pytest.fixture(scope="module")
def api(tmp_path_factory: pytest.TempPathFactory) -> Any:
    server = start_server(tmp_path_factory.mktemp("sets"), 2, 1, warm=False, idle_s=600)
    yield server
    server.stop()


@pytest.fixture()
def client(api: ApiServer) -> Any:
    wait_session_workers_free(api.url)
    with httpx.Client(base_url=api.url, timeout=120) as c:
        yield c


def _csv(c: httpx.Client, text: str, bom: bool = False) -> httpx.Response:
    data = ("﻿" + text if bom else text).encode("utf-8")
    return c.post("/product-sets/parse-csv", files={"file": ("set.csv", data, "text/csv")})


def test_set_validation(client: httpx.Client) -> None:
    for products in ([{"type": "X", "priority": 80}], [{"type": "A", "priority": 59}],
                     [{"type": "A", "priority": 101}], [], [{"type": "A"}] * 1001):
        assert client.post("/product-sets", json={"name": "bad", "products": products}).status_code == 422
    r = client.post("/product-sets", json={"name": "ok", "products": [{"type": "a"}, {"type": "B", "priority": 61}]})
    assert r.status_code == 201
    body = r.json()
    assert body["products"] == [{"type": "A", "priority": 80}, {"type": "B", "priority": 61}]
    assert body["total"] == 2 and body["counts"]["A"] == 1 and len(body["hash"]) == 64
    assert client.delete(f"/product-sets/{body['id']}").status_code == 204
    assert client.get(f"/product-sets/{body['id']}").status_code == 404


def test_csv_parsing(client: httpx.Client) -> None:
    comma = _csv(client, "type,priority\nA,70\ne,\nT,100\n")
    assert comma.status_code == 200, comma.text
    assert comma.json()["products"] == [{"type": "A", "priority": 70}, {"type": "E", "priority": 80},
                                        {"type": "T", "priority": 100}]
    semicolon = _csv(client, "Type;Priority\r\nI;61\r\nP;99\r\n", bom=True)
    assert semicolon.status_code == 200 and semicolon.json()["total"] == 2
    only_type = _csv(client, "type\nL\nB\n")
    assert only_type.json()["products"] == [{"type": "L", "priority": 80}, {"type": "B", "priority": 80}]
    bad = _csv(client, "type,priority\nA,80\nZ,80\nB,80\nE,80\nI,80\nA,200\n")
    assert bad.status_code == 422
    assert [(e["line"]) for e in bad.json()["errors"]] == [3, 7]


def test_csv_round_trip(client: httpx.Client) -> None:
    created = client.post("/product-sets", json={"name": "five", "products": FIVE}).json()
    exported = client.get(f"/product-sets/{created['id']}/csv")
    assert exported.status_code == 200 and exported.text.startswith("PO,Item ID,#,Type,Priority,DueDate\n")
    parsed = _csv(client, exported.text).json()
    assert parsed["products"] == FIVE and parsed["hash"] == created["hash"]
    client.delete(f"/product-sets/{created['id']}")


def test_generate_from_seed(client: httpx.Client) -> None:
    given = client.post("/product-sets/generate", json={"seed": 42, "count": 30}).json()
    assert given["seed"] == 42 and given["seed_source"] == "user" and given["total"] == 30
    with SimulationSession() as s:
        s.setup(seed=1, rule=3)
        expected = s.product_sequence(42, 30)
    assert [(p["type"], p["priority"]) for p in given["products"]] == expected
    drawn = client.post("/product-sets/generate", json={"count": 5}).json()
    assert drawn["seed_source"] == "random" and -2 ** 31 <= drawn["seed"] < 2 ** 31


def test_session_with_five_products(api: ApiServer, client: httpx.Client) -> None:
    saved = client.post("/product-sets", json={"name": "five", "products": FIVE}).json()
    r = client.post("/sessions", json={"seed": 7, "rule": 3, "horizon_ticks": 60000, "product_set_id": saved["id"]})
    assert r.status_code == 201, r.text
    info = r.json()
    sid = info["session_id"]
    assert info["products_total"] == 5 and info["products_hash"] == saved["hash"] and info["product_set_id"] == saved["id"]
    # editing the set afterwards does not change the session (it keeps a copy)
    client.put(f"/product-sets/{saved['id']}", json={"name": "changed", "products": [{"type": "B"}]})
    w = Watcher(api, sid)
    client.post(f"/sessions/{sid}/run", json={"mode": "fast"}).raise_for_status()
    finished = w.wait_for("finished", timeout_s=300)[0]
    assert finished["reason"] == "all_products_done"
    kpis = finished["kpis"]
    assert kpis["all_done"] is True and kpis["products_total"] == 5 and kpis["finished"] == 5 and kpis["created"] == 5
    assert kpis["makespan_time"] > 0 and kpis["makespan_ticks"] == round(kpis["makespan_time"] / 0.31)
    seen: dict[int, str] = {}
    for _, m in w.messages:
        for p in (m.get("state") or {}).get("products", []):
            seen.setdefault(p["id"], p["type"])
    assert [seen[k] for k in sorted(seen)] == [p["type"] for p in FIVE]  # those 5, in that order
    info = client.get(f"/sessions/{sid}").json()
    assert info["run_state"] == "finished" and info["run_reason"] == "all_products_done"
    assert info["products_hash"] == saved["hash"]
    w.close()
    client.delete(f"/sessions/{sid}")
    client.delete(f"/product-sets/{saved['id']}")


def test_session_without_set_behaves_as_before(client: httpx.Client) -> None:
    r = client.post("/sessions", json={"seed": 42, "rule": 3, "horizon_ticks": 2000})
    sid = r.json()["session_id"]
    assert r.json()["products_total"] is None and r.json()["seed_source"] == "user"
    client.post(f"/sessions/{sid}/step", params={"n": 2000}).raise_for_status()
    kpis = client.get(f"/sessions/{sid}/kpis").json()
    with SimulationSession() as s:
        s.setup(seed=42, rule=3, horizon_ticks=2000)
        s.run_to_end()
        assert kpis == s.kpis().as_dict()
    client.delete(f"/sessions/{sid}")


def test_optional_seed(client: httpx.Client) -> None:
    r = client.post("/sessions", json={"rule": 3, "horizon_ticks": 500})
    assert r.status_code == 201
    info = r.json()
    assert info["seed_source"] == "random" and -2 ** 31 <= info["parameters"]["seed"] < 2 ** 31
    client.delete(f"/sessions/{info['session_id']}")
    for seed in (2 ** 31, -2 ** 31 - 1, 1.5, "abc"):
        assert client.post("/sessions", json={"seed": seed, "rule": 3}).status_code == 422
    kpis = []
    for _ in range(2):
        sid = client.post("/sessions", json={"seed": 99, "rule": 3, "horizon_ticks": 1500, "products": FIVE}).json()["session_id"]
        client.post(f"/sessions/{sid}/step", params={"n": 1500}).raise_for_status()
        kpis.append(client.get(f"/sessions/{sid}/kpis").json())
        client.delete(f"/sessions/{sid}")
    assert kpis[0] == kpis[1] and kpis[0]["products_total"] == 5
    assert client.post("/sessions", json={"seed": 1, "rule": 3, "products": FIVE,
                                          "product_set_id": "x"}).status_code == 422
