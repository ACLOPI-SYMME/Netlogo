"""Agent service (FastAPI), the real counterpart of aclopi.agent_mock. Contract: docs/agent-api.md.

    POST /decide   -> 202 at once; the decision runs in an asyncio task:
                      b1 / b1b: candidates -> heuristic (no LLM);  agent: aclopi.agent.core.Agent
                      then POST /sessions/{id}/next-machine (Bearer ACLOPI_AGENT_TOKEN). 409 / 422
                      are logged, never retried.
    GET /health    -> service status, LLM provider and whether it answers (checked every 30 s in the
                      background; the fake is always ok). b1 / b1b work with the LLM down.
    GET /decisions -> the last decision records (also appended to ACLOPI_AGENT_LOG as JSON lines).
    POST /sequence/propose -> up to 2 entry orders of a product list from the LLM plus the heuristic
                      (aclopi.agent.sequencing; docs/sequencing.md). 200 also when the LLM fails.
Configuration only by environment variables (AgentSettings.from_env). Several decisions run at the
same time; LLM calls share a semaphore (LLM_MAX_PARALLEL, default 2).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from collections import deque
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, AsyncIterator, Mapping

import httpx
from fastapi import FastAPI, Header, Response

from aclopi.agent.core import Agent, AgentConfig, candidates_summary
from aclopi.agent.llm import LLMClient, client_from_env
from aclopi.agent.sequencing import SequenceRequest, propose
from aclopi.agent.strategies import DecisionContext, decide as decide_heuristic, short_reason
from aclopi.agent.triage import TriageParams
from aclopi.contracts.agent import DecideRequest, bearer_matches

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AgentSettings:
    platform_url: str = "http://localhost:8000"
    token: str = ""
    provider: str = "fake"
    llm_max_parallel: int = 2
    health_interval_s: float = 30.0
    sequence_timeout_s: float = 30.0
    log_path: str = "results/agent/decisions.jsonl"
    config: AgentConfig = AgentConfig()

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "AgentSettings":
        env = os.environ if env is None else env
        f = lambda k, d: float(env.get(k, d))  # noqa: E731
        return cls(
            platform_url=env.get("ACLOPI_PLATFORM_URL", "http://localhost:8000").rstrip("/"),
            token=env.get("ACLOPI_AGENT_TOKEN", ""),
            provider=env.get("ACLOPI_LLM_PROVIDER", "fake"),
            llm_max_parallel=int(env.get("LLM_MAX_PARALLEL", "2")),
            health_interval_s=f("ACLOPI_AGENT_HEALTH_INTERVAL_S", "30"),
            sequence_timeout_s=f("ACLOPI_SEQUENCE_TIMEOUT_S", "30"),
            log_path=env.get("ACLOPI_AGENT_LOG", "results/agent/decisions.jsonl"),
            config=AgentConfig(
                triage=TriageParams(u_wide=f("ACLOPI_U_WIDE", "100"), u_narrow=f("ACLOPI_U_NARROW", "50")),
                fast_deadline_s=f("ACLOPI_FAST_DEADLINE_S", "60"), what_if_p95_s=f("ACLOPI_WHATIF_P95_S", "5.5"),
                llm2_latency_s=f("ACLOPI_LLM2_LATENCY_S", "3")),
        )


class HttpPlatform:
    """The platform's decision endpoints over HTTP (aclopi.agent.core.Platform)."""

    def __init__(self, base_url: str, token: str = "", transport: httpx.AsyncBaseTransport | None = None) -> None:
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        self.http = httpx.AsyncClient(base_url=base_url, headers=headers, timeout=30, transport=transport)

    async def candidates(self, session_id: str, product: int, seq: int) -> dict[str, Any]:
        r = await self.http.get(f"/sessions/{session_id}/candidates", params={"product": product, "seq": seq})
        r.raise_for_status()
        return r.json()

    async def state(self, session_id: str) -> dict[str, Any]:
        r = await self.http.get(f"/sessions/{session_id}/state")
        r.raise_for_status()
        return r.json()

    async def what_if(self, session_id: str, product: int, seq: int, options: list[str], budget_ms: int) -> dict[str, Any]:
        r = await self.http.post(f"/sessions/{session_id}/what-if",
                                 json={"product": product, "seq": seq, "options": options, "budget_ms": budget_ms})
        r.raise_for_status()
        return r.json()

    async def next_machine(self, session_id: str, body: dict[str, Any]) -> httpx.Response:
        return await self.http.post(f"/sessions/{session_id}/next-machine", json=body)

    async def close(self) -> None:
        await self.http.aclose()


def create_app(settings: AgentSettings | None = None, llm: LLMClient | None = None,
               platform_transport: httpx.AsyncBaseTransport | None = None) -> FastAPI:
    settings = settings or AgentSettings.from_env()
    llm = llm or client_from_env()
    platform = HttpPlatform(settings.platform_url, settings.token, platform_transport)
    agent = Agent(platform, llm, settings.config, asyncio.Semaphore(settings.llm_max_parallel))
    health = {"llm": "ok" if settings.provider == "fake" else "unknown", "checked_at": None}
    log_path = Path(settings.log_path)

    async def check_llm_forever() -> None:
        while True:
            try:
                ok = await asyncio.wait_for(llm.ping(), timeout=5)
            except Exception:  # noqa: BLE001
                ok = False
            health.update(llm="ok" if ok else "down", checked_at=time.time())
            await asyncio.sleep(settings.health_interval_s)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        checker = asyncio.create_task(check_llm_forever())
        yield
        checker.cancel()
        await platform.close()

    app = FastAPI(title="ACLOPI agent", version="0.1.0", lifespan=lifespan)
    app.state.tasks = set()
    app.state.records = deque(maxlen=5000)
    app.state.agent, app.state.settings = agent, settings

    @app.get("/health")
    async def get_health() -> dict[str, Any]:
        return {"status": "ok", "provider": settings.provider, "llm": health["llm"], "llm_checked_at": health["checked_at"],
                "running_decisions": len(app.state.tasks)}

    @app.get("/decisions")
    async def get_decisions(session_id: str | None = None) -> list[dict[str, Any]]:
        return [r for r in app.state.records if session_id is None or r.get("session_id") == session_id]

    @app.post("/decide", status_code=202)
    async def post_decide(body: DecideRequest, authorization: str | None = Header(None)) -> Response:
        if settings.token and not bearer_matches(authorization, settings.token):
            return Response(status_code=401)
        if body.strategy == "none":
            return Response(status_code=202)
        task = asyncio.ensure_future(run_decision(body.model_dump()))
        app.state.tasks.add(task)
        task.add_done_callback(app.state.tasks.discard)
        return Response(status_code=202)

    @app.post("/sequence/propose", response_model=None)
    async def post_sequence(body: SequenceRequest, authorization: str | None = Header(None)) -> Any:
        if settings.token and not bearer_matches(authorization, settings.token):
            return Response(status_code=401)
        return await propose(llm, [p.model_dump() for p in body.products], settings.sequence_timeout_s)

    async def run_decision(req: dict[str, Any]) -> None:
        start = time.monotonic()
        try:
            if req["strategy"] in ("b1", "b1b"):
                cands = await platform.candidates(req["session_id"], req["product"], req["seq"])
                decision, record = None, {"session_id": req["session_id"], "product": req["product"], "seq": req["seq"],
                                          "strategy": req["strategy"], "mode": req["mode"], "tick": req.get("tick"),
                                          "now": cands.get("time"), **candidates_summary(cands),
                                          "gap_finish": cands.get("gap_finish"),
                                          "gap_finish_plus_next": cands.get("gap_finish_plus_next")}
                if cands.get("valid") and cands.get("candidates"):
                    decision = decide_heuristic(DecisionContext(req["session_id"], req["product"], req["seq"],
                                                                req["strategy"], req["mode"], cands))
                    chosen = next(c for c in cands["candidates"] if c["machine"] == decision.machine)
                    record.update(level="heuristic", machine=decision.machine, reason=decision.reason,
                                  estimated_finish=chosen.get("finish"), estimated_start=chosen.get("start"))
                else:
                    record["error"] = f"candidates-invalid: {cands.get('reason')}"
            else:
                decision, record = await agent.decide(req)
            if decision is not None:
                total_ms = round(1000 * (time.monotonic() - start), 1)
                latencies = {"total_ms": total_ms, "llm_ms": decision.latencies.get("llm_ms") or None}
                r = await platform.next_machine(req["session_id"], {
                    "product": req["product"], "seq": req["seq"], "machine": decision.machine,
                    "decision_level": decision.decision_level, "reason": short_reason(decision.reason), "latencies": latencies})
                record["response"] = r.status_code
                if r.status_code in (409, 422):
                    record["rejected"] = r.json().get("code") if r.headers.get("content-type", "").startswith("application/json") else r.status_code
                    logger.warning("next-machine %s for %s/%s: %s", r.status_code, req["product"], req["seq"], record["rejected"])
        except Exception as exc:  # noqa: BLE001 - a decision never brings the service down
            record = {"session_id": req.get("session_id"), "product": req.get("product"), "seq": req.get("seq"),
                      "strategy": req.get("strategy"), "error": f"{type(exc).__name__}: {exc}"[:300]}
            logger.exception("decision failed")
        record["total_ms"] = round(1000 * (time.monotonic() - start), 1)
        app.state.records.append(record)
        try:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            with log_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, default=str) + "\n")
        except OSError:
            logger.exception("could not write the decision log")

    return app
