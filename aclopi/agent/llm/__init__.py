"""LLM clients behind one interface:

    await client.complete_json(messages, schema, timeout_s) -> (dict | LLMError, latency_s)

messages: [{"role": "system" | "user" | "assistant", "content": str}]; schema: JSON schema of the
answer. Providers, chosen by ACLOPI_LLM_PROVIDER (configuration only by environment variables):

    fake       deterministic, for tests and the smoke test (aclopi.agent.llm.fake)
    ollama     /api/chat with format = JSON schema, think false, keep_alive -1
    anthropic  Messages API, forced tool call with the schema (ANTHROPIC_API_KEY)

Any other value is an error when the service starts (create_app calls client_from_env).
"""

from __future__ import annotations

import os
from typing import Mapping

from aclopi.agent.llm.base import LLMClient, LLMError

PROVIDERS = ("fake", "ollama", "anthropic")


def client_from_env(env: Mapping[str, str] | None = None) -> LLMClient:
    env = os.environ if env is None else env
    provider = env.get("ACLOPI_LLM_PROVIDER", "fake").strip().lower()
    if provider == "fake":
        from aclopi.agent.llm.fake import FakeLLM

        return FakeLLM(
            latency_s=float(env.get("ACLOPI_FAKE_LATENCY_S", "0")),
            invalid_rate=float(env.get("ACLOPI_FAKE_INVALID_RATE", "0")),
            what_if_rate=float(env.get("ACLOPI_FAKE_WHAT_IF_RATE", "0")),
            seed=int(env.get("ACLOPI_FAKE_SEED", "0")),
        )
    if provider == "ollama":
        from aclopi.agent.llm.ollama import OllamaLLM

        return OllamaLLM(url=env.get("ACLOPI_OLLAMA_URL", "http://localhost:11434"),
                         model=env.get("ACLOPI_LLM_MODEL", "qwen3:8b"),
                         num_ctx=int(env.get("ACLOPI_OLLAMA_NUM_CTX", "8192")))
    if provider == "anthropic":
        from aclopi.agent.llm.anthropic import AnthropicLLM

        key = env.get("ANTHROPIC_API_KEY", "")
        if not key:
            raise RuntimeError("ACLOPI_LLM_PROVIDER=anthropic needs ANTHROPIC_API_KEY")
        return AnthropicLLM(api_key=key, model=env.get("ACLOPI_LLM_MODEL", "claude-haiku-5-5"),
                            url=env.get("ACLOPI_ANTHROPIC_URL", "https://api.anthropic.com"))
    raise ValueError(f"ACLOPI_LLM_PROVIDER must be one of {PROVIDERS}, got {provider!r}")


__all__ = ["LLMClient", "LLMError", "PROVIDERS", "client_from_env"]
