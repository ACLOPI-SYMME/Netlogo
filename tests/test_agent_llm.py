"""LLM clients (fake, and the real providers with mocked HTTP / boto3) and the prompt. No network."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx
import pytest

from aclopi.agent.llm import LLMError, client_from_env
from aclopi.agent.llm.anthropic import AnthropicLLM
from aclopi.agent.llm.fake import FakeLLM
from aclopi.agent.llm.ollama import OllamaLLM
from aclopi.agent.prompts import Answer, answer_schema, build_messages, estimated_tokens, parse_answer
from aclopi.agent.service import AgentSettings, create_app

MACHINES = ["M3", "M2", "M5", "M7"]
SCHEMA = answer_schema(MACHINES, allow_what_if=True)
MSGS = [{"role": "system", "content": "sys"}, {"role": "user", "content": "choose"}]


def run(coro: Any) -> Any:
    return asyncio.run(coro)


def test_fake_is_deterministic_and_configurable() -> None:
    a = [run(FakeLLM(seed=1, invalid_rate=0.3, what_if_rate=0.5).complete_json(MSGS, SCHEMA, 1))[0] for _ in range(1)]
    llm1, llm2 = FakeLLM(seed=1, invalid_rate=0.3, what_if_rate=0.5), FakeLLM(seed=1, invalid_rate=0.3, what_if_rate=0.5)
    out1 = [run(llm1.complete_json(MSGS, SCHEMA, 1))[0] for _ in range(30)]
    out2 = [run(llm2.complete_json(MSGS, SCHEMA, 1))[0] for _ in range(30)]
    assert out1 == out2 and a[0] == out1[0]
    assert any(isinstance(o, LLMError) and o.kind == "invalid-json" for o in out1)
    assert any(isinstance(o, dict) and o["action"] == "what_if" for o in out1)
    assert all(o["machine"] == "M3" for o in out1 if isinstance(o, dict) and o["action"] == "decide")
    # Decide-only schema: never what_if.
    plain = FakeLLM(what_if_rate=1.0)
    assert run(plain.complete_json(MSGS, answer_schema(MACHINES, False), 1))[0]["action"] == "decide"


def test_fake_latency_and_timeout() -> None:
    data, latency = run(FakeLLM(latency_s=0.2).complete_json(MSGS, SCHEMA, 1))
    assert isinstance(data, dict) and latency >= 0.2
    data, _ = run(FakeLLM(latency_s=0.5).complete_json(MSGS, SCHEMA, 0.1))
    assert isinstance(data, LLMError) and data.kind == "timeout"


def test_fake_uses_what_if_results() -> None:
    msgs = [{"role": "user", "content": "- option M2: op_end_time 330.0; ...\n- option M7: op_end_time 310.5; ..."}]
    data, _ = run(FakeLLM().complete_json(msgs, answer_schema(["M2", "M7"], False), 1))
    assert data["machine"] == "M7"


def test_ollama_request_shape() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(json.loads(request.content))
        return httpx.Response(200, json={"message": {"content": '{"action": "decide", "machine": "M2", "reason": "x"}'}})

    llm = OllamaLLM("http://ollama:11434", "qwen3:8b", num_ctx=4096, transport=httpx.MockTransport(handler))
    data, _ = run(llm.complete_json(MSGS, SCHEMA, 5))
    assert data["machine"] == "M2"
    assert seen["format"] == SCHEMA and seen["think"] is False and seen["keep_alive"] == -1
    assert seen["options"]["num_ctx"] == 4096 and seen["stream"] is False


def test_anthropic_request_shape_and_errors() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["headers"], seen["body"] = request.headers, json.loads(request.content)
        return httpx.Response(200, json={"content": [{"type": "tool_use", "name": "decision",
                                                      "input": {"action": "decide", "machine": "M5", "reason": "y"}}]})

    llm = AnthropicLLM("sk-test", "claude-haiku-5-5", transport=httpx.MockTransport(handler))
    data, _ = run(llm.complete_json(MSGS, SCHEMA, 5))
    assert data["machine"] == "M5" and seen["headers"]["x-api-key"] == "sk-test"
    body = seen["body"]
    assert body["model"] == "claude-haiku-5-5" and body["tool_choice"] == {"type": "tool", "name": "decision"}
    assert body["tools"][0]["input_schema"] == SCHEMA and body["system"][0]["text"] == "sys"
    assert [m["role"] for m in body["messages"]] == ["user"]
    failing = AnthropicLLM("k", "m", transport=httpx.MockTransport(lambda r: httpx.Response(529, json={})))
    err, _ = run(failing.complete_json(MSGS, SCHEMA, 5))
    assert isinstance(err, LLMError) and err.kind == "provider"


def test_removed_provider_fails_at_startup(monkeypatch: pytest.MonkeyPatch) -> None:
    # A provider that is no longer supported (bedrock was removed) stops the service when it starts.
    monkeypatch.setenv("ACLOPI_LLM_PROVIDER", "bedrock")
    with pytest.raises(ValueError, match=r"must be one of \('fake', 'ollama', 'anthropic'\), got 'bedrock'"):
        create_app(AgentSettings(provider="bedrock"))


def test_empty_model_means_the_provider_default() -> None:
    # docker compose passes ACLOPI_LLM_MODEL: ${ACLOPI_LLM_MODEL:-} as "" when it is not set.
    assert client_from_env({"ACLOPI_LLM_PROVIDER": "ollama", "ACLOPI_LLM_MODEL": ""}).model == "qwen3:8b"
    assert client_from_env({"ACLOPI_LLM_PROVIDER": "anthropic", "ANTHROPIC_API_KEY": "k",
                            "ACLOPI_LLM_MODEL": "  "}).model == "claude-haiku-5-5"
    assert client_from_env({"ACLOPI_LLM_PROVIDER": "ollama", "ACLOPI_LLM_MODEL": "llama3:8b"}).model == "llama3:8b"
    assert isinstance(client_from_env({"ACLOPI_LLM_PROVIDER": "", "ACLOPI_FAKE_SEED": ""}), FakeLLM)


def test_provider_from_env() -> None:
    assert isinstance(client_from_env({"ACLOPI_LLM_PROVIDER": "fake", "ACLOPI_FAKE_LATENCY_S": "0.5"}), FakeLLM)
    assert isinstance(client_from_env({"ACLOPI_LLM_PROVIDER": "ollama"}), OllamaLLM)
    assert client_from_env({"ACLOPI_LLM_PROVIDER": "anthropic", "ANTHROPIC_API_KEY": "k"}).model == "claude-haiku-5-5"
    with pytest.raises(RuntimeError):
        client_from_env({"ACLOPI_LLM_PROVIDER": "anthropic"})
    with pytest.raises(ValueError):
        client_from_env({"ACLOPI_LLM_PROVIDER": "gpt"})


def test_answer_validation() -> None:
    assert isinstance(parse_answer({"action": "decide", "machine": "M2", "reason": "r"}, MACHINES, False), Answer)
    assert parse_answer({"action": "decide", "machine": "M1", "reason": "r"}, MACHINES, False).startswith("machine-not-candidate")
    assert parse_answer({"action": "what_if", "reason": "r"}, MACHINES, False) == "what-if-not-offered"
    assert isinstance(parse_answer({"action": "what_if"}, MACHINES, True), Answer)
    assert parse_answer({"action": "decide"}, MACHINES, True).startswith("invalid-answer")
    assert answer_schema(MACHINES, False)["properties"]["action"]["enum"] == ["decide"]


def big_prompt() -> list[dict[str, str]]:
    now = 1000.0
    cands = [{"machine": m, "finish": now + 300 + 20 * i, "delta_finish": 20 * i, "finish_plus_next": now + 400 + 10 * i,
              "delta_finish_plus_next": 10 * i, "next_machine": "M7", "travel": 124.6, "current_remaining": 150.0,
              "queue_time": 420.0, "queue": [301, 302], "en_route_time": 210.0, "en_route": [303],
              "is_current_machine": i == 0} for i, m in enumerate(MACHINES)]
    result = {"product": 200, "seq": 2, "time": now, "operation": "O1", "current_machine": "M3", "own_remaining": 100.0,
              "gap_finish": 20.0, "gap_finish_plus_next": 10.0, "candidates": cands}
    context = {"products_in_plant": 9, "m1_busy": True, "m1_remaining": 40.0, "m1_queue": 2,
               "pending_operations": ["O1", "O1", "O2", "O2", "O4", "O9"], "product_type": "E"}
    what_if = {"status": "ok", "options": [
        {"machine": "M3", "op_end_time": now + 310, "others": {"work": 431.2, "wait": 38.4, "presence": 612.3, "finished": 0}},
        {"machine": "M2", "op_end_time": now + 330, "op_end_estimated": True,
         "others": {"work": 520.0, "wait": 20.0, "presence": 600.0, "finished": 1}}]}
    return build_messages(context, result, cands, allow_what_if=False, what_if=what_if)


def test_prompt_content_and_size() -> None:
    msgs = big_prompt()
    assert msgs[0]["role"] == "system" and msgs[-1]["role"] == "user"  # fixed part first
    user = msgs[-1]["content"]
    assert "option M2: op_end_time 330.0 (estimated)" in user and "makespan" in msgs[0]["content"]
    assert "| M3 (current machine: in place) | +300 |" in user
    assert "M1: 40 u.t. left of its job, 2 waiting" in user and "type E" in user
    assert "(step 2 of 7). Pending after it: O1 O2 O2 O4 O9." in user
    tokens = estimated_tokens(msgs)
    print("largest prompt, estimated tokens:", tokens)
    assert tokens <= 3000
