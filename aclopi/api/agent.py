"""Client of the agent service (L5.5): POST /decide and GET /health. Contract: aclopi/contracts/agent.py.

- decide() never raises and never blocks a run: one attempt, ACLOPI_AGENT_DECIDE_TIMEOUT_S (2 s),
  no retries. A failure is logged and counted; what happens next is the caller's business (live:
  the model applies rule 3; fast: the API fails the run after ACLOPI_FAST_DECISION_TIMEOUT_S).
- health_loop() polls GET /health every ACLOPI_AGENT_HEALTH_INTERVAL_S. The result shows in
  GET /health (detail) and never affects /health/ready.
- The shared token (ACLOPI_AGENT_TOKEN) goes in the Authorization header and is never logged.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class AgentClient:
    def __init__(self, url: str | None, token: str | None, decide_timeout_s: float = 2.0,
                 health_interval_s: float = 30.0) -> None:
        self.url = url
        self.token = token
        self.decide_timeout_s = decide_timeout_s
        self.health_interval_s = health_interval_s
        self.status = "unknown" if url else "not_configured"  # ok | down | unknown | not_configured
        self.last_check: float | None = None
        self.last_ok: float | None = None
        self.last_error: str | None = None
        self.decide_sent = 0
        self.decide_failed = 0
        self._client: httpx.AsyncClient | None = None

    @property
    def available(self) -> bool:
        return self.status == "ok"

    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"} if self.token else {}

    async def start(self) -> None:
        self._client = httpx.AsyncClient(timeout=self.decide_timeout_s)

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()

    def info(self) -> dict[str, Any]:
        return {"configured": self.url is not None, "status": self.status, "last_check": self.last_check,
                "last_ok": self.last_ok, "last_error": self.last_error, "decide_sent": self.decide_sent,
                "decide_failed": self.decide_failed}

    async def check(self) -> None:
        if not self.url or self._client is None:
            return
        self.last_check = time.time()
        try:
            r = await self._client.get(f"{self.url}/health", headers=self.headers(), timeout=self.decide_timeout_s)
            if r.status_code == 200:
                self.status, self.last_ok, self.last_error = "ok", self.last_check, None
            else:
                self.status, self.last_error = "down", f"/health answered {r.status_code}"
        except httpx.HTTPError as exc:
            self.status, self.last_error = "down", f"{type(exc).__name__}"
        if self.status != "ok":
            logger.warning("Agent health check failed: %s", self.last_error)

    async def health_loop(self) -> None:
        while True:
            try:
                await self.check()
            except Exception:  # noqa: BLE001 - the loop must keep running
                logger.exception("Agent health check crashed")
            await asyncio.sleep(self.health_interval_s)

    async def decide(self, payload: dict[str, Any]) -> bool:
        """POST /decide once; True if the agent accepted it (2xx)."""
        self.decide_sent += 1
        if not self.url or self._client is None:
            self.decide_failed += 1
            logger.warning("No agent configured (ACLOPI_AGENT_URL): decision not requested",
                           extra={"session_id": payload.get("session_id")})
            return False
        try:
            r = await self._client.post(f"{self.url}/decide", json=payload, headers=self.headers(),
                                        timeout=self.decide_timeout_s)
            if 200 <= r.status_code < 300:
                return True
            error = f"/decide answered {r.status_code}"
        except httpx.HTTPError as exc:
            error = f"/decide failed: {type(exc).__name__}"
        self.decide_failed += 1
        logger.warning("%s (product %s, seq %s)", error, payload.get("product"), payload.get("seq"),
                       extra={"session_id": payload.get("session_id")})
        return False
