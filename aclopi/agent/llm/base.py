from __future__ import annotations

import asyncio
import json
import time
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, Iterator

Messages = list[dict[str, str]]

# Calls made inside `with min_tokens(n)` get max_tokens >= n (providers with a limit: openai_compat,
# anthropic). For answers longer than a decision, e.g. the orders of aclopi.agent.sequencing.
_MIN_TOKENS: ContextVar[int] = ContextVar("aclopi_llm_min_tokens", default=0)


@contextmanager
def min_tokens(n: int) -> Iterator[None]:
    token = _MIN_TOKENS.set(int(n))
    try:
        yield
    finally:
        _MIN_TOKENS.reset(token)


def token_limit(default: int) -> int:
    return max(int(default), _MIN_TOKENS.get())


@dataclass(frozen=True)
class LLMError:
    kind: str  # timeout | http | invalid-json | provider
    detail: str = ""


class LLMClient:
    """Base class: providers implement _complete (raw text or dict); timing and errors are shared."""

    name = "base"

    async def complete_json(self, messages: Messages, schema: dict[str, Any], timeout_s: float) -> tuple[dict[str, Any] | LLMError, float]:
        start = time.perf_counter()
        try:
            raw = await asyncio.wait_for(self._complete(messages, schema, timeout_s), timeout=max(0.01, timeout_s))
        except asyncio.TimeoutError:
            return LLMError("timeout", f"{timeout_s:.1f} s"), time.perf_counter() - start
        except Exception as exc:  # noqa: BLE001 - any provider failure is reported, never raised
            return LLMError("provider", f"{type(exc).__name__}: {exc}"[:300]), time.perf_counter() - start
        latency = time.perf_counter() - start
        if isinstance(raw, dict):
            return raw, latency
        try:
            data = json.loads(raw)
        except (TypeError, ValueError) as exc:
            return LLMError("invalid-json", str(exc)[:200]), latency
        if not isinstance(data, dict):
            return LLMError("invalid-json", "not a JSON object"), latency
        return data, latency

    async def _complete(self, messages: Messages, schema: dict[str, Any], timeout_s: float) -> str | dict[str, Any]:
        raise NotImplementedError

    async def ping(self) -> bool:
        """Cheap liveness check for /health."""
        return True


def split_system(messages: Messages) -> tuple[str, Messages]:
    system = "\n\n".join(m["content"] for m in messages if m["role"] == "system")
    return system, [m for m in messages if m["role"] != "system"]
