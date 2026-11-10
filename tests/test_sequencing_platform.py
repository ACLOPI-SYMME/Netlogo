"""simulate_list b1b (decided in the worker, no HTTP) gives the same makespan as b1b through the
platform (API + worker + the real agent service, POST /decide -> next-machine): 10 products, seed 42,
Deterministic. The API and the agent service run in threads of this process."""

from __future__ import annotations

import threading
import time
from typing import Any

import httpx
import pytest
import uvicorn

from aclopi.agent.llm.fake import FakeLLM
from aclopi.agent.service import AgentSettings, create_app as create_agent_app
from aclopi.sim import SimulationSession
from aclopi.sim.sequencing import simulate_list
from apiserver import ApiServer, free_port

TOKEN = "test-token"
LIST_10 = [{"type": t, "priority": 80} for t in "ABIEAPBTLA"]


@pytest.fixture(scope="module")
def stack(tmp_path_factory: pytest.TempPathFactory) -> Any:
    from aclopi.api import Settings

    api_port, agent_port = free_port(), free_port()
    agent_app = create_agent_app(AgentSettings(platform_url=f"http://127.0.0.1:{api_port}", token=TOKEN,
                                               log_path=str(tmp_path_factory.mktemp("agent") / "d.jsonl")), llm=FakeLLM())
    agent = uvicorn.Server(uvicorn.Config(agent_app, host="127.0.0.1", port=agent_port, log_config=None, access_log=False))
    thread = threading.Thread(target=agent.run, daemon=True)
    thread.start()
    settings = Settings(host="127.0.0.1", port=api_port, n_session_workers=1, n_whatif_workers=1,
                        session_idle_timeout_s=600, work_dir=tmp_path_factory.mktemp("api"),
                        agent_url=f"http://127.0.0.1:{agent_port}", agent_token=TOKEN, agent_health_interval_s=0.5)
    api = ApiServer(settings, warm=False)
    api.start()
    yield api
    api.stop()
    agent.should_exit = True
    thread.join(10)


def test_b1b_in_the_worker_equals_b1b_through_the_platform(stack: ApiServer) -> None:
    with httpx.Client(base_url=stack.url, timeout=60, headers={"Authorization": f"Bearer {TOKEN}"}) as c:
        deadline = time.monotonic() + 30
        while c.get("/health").json()["agent"]["status"] != "ok":
            assert time.monotonic() < deadline, "agent not ok"
            time.sleep(0.2)
        r = c.post("/sessions", json={"seed": 42, "rule": 4, "strategy": "b1b", "modeling_type": "Deterministic",
                                      "horizon_ticks": 200000, "products": LIST_10})
        assert r.status_code == 201, r.text
        sid = r.json()["session_id"]
        c.post(f"/sessions/{sid}/run", json={"mode": "fast"}).raise_for_status()
        deadline = time.monotonic() + 240
        while (info := c.get(f"/sessions/{sid}").json())["run_state"] not in ("finished", "failed"):
            assert time.monotonic() < deadline, info
            time.sleep(0.5)
        platform = c.get(f"/sessions/{sid}/kpis").json()
        decisions = c.get(f"/sessions/{sid}/metrics").json()["decisions"]
        c.delete(f"/sessions/{sid}")
    with SimulationSession() as s:
        local = simulate_list(s, LIST_10, "b1b", "Deterministic", 42)
    print(f"\nplatform {platform['makespan_ticks']} ({decisions['applied']} decisions), worker {local['makespan_ticks']}")
    assert info["run_state"] == "finished" and platform["all_done"] and decisions["applied"] > 0
    assert decisions["by_level"] == {"heuristic": decisions["applied"]}
    assert (local["makespan_ticks"], local["makespan_time"]) == (platform["makespan_ticks"], platform["makespan_time"])
