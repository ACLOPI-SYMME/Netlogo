"""Mock agent (L5.5) for tests and local runs. Contract: aclopi/contracts/agent.py (PROPOSAL).

POST /decide answers 202 at once and decides in the background, then calls the platform's
POST /sessions/{id}/next-machine:

- b1 / b1b: at once, the best candidate by finish (b1b: finish_plus_next when the candidates give
  it, else finish); level "heuristic".
- agent: a level drawn with configurable weights (default code-obvious 0.5, llm 0.3, llm-what-if
  0.15, code-fallback 0.05):
    code-obvious   at once, best by finish
    llm            waits ACLOPI_MOCK_LLM_DELAY_S (3-4 s), best by finish
    llm-what-if    waits ~3 s, asks POST /what-if with the two best by finish (budget 10 s live,
                   15 s fast), waits ~1.5 s and takes the option with the earlier op_end_time.
                   Live: if the product's own_remaining (in seconds at ticks_per_second) minus 2 s
                   of margin is under ~12 s it decides as llm without a what-if. A skipped or
                   timed-out what-if: decides without it (level llm).
    code-fallback  best by finish
- "down" mode (ACLOPI_MOCK_DOWN = decide | health | all): those endpoints never answer.
- Own seed (ACLOPI_MOCK_SEED): its draws are reproducible when decisions arrive in the same order.
"""

from __future__ import annotations

import asyncio
import logging
import os
import random
import time
from dataclasses import dataclass, field
from typing import Any, Mapping

import httpx
from fastapi import FastAPI, Header, Response

from aclopi.contracts.agent import DecideRequest

logger = logging.getLogger(__name__)

LEVELS = ("code-obvious", "llm", "llm-what-if", "code-fallback")
TICK_TIME = 0.31  # simulated time units per tick


def _range(value: str, default: tuple[float, float]) -> tuple[float, float]:
    if not value.strip():
        return default
    parts = [float(x) for x in value.replace(",", "-").split("-") if x.strip()]
    return (parts[0], parts[-1])


@dataclass
class MockConfig:
    platform_url: str = "http://127.0.0.1:8000"
    token: str | None = None
    seed: int = 1
    weights: dict[str, float] = field(default_factory=lambda: {
        "code-obvious": 0.5, "llm": 0.3, "llm-what-if": 0.15, "code-fallback": 0.05})
    llm_delay_s: tuple[float, float] = (3.0, 4.0)
    whatif_pre_s: float = 3.0
    whatif_post_s: float = 1.5
    whatif_min_margin_s: float = 12.0
    down: str = ""  # "", "decide", "health" or "all"

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> MockConfig:
        env = os.environ if env is None else env
        cfg = cls()
        cfg.platform_url = (env.get("ACLOPI_PLATFORM_URL", "") or cfg.platform_url).rstrip("/")
        cfg.token = env.get("ACLOPI_AGENT_TOKEN", "").strip() or None
        cfg.seed = int(env.get("ACLOPI_MOCK_SEED", "") or cfg.seed)
        if env.get("ACLOPI_MOCK_FRACTIONS", "").strip():
            cfg.weights = {k.strip(): float(v) for k, v in
                           (item.split("=") for item in env["ACLOPI_MOCK_FRACTIONS"].split(","))}
        cfg.llm_delay_s = _range(env.get("ACLOPI_MOCK_LLM_DELAY_S", ""), cfg.llm_delay_s)
        cfg.whatif_pre_s = float(env.get("ACLOPI_MOCK_WHATIF_PRE_S", "") or cfg.whatif_pre_s)
        cfg.whatif_post_s = float(env.get("ACLOPI_MOCK_WHATIF_POST_S", "") or cfg.whatif_post_s)
        cfg.down = env.get("ACLOPI_MOCK_DOWN", "").strip()
        return cfg


def _rank(candidates: list[dict[str, Any]], b1b: bool = False) -> list[dict[str, Any]]:
    def key(c: dict[str, Any]) -> tuple[float, str]:
        value = c.get("finish_plus_next") if b1b and c.get("finish_plus_next") is not None else c.get("finish")
        return (float(value) if value is not None else float("inf"), c["machine"])
    return sorted(candidates, key=key)


def create_mock_app(config: MockConfig | None = None) -> FastAPI:
    cfg = config or MockConfig.from_env()
    rng = random.Random(cfg.seed)
    app = FastAPI(title="ACLOPI mock agent", version="0.1.0")
    app.state.config = cfg
    app.state.decided = []  # (session_id, product, seq, machine, level) for tests
    tasks: set[asyncio.Task[Any]] = set()
    headers = {"Authorization": f"Bearer {cfg.token}"} if cfg.token else {}

    @app.get("/health")
    async def health() -> dict[str, str]:
        if cfg.down in ("health", "all"):
            await asyncio.sleep(3600)
        return {"status": "ok"}

    @app.post("/decide", status_code=202)
    async def decide(body: DecideRequest, authorization: str | None = Header(None)) -> Response:
        if cfg.down in ("decide", "all"):
            await asyncio.sleep(3600)
        if cfg.token and authorization != f"Bearer {cfg.token}":
            return Response(status_code=401)
        task = asyncio.ensure_future(_decide(body))
        tasks.add(task)
        task.add_done_callback(tasks.discard)
        return Response(status_code=202)

    async def _decide(req: DecideRequest) -> None:
        t0 = time.perf_counter()
        llm_ms: list[float] = []
        base = f"{cfg.platform_url}/sessions/{req.session_id}"
        async with httpx.AsyncClient(timeout=30, headers=headers) as http:
            try:
                r = await http.get(f"{base}/candidates", params={"product": req.product, "seq": req.seq})
                cands = r.json() if r.status_code == 200 else {"valid": False}
                if not cands.get("valid"):
                    return  # no longer pending: nothing to decide
                ranked = _rank(cands["candidates"], b1b=req.strategy == "b1b")
                machine, level, reason = ranked[0]["machine"], "heuristic", "best finish"
                if req.strategy == "agent":
                    level = rng.choices(list(cfg.weights), weights=list(cfg.weights.values()))[0]
                    machine, reason = ranked[0]["machine"], f"mock {level}: best finish"
                    if level == "llm-what-if" and req.mode == "live" and req.ticks_per_second:
                        own_s = float(ranked[0].get("own_remaining") or 0.0) / TICK_TIME / req.ticks_per_second
                        if own_s - 2.0 < cfg.whatif_min_margin_s:
                            level, reason = "llm", "mock llm: no time for a what-if"
                    if level == "llm":
                        delay = rng.uniform(*cfg.llm_delay_s)
                        await asyncio.sleep(delay)
                        llm_ms.append(round(1000 * delay, 1))
                    elif level == "llm-what-if":
                        await asyncio.sleep(cfg.whatif_pre_s)
                        llm_ms.append(round(1000 * cfg.whatif_pre_s, 1))
                        options = [c["machine"] for c in ranked[:2]]
                        if len(options) == 2:
                            w = await http.post(f"{base}/what-if", json={
                                "product": req.product, "seq": req.seq, "options": options,
                                "budget_ms": 10000 if req.mode == "live" else 15000})
                            body = w.json() if w.status_code == 200 else {}
                            await asyncio.sleep(cfg.whatif_post_s)
                            llm_ms.append(round(1000 * cfg.whatif_post_s, 1))
                            if body.get("status") == "ok":
                                best = min(body["options"], key=lambda o: (o.get("op_end_time") or float("inf"),
                                                                           o["machine"]))
                                machine, reason = best["machine"], "mock llm-what-if: earlier op_end_time"
                            else:
                                level, reason = "llm", f"mock llm: what-if {body.get('status', w.status_code)}"
                        else:
                            level = "llm"
                await http.post(f"{base}/next-machine", json={
                    "product": req.product, "seq": req.seq, "machine": machine, "decision_level": level,
                    "reason": reason, "latencies": {"total_ms": round(1000 * (time.perf_counter() - t0), 1),
                                                    "llm_ms": llm_ms or None}})
                app.state.decided.append((req.session_id, req.product, req.seq, machine, level))
            except httpx.HTTPError as exc:
                logger.warning("mock agent: platform call failed: %s", type(exc).__name__)

    return app
