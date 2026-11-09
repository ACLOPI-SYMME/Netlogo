"""OpenAI-compatible chat completions (POST {base_url}/chat/completions, Bearer key).

JSON output, first mode the server accepts (json_mode "auto"; the one found is kept for the next calls):
    json_schema   response_format {"type": "json_schema", "json_schema": {"name", "schema", "strict": false}}
                  (not strict: the what-if schema has an optional "machine", which strict mode refuses)
    json_object   response_format {"type": "json_object"}
    prompt        no response_format; the schema goes in the system message (the answer is validated
                  afterwards by aclopi.agent.prompts.parse_answer, as with every provider)
A mode is rejected when the server answers 400, 404, 415 or 422 to it; any other error (401, 429, 5xx,
timeout) is a failure of that call and does not change the mode. json_mode can also be forced.
reasoning_effort is sent unless it is empty ("none" by default: no thinking, short latency).
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

import httpx

from aclopi.agent.llm.base import LLMClient, Messages

logger = logging.getLogger(__name__)

JSON_MODES = ("json_schema", "json_object", "prompt")
REJECTED = (400, 404, 415, 422)
_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$")


class ModeRejected(Exception):
    pass


def extract_json(text: str) -> str:
    """The JSON object of an answer: without ``` fences and text around it (it is parsed afterwards)."""
    text = _FENCE.sub("", (text or "").strip())
    start, end = text.find("{"), text.rfind("}")
    return text[start:end + 1] if 0 <= start < end else text


class OpenAICompatLLM(LLMClient):
    name = "openai_compat"

    def __init__(self, base_url: str, api_key: str, model: str, timeout_s: float = 30.0, max_tokens: int = 200,
                 reasoning_effort: str = "none", json_mode: str = "auto",
                 transport: httpx.AsyncBaseTransport | None = None) -> None:
        if json_mode != "auto" and json_mode not in JSON_MODES:
            raise ValueError(f"json_mode must be auto or one of {JSON_MODES}, got {json_mode!r}")
        self.base_url, self._key, self.model = base_url.rstrip("/"), api_key, model
        self.timeout_s, self.max_tokens, self.reasoning_effort = timeout_s, max_tokens, reasoning_effort
        self.json_mode: str | None = None if json_mode == "auto" else json_mode  # None: not found yet
        self._transport = transport

    def __repr__(self) -> str:  # never shows the key
        return f"OpenAICompatLLM(base_url={self.base_url!r}, model={self.model!r}, json_mode={self.json_mode!r})"

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._key}", "Content-Type": "application/json"}

    def _body(self, messages: Messages, schema: dict[str, Any], mode: str) -> dict[str, Any]:
        if mode == "prompt":
            hint = ("Answer with ONE JSON object only (no text, no code fences) that follows this JSON schema:\n"
                    + json.dumps(schema, separators=(",", ":")))
            messages = [{"role": "system", "content": hint}] + list(messages) if not any(
                m["role"] == "system" for m in messages) else [
                {**m, "content": m["content"] + "\n\n" + hint} if m["role"] == "system" else m for m in messages]
        body: dict[str, Any] = {"model": self.model, "max_tokens": self.max_tokens, "temperature": 0,
                                "messages": list(messages)}
        if self.reasoning_effort:
            body["reasoning_effort"] = self.reasoning_effort
        if mode == "json_schema":
            body["response_format"] = {"type": "json_schema",
                                       "json_schema": {"name": "decision", "schema": schema, "strict": False}}
        elif mode == "json_object":
            body["response_format"] = {"type": "json_object"}
        return body

    async def _post(self, http: httpx.AsyncClient, messages: Messages, schema: dict[str, Any], mode: str) -> str:
        r = await http.post(f"{self.base_url}/chat/completions", json=self._body(messages, schema, mode),
                            headers=self._headers())
        if r.status_code in REJECTED and self.json_mode is None:
            raise ModeRejected(f"{r.status_code}: {r.text[:200]}")
        r.raise_for_status()
        return extract_json(r.json()["choices"][0]["message"]["content"] or "")

    async def _complete(self, messages: Messages, schema: dict[str, Any], timeout_s: float) -> str:
        async with httpx.AsyncClient(timeout=min(timeout_s, self.timeout_s), transport=self._transport) as http:
            if self.json_mode is not None:
                return await self._post(http, messages, schema, self.json_mode)
            for mode in JSON_MODES:
                try:
                    text = await self._post(http, messages, schema, mode)
                except ModeRejected as exc:
                    logger.info("openai_compat: %s not accepted (%s)", mode, exc)
                    continue
                self.json_mode = mode
                logger.info("openai_compat: JSON output mode %s", mode)
                return text
        raise RuntimeError("the server rejected every JSON output mode")

    async def ping(self) -> bool:
        async with httpx.AsyncClient(timeout=5, transport=self._transport) as http:
            r = await http.get(f"{self.base_url}/models", headers=self._headers())
            return r.status_code == 200
