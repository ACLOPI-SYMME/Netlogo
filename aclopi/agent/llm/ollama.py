from __future__ import annotations

from typing import Any

import httpx

from aclopi.agent.llm.base import LLMClient, Messages


class OllamaLLM(LLMClient):
    """Ollama /api/chat with structured output (format = JSON schema), no thinking, model kept loaded."""

    name = "ollama"

    def __init__(self, url: str, model: str, num_ctx: int = 8192, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.url, self.model, self.num_ctx, self._transport = url.rstrip("/"), model, num_ctx, transport

    async def _complete(self, messages: Messages, schema: dict[str, Any], timeout_s: float) -> str:
        body = {"model": self.model, "messages": messages, "format": schema, "stream": False, "think": False,
                "keep_alive": -1, "options": {"num_ctx": self.num_ctx, "temperature": 0}}
        async with httpx.AsyncClient(timeout=timeout_s, transport=self._transport) as http:
            r = await http.post(f"{self.url}/api/chat", json=body)
            r.raise_for_status()
            return r.json()["message"]["content"]

    async def ping(self) -> bool:
        async with httpx.AsyncClient(timeout=2, transport=self._transport) as http:
            r = await http.get(f"{self.url}/api/tags")
            return r.status_code == 200
