"""LLM clients behind one interface:

    await client.complete_json(messages, schema, timeout_s) -> (dict | LLMError, latency_s)

messages: [{"role": "system" | "user" | "assistant", "content": str}]; schema: JSON schema of the
answer. Providers, chosen by ACLOPI_LLM_PROVIDER (configuration only by environment variables):

    fake       deterministic, for tests and the smoke test (aclopi.agent.llm.fake)
    ollama     /api/chat with format = JSON schema, think false, keep_alive -1
    anthropic  Messages API, forced tool call with the schema (ANTHROPIC_API_KEY)
    openai_compat  /chat/completions of an OpenAI-compatible server: ACLOPI_LLM_BASE_URL, ACLOPI_LLM_API_KEY,
               ACLOPI_LLM_MODEL, ACLOPI_LLM_TIMEOUT_S (30), ACLOPI_LLM_MAX_TOKENS (200),
               ACLOPI_LLM_REASONING_EFFORT (none; empty: not sent), ACLOPI_LLM_JSON_MODE (auto)

Any other value is an error when the service starts (create_app calls client_from_env).
"""

from __future__ import annotations

import os
from typing import Mapping

from aclopi.agent.llm.base import LLMClient, LLMError

PROVIDERS = ("fake", "ollama", "anthropic", "openai_compat")


def _get(env: Mapping[str, str], key: str, default: str) -> str:
    """An empty value counts as not set (docker compose passes ${VAR:-} as "")."""
    return (env.get(key) or "").strip() or default


def client_from_env(env: Mapping[str, str] | None = None) -> LLMClient:
    env = os.environ if env is None else env
    provider = _get(env, "ACLOPI_LLM_PROVIDER", "fake").lower()
    if provider == "fake":
        from aclopi.agent.llm.fake import FakeLLM

        return FakeLLM(
            latency_s=float(_get(env, "ACLOPI_FAKE_LATENCY_S", "0")),
            invalid_rate=float(_get(env, "ACLOPI_FAKE_INVALID_RATE", "0")),
            what_if_rate=float(_get(env, "ACLOPI_FAKE_WHAT_IF_RATE", "0")),
            seed=int(_get(env, "ACLOPI_FAKE_SEED", "0")),
        )
    if provider == "ollama":
        from aclopi.agent.llm.ollama import OllamaLLM

        return OllamaLLM(url=_get(env, "ACLOPI_OLLAMA_URL", "http://localhost:11434"),
                         model=_get(env, "ACLOPI_LLM_MODEL", "qwen3:8b"),
                         num_ctx=int(_get(env, "ACLOPI_OLLAMA_NUM_CTX", "8192")))
    if provider == "anthropic":
        from aclopi.agent.llm.anthropic import AnthropicLLM

        key = _get(env, "ANTHROPIC_API_KEY", "")
        if not key:
            raise RuntimeError("ACLOPI_LLM_PROVIDER=anthropic needs ANTHROPIC_API_KEY")
        return AnthropicLLM(api_key=key, model=_get(env, "ACLOPI_LLM_MODEL", "claude-haiku-5-5"),
                            url=_get(env, "ACLOPI_ANTHROPIC_URL", "https://api.anthropic.com"))
    if provider == "openai_compat":
        from aclopi.agent.llm.openai_compat import OpenAICompatLLM

        url, key = _get(env, "ACLOPI_LLM_BASE_URL", ""), _get(env, "ACLOPI_LLM_API_KEY", "")
        if not url or not key:
            raise RuntimeError("ACLOPI_LLM_PROVIDER=openai_compat needs ACLOPI_LLM_BASE_URL and ACLOPI_LLM_API_KEY")
        effort = env.get("ACLOPI_LLM_REASONING_EFFORT")
        return OpenAICompatLLM(base_url=url, api_key=key, model=_get(env, "ACLOPI_LLM_MODEL", "strata"),
                               timeout_s=float(_get(env, "ACLOPI_LLM_TIMEOUT_S", "30")),
                               max_tokens=int(_get(env, "ACLOPI_LLM_MAX_TOKENS", "200")),
                               reasoning_effort="none" if effort is None else effort.strip(),
                               json_mode=_get(env, "ACLOPI_LLM_JSON_MODE", "auto"))
    raise ValueError(f"ACLOPI_LLM_PROVIDER must be one of {PROVIDERS}, got {provider!r}")


__all__ = ["LLMClient", "LLMError", "PROVIDERS", "client_from_env"]
