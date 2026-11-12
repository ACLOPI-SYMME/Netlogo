"""Optimize order end to end (docs/optimize-order.md): the API with real workers and the mock agent's
POST /sequence/propose (no delay unless a test sets one), in threads of this process. Short lists
(4 products) so that each simulation takes a few seconds."""

from __future__ import annotations

import json
import threading
import time
from typing import Any

import httpx
import pytest
from websockets.sync.client import connect

from aclopi.agent_mock import MockConfig
from aclopi.api.optimize import AI_DOWN
from apiserver import ApiServer, free_port, wait_session_workers_free
from test_agent_decisions import MockServer

TOKEN = "test-token"
LIST = [{"type": t, "priority": 80} for t in "IAEB"]  # largest_first: A, B, E, I -> [1, 3, 2, 0]
AI_TIMEOUT_S = 3.0


@pytest.fixture(scope="module")
def stack(tmp_path_factory: pytest.TempPathFactory) -> Any:
    from aclopi.api import Settings

    api_port = free_port()
    mock = MockServer(MockConfig(platform_url=f"http://127.0.0.1:{api_port}", token=TOKEN))
    settings = Settings(host="127.0.0.1", port=api_port, n_session_workers=2, n_whatif_workers=1,
                        session_idle_timeout_s=600, work_dir=tmp_path_factory.mktemp("optimize"),
                        agent_url=mock.url, agent_token=TOKEN, agent_health_interval_s=0.5,
                        optimize_ai_timeout_s=AI_TIMEOUT_S, optimize_max_wait_s=20)
    api = ApiServer(settings, warm=False)
    api.start()
    yield api, mock
    api.stop()
    mock.stop()


@pytest.fixture()
def client(stack: Any) -> Any:
    api, mock = stack
    cfg = mock.config
    cfg.down, cfg.sequence_delay_s, cfg.sequence_busy = "", 0.0, 0
    mock.app.state.sequence_calls = 0
    mock.app.state.sequence_requests.clear()
    _wait_agent(api, "ok")
    wait_session_workers_free(api.url)
    with httpx.Client(base_url=api.url, timeout=120, headers={"Authorization": f"Bearer {TOKEN}"}) as c:
        yield c


def _wait_agent(api: ApiServer, status: str, timeout_s: float = 20) -> None:
    deadline = time.monotonic() + timeout_s
    while api.runtime.agent.status != status:
        assert time.monotonic() < deadline, f"agent status {api.runtime.agent.status!r}, expected {status!r}"
        time.sleep(0.1)


def _session(c: httpx.Client, rule: int = 3, seed: int = 42, horizon: int = 20000, products: Any = LIST) -> str:
    body: dict[str, Any] = {"seed": seed, "rule": rule, "horizon_ticks": horizon, "products": products}
    r = c.post("/sessions", json=body)
    assert r.status_code == 201, r.text
    return r.json()["session_id"]


def _optimize(c: httpx.Client, sid: str, mode: str) -> dict[str, Any]:
    r = c.post(f"/sessions/{sid}/optimize-order", json={"mode": mode})
    assert r.status_code == 202, r.text
    return r.json()


def _wait_opt(c: httpx.Client, sid: str, until: Any = None, timeout_s: float = 240) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_s
    seen: set[str] = set()
    while True:
        o = c.get(f"/sessions/{sid}/optimize-order").json()
        seen.add(o["status"])
        o["seen"] = seen
        if (until(o) if until else o["status"] in ("done", "cancelled", "failed")):
            return o
        assert time.monotonic() < deadline, o
        time.sleep(0.1)


def _run_fast(c: httpx.Client, sid: str) -> dict[str, Any]:
    c.post(f"/sessions/{sid}/run", json={"mode": "fast"}).raise_for_status()
    deadline = time.monotonic() + 120
    while (info := c.get(f"/sessions/{sid}").json())["run_state"] not in ("finished", "failed"):
        assert time.monotonic() < deadline, {k: info[k] for k in ("run_state", "ticks", "status", "optimize_status",
                                                                   "worker_slot")}
        time.sleep(0.2)
    return info


class Collector:
    def __init__(self, api: ApiServer, sid: str) -> None:
        self._cm = connect(f"{api.ws_url}/ws/sessions/{sid}", open_timeout=30)
        self.ws = self._cm.__enter__()
        self.messages: list[dict[str, Any]] = []
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self) -> None:
        try:
            for text in self.ws:
                self.messages.append(json.loads(text))
        except Exception:  # noqa: BLE001
            pass

    def types(self) -> list[str]:
        return [m["type"] for m in self.messages]

    def close(self) -> None:
        self._cm.__exit__(None, None, None)


def test_quick_round0_without_ai_then_one_round(stack: Any, client: httpx.Client) -> None:
    api, mock = stack
    sid = _session(client)
    o = _optimize(client, sid, "quick")
    assert o["status"] == "running" and o["rounds"] == 1 and o["strategy"] == "rule3" and o["reasoning_effort"] == "none"
    o = _wait_opt(client, sid)
    assert o["status"] == "done" and o["warning"] is None, o
    # round 0 had no AI call: the only call came with the original and the heuristic already simulated
    reqs = mock.app.state.sequence_requests
    assert len(reqs) == 1 and [e["order"] for e in reqs[0]["evaluated"]] == [[0, 1, 2, 3], [1, 3, 2, 0]]
    assert reqs[0]["reasoning"] == "none" and reqs[0]["strategy"] == "rule3" and reqs[0]["mode"] == "Deterministic"
    assert all(e["details"] is not None for e in reqs[0]["evaluated"])
    labels = [e["label"] for e in o["evaluated"]]
    assert labels == ["Original", "Heuristic", "AI round 1 · 1", "AI round 1 · 2"]
    assert [e["origin"] for e in o["evaluated"]] == ["original", "heuristic", "ai", "ai"]
    assert all(e["all_done"] and e["makespan_ticks"] for e in o["evaluated"])
    assert o["evaluated"][0]["saving_time"] == 0.0 and o["evaluated"][2]["analysis"].startswith("mock analysis")
    best = min(o["evaluated"], key=lambda e: (e["makespan_ticks"], e["index"]))
    assert o["best"] == best["index"] and o["progress_pct"] == 100.0
    info = client.get(f"/sessions/{sid}").json()
    assert info["optimize_status"] == "done" and info["optimization"] is None and info["ticks"] == 0
    client.delete(f"/sessions/{sid}")


def test_full_two_rounds_rule4_with_websocket(stack: Any, client: httpx.Client) -> None:
    api, mock = stack
    sid = _session(client, rule=4)
    ws = Collector(api, sid)
    o = _optimize(client, sid, "full")
    assert o["rounds"] == 2 and o["strategy"] == "b1b" and o["reasoning_effort"] == "medium"
    # while it optimizes, the session refuses other operations
    assert client.post(f"/sessions/{sid}/run", json={"mode": "fast"}).status_code == 409
    o = _wait_opt(client, sid)
    assert o["status"] == "done", o
    assert [r["round"] for r in o["rounds_info"]] == [1, 2] and len(o["evaluated"]) == 6
    reqs = mock.app.state.sequence_requests
    assert [len(r["evaluated"]) for r in reqs] == [2, 4] and all(r["reasoning"] == "medium" for r in reqs)
    assert len({tuple(e["order"]) for e in o["evaluated"]}) == 6
    deadline = time.monotonic() + 10
    while "optimize_result" not in ws.types():
        assert time.monotonic() < deadline, ws.types()
        time.sleep(0.1)
    types = ws.types()
    assert types.count("optimize_best") == 6 and "optimize_progress" in types and "optimize_failed" not in types
    progress = [m for m in ws.messages if m["type"] == "optimize_progress"]
    assert {m["phase"] for m in progress} >= {"simulating", "waiting_ai"}
    result = next(m for m in ws.messages if m["type"] == "optimize_result")["result"]
    assert result["status"] == "done" and result["best"] == o["best"]
    ws.close()
    client.delete(f"/sessions/{sid}")


def test_use_this_midway_cuts_and_applies(stack: Any, client: httpx.Client) -> None:
    api, mock = stack
    mock.config.sequence_delay_s = 2.5
    sid = _session(client)
    _optimize(client, sid, "full")
    o = _wait_opt(client, sid, until=lambda o: o["status"] == "waiting_ai")
    assert len(o["evaluated"]) == 2
    r = client.post(f"/sessions/{sid}/apply-order", json={"candidate": 1})
    assert r.status_code == 200, r.text
    body = r.json()
    o = body["optimization"]
    assert o["status"] == "done" and o["applied"] == 1 and o["stopped_early"] and len(o["evaluated"]) == 2
    assert [p["type"] for p in body["products"]] == list("ABEI")  # the heuristic's order
    applied = body["session"]["optimization"]
    assert applied["optimized"] and applied["mode"] == "full" and applied["origin"] == "heuristic"
    assert applied["order"] == [1, 3, 2, 0] and applied["estimated_makespan_ticks"] == o["evaluated"][1]["makespan_ticks"]
    assert body["session"]["ticks"] == 0 and body["session"]["run_state"] == "idle"
    assert mock.app.state.sequence_calls <= 1
    # the run uses the new entry order: types of the products by creation order (who), from platform-state
    # read every 500 ticks until the 4 have entered
    seen: dict[int, str] = {}
    for _ in range(40):
        client.post(f"/sessions/{sid}/step", params={"n": 500}).raise_for_status()
        seen.update({p["id"]: p["type"] for p in client.get(f"/sessions/{sid}/state").json()["products"]})
        if len(seen) == 4:
            break
    assert [seen[k] for k in sorted(seen)] == list("ABEI"), seen
    info = _run_fast(client, sid)
    assert info["run_state"] == "finished"
    kpis = client.get(f"/sessions/{sid}/kpis").json()
    run = client.get(f"/runs/{client.get(f'/sessions/{sid}').json()['last_run_id']}").json()
    assert run["optimization"]["estimated_makespan_ticks"] == applied["estimated_makespan_ticks"]
    print(f"\nestimated {applied['estimated_makespan_ticks']} (Deterministic) vs real {kpis['makespan_ticks']} (Stochastic)")
    client.delete(f"/sessions/{sid}")


def test_429_waits_its_turn_and_goes_on(stack: Any, client: httpx.Client) -> None:
    api, mock = stack
    mock.config.sequence_busy, mock.config.sequence_retry_after_s = 1, 2
    sid = _session(client)
    _optimize(client, sid, "quick")
    o = _wait_opt(client, sid)
    assert o["status"] == "done" and "waiting_turn" in o["seen"], o
    assert o["waited_s"] >= 1.5 and len(o["evaluated"]) == 4 and mock.app.state.sequence_calls == 2
    client.delete(f"/sessions/{sid}")


def test_ai_timeout_ends_with_what_was_evaluated(stack: Any, client: httpx.Client) -> None:
    api, mock = stack
    mock.config.sequence_delay_s = AI_TIMEOUT_S + 3
    sid = _session(client)
    _optimize(client, sid, "full")
    o = _wait_opt(client, sid)
    assert o["status"] == "done" and len(o["evaluated"]) == 2 and "did not answer" in o["warning"], o
    client.delete(f"/sessions/{sid}")


def test_agent_down_compares_original_and_heuristic(stack: Any, client: httpx.Client) -> None:
    api, mock = stack
    mock.config.down = "health"
    _wait_agent(api, "down")
    sid = _session(client)
    _optimize(client, sid, "quick")
    o = _wait_opt(client, sid)
    assert o["status"] == "done" and o["warning"] == AI_DOWN and [e["label"] for e in o["evaluated"]] == ["Original", "Heuristic"]
    assert mock.app.state.sequence_calls == 0
    client.delete(f"/sessions/{sid}")


def test_session_identical_after_optimizing_without_applying(stack: Any, client: httpx.Client) -> None:
    """3000-tick fast runs: optimized (not applied) and cancelled sessions give the KPIs of an untouched one."""
    api, mock = stack
    kpis = []
    for action in ("none", "optimize", "cancel"):
        sid = _session(client, seed=7, horizon=3000)
        if action != "none":
            mock.config.sequence_delay_s = 30.0 if action == "cancel" else 0.0
            _optimize(client, sid, "quick")
            if action == "cancel":
                _wait_opt(client, sid, until=lambda o: o["status"] == "waiting_ai")
                t0 = time.monotonic()
                r = client.post(f"/sessions/{sid}/optimize-order/cancel")
                assert r.status_code == 200 and r.json()["status"] == "cancelled" and time.monotonic() - t0 < 5
            o = _wait_opt(client, sid)
            assert o["status"] in ("done", "cancelled") and o["applied"] is None
        info = client.get(f"/sessions/{sid}").json()
        assert info["ticks"] == 0 and info["run_state"] == "idle" and info["optimization"] is None
        assert _run_fast(client, sid)["run_state"] == "finished"
        kpis.append(client.get(f"/sessions/{sid}/kpis").json())
        client.delete(f"/sessions/{sid}")
    assert kpis[0]["ticks"] == 3000 and kpis[1] == kpis[0] and kpis[2] == kpis[0]


def test_cancel_during_a_simulation(stack: Any, client: httpx.Client) -> None:
    api, mock = stack
    sid = _session(client, rule=4)
    _optimize(client, sid, "quick")
    _wait_opt(client, sid, until=lambda o: o["current"] is not None and o["current"]["ticks"] > 0)
    t0 = time.monotonic()
    r = client.post(f"/sessions/{sid}/optimize-order/cancel")
    assert r.status_code == 200 and r.json()["status"] == "cancelled", r.text
    assert time.monotonic() - t0 < 10
    assert client.post(f"/sessions/{sid}/optimize-order/cancel").status_code == 409
    client.delete(f"/sessions/{sid}")
