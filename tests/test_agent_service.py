"""Agent service with a fake platform (httpx.MockTransport) and the fake LLM. No NetLogo, no network."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx

from aclopi.agent.llm.fake import FakeLLM
from aclopi.agent.service import AgentSettings, create_app

UNCERTAIN = [{"machine": "M3", "finish": 1300, "finish_plus_next": 1500, "start": 1090},
             {"machine": "M2", "finish": 1400, "finish_plus_next": 1450, "start": 1190}]


class FakePlatform:
    def __init__(self, next_status: int = 200) -> None:
        self.next_status, self.sent, self.calls = next_status, [], []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.calls.append((request.method, request.url.path, request.headers.get("authorization")))
        if request.url.path.endswith("/candidates"):
            return httpx.Response(200, json={"product": int(request.url.params["product"]), "seq": int(request.url.params["seq"]),
                                             "valid": True, "time": 1000.0, "current_machine": "M2",
                                             "own_remaining": 90.0, "candidates": UNCERTAIN})
        if request.url.path.endswith("/state"):
            return httpx.Response(200, json={"time": 1000.0, "products": [], "machines": []})
        if request.url.path.endswith("/next-machine"):
            self.sent.append(json.loads(request.content))
            if self.next_status == 409:
                return httpx.Response(409, json={"code": "decision_not_pending", "detail": "late"})
            return httpx.Response(self.next_status, json={"applied": True, "tick": 1})
        return httpx.Response(404)


def decide_body(product: int, strategy: str, seq: int = 2) -> dict[str, Any]:
    return {"session_id": "s1", "product": product, "seq": seq, "strategy": strategy, "mode": "fast",
            "ticks_per_second": None, "tick": 3226, "simulated_time": 1000.0}


async def exercise(platform: FakePlatform, bodies: list[dict[str, Any]], llm: FakeLLM, token: str = "",
                   tmp_log: str = "") -> tuple[Any, list[int]]:
    settings = AgentSettings(platform_url="http://platform", token=token, log_path=tmp_log, llm_max_parallel=1)
    app = create_app(settings, llm=llm, platform_transport=httpx.MockTransport(platform.handler))
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://agent") as client:
        codes = [(await client.post("/decide", json=b, headers=headers)).status_code for b in bodies]
        while app.state.tasks:
            await asyncio.gather(*list(app.state.tasks))
        app.state.health = (await client.get("/health")).json()
    return app, codes


def test_b1_b1b_and_agent_reply_to_the_platform(tmp_path) -> None:
    platform = FakePlatform()
    app, codes = asyncio.run(exercise(platform, [decide_body(201, "b1"), decide_body(202, "b1b"), decide_body(203, "agent")],
                                      FakeLLM(), tmp_log=str(tmp_path / "d.jsonl")))
    assert codes == [202, 202, 202]
    sent = {s["product"]: s for s in platform.sent}
    assert (sent[201]["machine"], sent[201]["decision_level"]) == ("M3", "heuristic")
    assert (sent[202]["machine"], sent[202]["decision_level"]) == ("M2", "heuristic")
    assert sent[203]["decision_level"] == "llm" and sent[203]["latencies"]["llm_ms"]
    lines = (tmp_path / "d.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 3 and {json.loads(x)["strategy"] for x in lines} == {"b1", "b1b", "agent"}
    assert app.state.health["provider"] == "fake" and app.state.health["llm"] == "ok"


def test_concurrent_decisions_and_token(tmp_path) -> None:
    platform = FakePlatform()
    bodies = [decide_body(300 + i, "agent") for i in range(6)]
    app, codes = asyncio.run(exercise(platform, bodies, FakeLLM(latency_s=0.05), token="t0k", tmp_log=str(tmp_path / "d.jsonl")))
    assert codes == [202] * 6 and len(platform.sent) == 6
    assert all(auth == "Bearer t0k" for _, _, auth in platform.calls)
    settings = AgentSettings(platform_url="http://platform", token="t0k", log_path=str(tmp_path / "x.jsonl"))
    app = create_app(settings, llm=FakeLLM(), platform_transport=httpx.MockTransport(platform.handler))

    async def unauthorized() -> int:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://agent") as client:
            return (await client.post("/decide", json=decide_body(1, "b1"))).status_code

    assert asyncio.run(unauthorized()) == 401


def test_rejections_are_logged_not_retried(tmp_path) -> None:
    platform = FakePlatform(next_status=409)
    app, _ = asyncio.run(exercise(platform, [decide_body(201, "b1")], FakeLLM(), tmp_log=str(tmp_path / "d.jsonl")))
    assert len(platform.sent) == 1
    record = list(app.state.records)[0]
    assert record["response"] == 409 and record["rejected"] == "decision_not_pending"


def test_b1_works_with_the_llm_down(tmp_path) -> None:
    class DownLLM(FakeLLM):
        async def _complete(self, *a: Any, **k: Any) -> str:
            raise ConnectionError("llm down")

    platform = FakePlatform()
    asyncio.run(exercise(platform, [decide_body(201, "b1"), decide_body(202, "agent")], DownLLM(), tmp_log=str(tmp_path / "d.jsonl")))
    sent = {s["product"]: s["decision_level"] for s in platform.sent}
    assert sent == {201: "heuristic", 202: "code-fallback"}  # fast mode never leaves it to rule 3
