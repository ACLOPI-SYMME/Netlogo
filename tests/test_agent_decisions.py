"""Rule 4 decisions through the agent (L5.5): strategies, /decide -> next-machine, live and fast
runs, agent down. The API and the mock agent (aclopi.agent_mock) run in threads of this process."""

from __future__ import annotations

import threading
import time
from typing import Any

import httpx
import pytest
import uvicorn

from aclopi.agent_mock import MockConfig, create_mock_app
from aclopi.sim import SimulationSession
from aclopi.sim.decisions import clear_decisions, pending_decisions, run_until_decision
from apiserver import ApiServer, free_port, start_server, wait_session_workers_free
from test_live import Watcher

TOKEN = "test-token"


class MockServer:
    def __init__(self, config: MockConfig) -> None:
        self.port = free_port()
        self.app = create_mock_app(config)
        self.config = config
        self.server = uvicorn.Server(uvicorn.Config(self.app, host="127.0.0.1", port=self.port, log_config=None,
                                                   access_log=False, timeout_graceful_shutdown=1))
        self.thread = threading.Thread(target=self.server.run, daemon=True)
        self.thread.start()
        deadline = time.monotonic() + 30
        while not self.server.started:
            assert time.monotonic() < deadline
            time.sleep(0.05)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def stop(self) -> None:
        self.server.should_exit = True
        self.thread.join(10)


@pytest.fixture(scope="module")
def stack(tmp_path_factory: pytest.TempPathFactory) -> Any:
    api_port = free_port()
    mock = MockServer(MockConfig(platform_url=f"http://127.0.0.1:{api_port}", token=TOKEN, seed=7,
                                 llm_delay_s=(0.1, 0.1), whatif_pre_s=0.1, whatif_post_s=0.1))
    from aclopi.api import Settings
    from apiserver import ApiServer as _Api

    settings = Settings(host="127.0.0.1", port=api_port, n_session_workers=2, n_whatif_workers=2,
                        session_idle_timeout_s=600, work_dir=tmp_path_factory.mktemp("agent"),
                        agent_url=mock.url, agent_token=TOKEN, agent_health_interval_s=0.5)
    api = _Api(settings, warm=True)
    api.start()
    yield api, mock
    api.stop()
    mock.stop()


@pytest.fixture()
def client(stack: Any) -> Any:
    api, mock = stack
    mock.config.down = ""
    mock.config.weights = {"code-obvious": 0.5, "llm": 0.3, "llm-what-if": 0.15, "code-fallback": 0.05}
    api.runtime.registry.fast_decision_timeout_s = 90.0
    _wait_agent(api, "ok")
    wait_session_workers_free(api.url)
    with httpx.Client(base_url=api.url, timeout=120, headers={"Authorization": f"Bearer {TOKEN}"}) as c:
        yield c


def _wait_agent(api: ApiServer, status: str, timeout_s: float = 20) -> None:
    deadline = time.monotonic() + timeout_s
    while api.runtime.agent.status != status:
        assert time.monotonic() < deadline, f"agent status {api.runtime.agent.status!r}, expected {status!r}"
        time.sleep(0.1)


def _session(c: httpx.Client, strategy: str | None, seed: int = 42, horizon: int = 3000, rule: int = 4) -> str:
    body: dict[str, Any] = {"seed": seed, "rule": rule, "horizon_ticks": horizon}
    if strategy is not None:
        body["strategy"] = strategy
    r = c.post("/sessions", json=body)
    assert r.status_code == 201, r.text
    return r.json()["session_id"]


def _wait_run(c: httpx.Client, sid: str, states: tuple[str, ...], timeout_s: float = 180) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_s
    while True:
        info = c.get(f"/sessions/{sid}").json()
        if info["run_state"] in states:
            return info
        assert time.monotonic() < deadline, info
        time.sleep(0.2)


# ----- sessions and next-machine -----

def test_strategy_validation(client: httpx.Client) -> None:
    assert client.post("/sessions", json={"seed": 1, "rule": 4, "strategy": "random"}).status_code == 422
    assert client.post("/sessions", json={"seed": 1, "rule": 3, "strategy": "b1"}).status_code == 422
    sid = _session(client, None)  # rule 4 without strategy: the agent
    assert client.get(f"/sessions/{sid}").json()["strategy"] == "agent"
    client.delete(f"/sessions/{sid}")
    sid = _session(client, "none")  # still accepted (tests)
    info = client.get(f"/sessions/{sid}").json()
    assert info["strategy"] == "none" and info["warnings"] == []
    client.delete(f"/sessions/{sid}")
    sid = _session(client, "b1")
    assert client.get(f"/sessions/{sid}").json()["strategy"] == "b1"
    client.delete(f"/sessions/{sid}")


def test_next_machine_token_late_and_incapable(stack: Any, client: httpx.Client) -> None:
    api, _ = stack
    with SimulationSession() as s:  # a pending decision of seed 42
        s.setup(seed=42, rule=4)
        for _ in range(4):
            run_until_decision(s, 10000)
            req = pending_decisions(s)[0]
            clear_decisions(s)
        tick = s.ticks
    sid = _session(client, "b1", horizon=10000)
    while tick > 0:
        n = min(tick, 2000)
        client.post(f"/sessions/{sid}/step", params={"n": n}).raise_for_status()
        tick -= n
    body = {"product": req.who, "seq": req.seq, "machine": req.candidates[0], "decision_level": "heuristic"}
    with httpx.Client(base_url=api.url, timeout=30) as anonymous:
        assert anonymous.post(f"/sessions/{sid}/next-machine", json=body).status_code == 401
        assert anonymous.get(f"/sessions/{sid}/candidates", params={"product": req.who, "seq": req.seq}).status_code == 401
        wrong = anonymous.post(f"/sessions/{sid}/next-machine", json=body, headers={"Authorization": "Bearer nope"})
        assert wrong.status_code == 401
    incapable = next(m for m in ("M1", "M2", "M3", "M4", "M5", "M6", "M7") if m not in req.candidates)
    r = client.post(f"/sessions/{sid}/next-machine", json={**body, "machine": incapable})
    assert r.status_code == 422, r.text
    r = client.post(f"/sessions/{sid}/next-machine", json=body)
    assert r.status_code == 200 and r.json()["applied"] is True, r.text
    old = client.post(f"/sessions/{sid}/next-machine", json={**body, "seq": req.seq - 1})
    assert old.status_code == 409 and old.json()["code"] == "decision_not_pending"
    m = client.get(f"/sessions/{sid}/metrics").json()["decisions"]
    assert m["applied"] == 1 and m["late"] == 1 and m["by_level"] == {"heuristic": 1}
    client.delete(f"/sessions/{sid}")


# ----- live -----

def test_live_b1_decisions_keep_the_pace(stack: Any, client: httpx.Client) -> None:
    api, _ = stack
    sid = _session(client, "b1", horizon=10000)
    w = Watcher(api, sid)
    client.post(f"/sessions/{sid}/run", json={"mode": "live", "speed": 4}).raise_for_status()
    time.sleep(1.0)
    start = time.monotonic()
    time.sleep(17.0)
    ticks = [(t, m["tick"]) for t, m in w.messages if m["type"] == "tick" and t >= start]
    rate = (ticks[-1][1] - ticks[0][1]) / (ticks[-1][0] - ticks[0][0])
    m = client.get(f"/sessions/{sid}/metrics").json()["decisions"]
    decisions = w.of("decision")
    print(f"\nlive b1 4x: {rate:.1f} ticks/s, {m['applied']} decisions, sources {m['sources']}")
    assert abs(rate - 128.0) <= 128.0 * 0.05
    assert m["applied"] >= 3 and m["by_level"].get("heuristic", 0) == m["applied"] and m["late"] == 0
    assert decisions and all(d["level"] == "heuristic" and not d["late"] for d in decisions)
    assert m["sources"].get("agent", 0) >= 1  # the model used the agent's machine
    w.close()
    client.delete(f"/sessions/{sid}")


# ----- fast -----

def test_fast_b1_is_reproducible(stack: Any, client: httpx.Client) -> None:
    """Also checks the /decide context (read in the worker without random numbers: the runs stay identical)."""
    runs = []
    sids = []
    for _ in range(2):
        sid = _session(client, "b1")
        sids.append(sid)
        client.post(f"/sessions/{sid}/run", json={"mode": "fast"}).raise_for_status()
        info = _wait_run(client, sid, ("finished", "failed"))
        assert info["run_state"] == "finished", info
        kpis = client.get(f"/sessions/{sid}/kpis").json()
        decisions = [(d["product"], d["seq"], d["machine"]) for d in
                     client.get(f"/sessions/{sid}/metrics").json()["decisions"]["log"]]
        runs.append((kpis, decisions))
        client.delete(f"/sessions/{sid}")
    assert runs[0][1] and runs[0] == runs[1]
    received = [r for r in stack[1].app.state.requests if r["session_id"] in sids]
    assert received and [{k: v for k, v in r.items() if k != "session_id"} for r in received if r["session_id"] == sids[0]] ==         [{k: v for k, v in r.items() if k != "session_id"} for r in received if r["session_id"] == sids[1]]
    for r in received:
        # fast: read at the end of the go that queued the request (ticks advances at the end of go)
        assert r["context_tick"] in (r["tick"], r["tick"] + 1)
        assert r["pending_operations"][0] == r["operation"] and r["current_machine"] == r["origin"]
        assert r["current_operation"] is not None and r["own_remaining"] > 0
        assert r["next_operation"] == (r["pending_operations"][1] if len(r["pending_operations"]) > 1 else None)
        assert r["product_type"] in ("A", "I", "P", "B", "E", "L", "T") and 60 <= r["priority"] <= 100
        assert r["products_in_plant"] >= 1 and set(r["m1"]) == {"busy", "remaining", "queue_length"}
        assert r["m1"]["remaining"] > 0 if r["m1"]["busy"] else r["m1"]["remaining"] == 0


def test_fast_with_agent_down_fails(stack: Any, client: httpx.Client) -> None:
    api, mock = stack
    api.runtime.registry.fast_decision_timeout_s = 3.0
    mock.config.down = "decide"  # /health still answers: the run is allowed, decisions never come
    sid = _session(client, "b1")
    w = Watcher(api, sid)
    client.post(f"/sessions/{sid}/run", json={"mode": "fast"}).raise_for_status()
    info = _wait_run(client, sid, ("failed", "finished"), timeout_s=60)
    assert info["run_state"] == "failed" and info["run_reason"] == "agent_unavailable"
    failed = [m for m in w.of("run_state") if m["run_state"] == "failed"]
    assert failed and failed[-1]["reason"] == "agent_unavailable"
    assert client.post(f"/sessions/{sid}/run", json={"mode": "fast"}).status_code == 409
    w.close()
    client.delete(f"/sessions/{sid}")


def test_agent_down_health_and_fast_refused(stack: Any, client: httpx.Client) -> None:
    api, mock = stack
    mock.config.down = "all"
    _wait_agent(api, "down")
    assert client.get("/health/ready").status_code == 200
    agent = client.get("/health").json()["agent"]
    assert agent["status"] == "down" and agent["configured"]
    sid = _session(client, "agent")
    assert client.get(f"/sessions/{sid}").json()["warnings"] == ["agent_unavailable"]
    r = client.post(f"/sessions/{sid}/run", json={"mode": "fast"})
    assert r.status_code == 503 and r.json()["code"] == "agent_unavailable"
    assert client.post(f"/sessions/{sid}/run", json={"mode": "live"}).status_code == 200  # live is allowed
    client.delete(f"/sessions/{sid}")
    none = _session(client, "none")  # no decider: fast runs do not need the agent
    assert client.post(f"/sessions/{none}/run", json={"mode": "fast"}).status_code == 200
    client.delete(f"/sessions/{none}")


def test_fast_agent_with_whatif(stack: Any, client: httpx.Client) -> None:
    _, mock = stack
    mock.config.weights = {"llm": 0.4, "llm-what-if": 0.6}
    sid = _session(client, "agent")
    client.post(f"/sessions/{sid}/run", json={"mode": "fast"}).raise_for_status()
    info = _wait_run(client, sid, ("finished", "failed"), timeout_s=240)
    assert info["run_state"] == "finished", info
    metrics = client.get(f"/sessions/{sid}/metrics").json()
    d = metrics["decisions"]
    print(f"\nfast agent: {d['by_level']}, what-ifs {metrics['whatif']['requests']}")
    assert d["by_level"].get("llm-what-if", 0) >= 1 and d["late"] == 0 and d["unanswered"] == 0
    assert metrics["whatif"]["ok"] + metrics["whatif"]["timeout"] >= 1 and metrics["whatif"]["error"] == 0
    client.delete(f"/sessions/{sid}")


# ----- page (/ui): live decision panel -----

def test_ui_decision_panel_shows_the_agents_decisions(stack: Any, client: httpx.Client) -> None:
    """Real platform + simulated agent, rule 4 in the browser: the panel gets rows from the WebSocket
    "decision" messages (with the product type, operation and reason added to the message)."""
    playwright_sync = pytest.importorskip("playwright.sync_api")
    api, _ = stack
    with playwright_sync.sync_playwright() as p:
        try:
            browser = p.chromium.launch(channel="msedge")
        except Exception:  # noqa: BLE001 - Playwright's own Chromium, if installed
            browser = p.chromium.launch()
        try:
            page = browser.new_page()
            page.goto(f"{api.url}/ui")
            page.check("#seed-on")
            page.fill("#seed", "42")
            page.select_option("#rule", "4")
            page.fill("#horizon", "10000")
            page.click("#create")
            page.wait_for_function("document.querySelector('#sid').textContent !== ''")
            sid = page.inner_text("#sid")
            assert client.get(f"/sessions/{sid}").json()["strategy"] == "agent"
            page.select_option("#speed", "4")
            page.click("#live")
            page.wait_for_function("document.querySelectorAll('#dec-rows tr').length >= 1", timeout=90_000)
            cells = page.eval_on_selector("#dec-rows tr:first-child", "e => [...e.cells].map(c => c.textContent)")
            tick, product, operation, machine, level = cells[:5]
            assert int(tick) > 0 and product.startswith("p") and "(" in product, cells
            assert operation.startswith("O") and machine.startswith("M") and level != "–", cells
            assert cells[6].endswith(" ms"), cells
            page.click("#close")
        finally:
            browser.close()
