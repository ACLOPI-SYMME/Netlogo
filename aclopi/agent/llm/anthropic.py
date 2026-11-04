from __future__ import annotations

from typing import Any

import httpx

from aclopi.agent.llm.base import LLMClient, Messages, split_system

TOOL = "decision"


class AnthropicLLM(LLMClient):
    """Messages API; the answer is a forced tool call whose input_schema is the answer schema."""

    name = "anthropic"

    def __init__(self, api_key: str, model: str, url: str = "https://api.anthropic.com",
                 max_tokens: int = 300, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._key, self.model, self.url, self.max_tokens, self._transport = api_key, model, url.rstrip("/"), max_tokens, transport

    def _headers(self) -> dict[str, str]:
        return {"x-api-key": self._key, "anthropic-version": "2023-06-01", "content-type": "application/json"}

    async def _complete(self, messages: Messages, schema: dict[str, Any], timeout_s: float) -> dict[str, Any]:
        system, rest = split_system(messages)
        body = {"model": self.model, "max_tokens": self.max_tokens, "temperature": 0,
                "system": [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
                "messages": rest,
                "tools": [{"name": TOOL, "description": "Return the decision.", "input_schema": schema}],
                "tool_choice": {"type": "tool", "name": TOOL}}
        async with httpx.AsyncClient(timeout=timeout_s, transport=self._transport) as http:
            r = await http.post(f"{self.url}/v1/messages", json=body, headers=self._headers())
            r.raise_for_status()
            for block in r.json().get("content", []):
                if block.get("type") == "tool_use":
                    return dict(block.get("input") or {})
        raise ValueError("no tool_use block in the answer")
