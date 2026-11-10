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
from aclopi.agent.llm.openai_compat import OpenAICompatLLM, extract_json
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
    with pytest.raises(ValueError, match=r"must be one of \('fake', 'ollama', 'anthropic', 'openai_compat'\), got 'bedrock'"):
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


# ----- openai_compat (HTTP simulated) -----

ANSWER = {"action": "decide", "machine": "M2", "reason": "M2 finishes 30 u.t. earlier"}


def compat_server(accepts: set[str], content: str = json.dumps(ANSWER),
                  status: int = 200) -> tuple[httpx.MockTransport, list[dict[str, Any]]]:
    """Fake OpenAI-compatible server: answers 400 to the response_format types it does not accept."""
    seen: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        seen.append({"url": str(request.url), "auth": request.headers.get("authorization"), "body": body})
        mode = (body.get("response_format") or {}).get("type", "prompt")
        if mode not in accepts:
            return httpx.Response(400, json={"error": {"message": f"{mode} not supported"}})
        if status != 200:
            return httpx.Response(status, json={"error": {"message": "nope"}})
        return httpx.Response(200, json={"choices": [{"message": {"role": "assistant", "content": content}}]})

    return httpx.MockTransport(handler), seen


def compat(transport: httpx.MockTransport, **kw: Any) -> OpenAICompatLLM:
    return OpenAICompatLLM("http://llm.test/v1/", "sk-secret", "strata", transport=transport, **kw)


def test_openai_compat_request_shape() -> None:
    transport, seen = compat_server({"json_schema", "json_object", "prompt"})
    llm = compat(transport)
    data, _ = run(llm.complete_json(MSGS, SCHEMA, 5))
    assert data == ANSWER and llm.json_mode == "json_schema"
    req = seen[0]
    assert req["url"] == "http://llm.test/v1/chat/completions" and req["auth"] == "Bearer sk-secret"
    body = req["body"]
    assert body["model"] == "strata" and body["reasoning_effort"] == "none" and body["max_tokens"] == 200
    assert body["response_format"]["json_schema"]["schema"] == SCHEMA and body["messages"] == MSGS
    assert "sk-secret" not in repr(llm)


def test_openai_compat_json_mode_fallback_order_and_kept() -> None:
    transport, seen = compat_server({"json_object", "prompt"})
    llm = compat(transport)
    assert run(llm.complete_json(MSGS, SCHEMA, 5))[0] == ANSWER
    assert [r["body"].get("response_format", {}).get("type") for r in seen] == ["json_schema", "json_object"]
    assert llm.json_mode == "json_object"
    run(llm.complete_json(MSGS, SCHEMA, 5))  # next call: straight to the mode found
    assert [r["body"]["response_format"]["type"] for r in seen[2:]] == ["json_object"]


def test_openai_compat_prompt_mode_puts_the_schema_in_the_system_message() -> None:
    transport, seen = compat_server({"prompt"}, content="```json\n" + json.dumps(ANSWER) + "\n```")
    llm = compat(transport)
    data, _ = run(llm.complete_json(MSGS, SCHEMA, 5))
    assert data == ANSWER and llm.json_mode == "prompt" and len(seen) == 3
    last = seen[-1]["body"]
    assert "response_format" not in last and last["messages"][0]["role"] == "system"
    system = last["messages"][0]["content"]
    assert system.startswith("sys") and json.dumps(SCHEMA, separators=(",", ":")) in system
    # with no response_format the answer is still validated: a wrong machine is rejected by parse_answer
    bad, _ = compat_server({"prompt"}, content=json.dumps({**ANSWER, "machine": "M1"}))
    data, _ = run(compat(bad).complete_json(MSGS, SCHEMA, 5))
    assert parse_answer(data, MACHINES, True).startswith("machine-not-candidate")


def test_openai_compat_errors_do_not_change_the_mode() -> None:
    transport, seen = compat_server({"json_schema"}, status=401)
    llm = compat(transport)
    err, _ = run(llm.complete_json(MSGS, SCHEMA, 5))
    assert isinstance(err, LLMError) and err.kind == "provider" and llm.json_mode is None and len(seen) == 1
    assert "sk-secret" not in err.detail
    invalid, _ = compat_server({"json_schema"}, content="not json")
    err, _ = run(compat(invalid).complete_json(MSGS, SCHEMA, 5))
    assert isinstance(err, LLMError) and err.kind == "invalid-json"
    none, _ = compat_server(set())
    err, _ = run(compat(none).complete_json(MSGS, SCHEMA, 5))
    assert isinstance(err, LLMError) and "rejected every JSON output mode" in err.detail


def test_openai_compat_options_and_forced_mode() -> None:
    transport, seen = compat_server({"json_schema", "json_object", "prompt"})
    llm = compat(transport, max_tokens=80, reasoning_effort="", json_mode="json_object")
    run(llm.complete_json(MSGS, SCHEMA, 5))
    body = seen[0]["body"]
    assert body["max_tokens"] == 80 and "reasoning_effort" not in body and body["response_format"] == {"type": "json_object"}
    with pytest.raises(ValueError):
        compat(transport, json_mode="xml")
    assert extract_json('Sure: {"a": 1} done') == '{"a": 1}'


def test_openai_compat_from_env() -> None:
    env = {"ACLOPI_LLM_PROVIDER": "openai_compat", "ACLOPI_LLM_BASE_URL": "http://x/v1", "ACLOPI_LLM_API_KEY": "k"}
    llm = client_from_env(env)
    assert isinstance(llm, OpenAICompatLLM) and llm.model == "strata" and llm.max_tokens == 200
    assert llm.reasoning_effort == "none" and llm.timeout_s == 30 and llm.json_mode is None
    llm = client_from_env({**env, "ACLOPI_LLM_MODEL": "m", "ACLOPI_LLM_MAX_TOKENS": "64", "ACLOPI_LLM_TIMEOUT_S": "7",
                           "ACLOPI_LLM_REASONING_EFFORT": "low", "ACLOPI_LLM_JSON_MODE": "prompt"})
    assert (llm.model, llm.max_tokens, llm.timeout_s, llm.reasoning_effort, llm.json_mode) == ("m", 64, 7.0, "low", "prompt")
    assert client_from_env({**env, "ACLOPI_LLM_REASONING_EFFORT": ""}).reasoning_effort == ""
    with pytest.raises(RuntimeError, match="ACLOPI_LLM_API_KEY"):
        client_from_env({**env, "ACLOPI_LLM_API_KEY": ""})


def test_prompt_asks_for_short_english_reasons() -> None:
    assert "in English, at most 120 characters" in big_prompt()[0]["content"]
