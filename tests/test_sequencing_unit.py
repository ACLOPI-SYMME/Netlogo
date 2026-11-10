"""Order of a product list (aclopi.agent.sequencing): largest_first, the LLM proposal and POST
/sequence/propose of the agent service, with the fake LLM. No NetLogo, no network."""

from __future__ import annotations

import asyncio
from typing import Any

import httpx

from aclopi.agent.llm.base import LLMClient, token_limit
from aclopi.agent.llm.fake import FakeLLM
from aclopi.agent.sequencing import (HEURISTIC_REASONING, REASONING_MAX, TYPE_OPERATIONS, build_messages, largest_first,
                                     propose, valid_orders)
from aclopi.agent.service import AgentSettings, create_app

LIST_20 = ["A"] * 8 + ["B"] * 6 + ["I"] * 3 + ["E"] * 3


class FixedLLM(LLMClient):
    def __init__(self, answer: Any, latency_s: float = 0.0) -> None:
        self.answer, self.latency_s, self.limits = answer, latency_s, []

    async def _complete(self, messages: Any, schema: dict[str, Any], timeout_s: float) -> Any:
        self.limits.append(token_limit(200))
        await asyncio.sleep(self.latency_s)
        return self.answer


def types(order: list[int], products: list[str]) -> str:
    return "".join(products[i] for i in order)


def test_operation_counts_match_the_task() -> None:
    assert {t: len(ops) for t, ops in TYPE_OPERATIONS.items()} == {"A": 7, "B": 7, "L": 7, "E": 6, "I": 4, "P": 4, "T": 4}


def test_largest_first_groups_and_alternates() -> None:
    products = ["I", "A", "E", "B", "L", "T", "A", "P", "B", "E"]
    order = largest_first(products)
    assert sorted(order) == list(range(len(products)))
    assert types(order, products) == "ABABLEEITP"  # 7 ops, then 6, then 4; no type twice in a row inside a group
    order = largest_first(LIST_20)
    assert types(order, LIST_20) == "ABABABABABABAA" + "EEE" + "III"  # A repeats only when B ran out
    assert [i for i in order if LIST_20[i] == "A"] == list(range(8))  # each type keeps list order
    assert largest_first([{"type": "t", "priority": 70}, ("A", 80), "e"]) == [1, 2, 0]


def test_valid_orders_keep_complete_permutations_only() -> None:
    long = "x" * 300
    data = {"orders": [{"order": [2, 0, 1], "reasoning": long}, {"order": [0, 1], "reasoning": "short"},
                       {"order": [2, 0, 1], "reasoning": "repeated"}, {"order": [0, 0, 1], "reasoning": "dup"},
                       {"order": [True, 0, 2], "reasoning": "bool"}, {"order": [1, 2, 0], "reasoning": "ok"}]}
    kept, discarded = valid_orders(data, 3)
    assert [k["order"] for k in kept] == [[2, 0, 1], [1, 2, 0]] and discarded == 4
    assert len(kept[0]["reasoning"]) <= REASONING_MAX and kept[0]["reasoning"].endswith("…")
    assert valid_orders({"orders": "no"}, 3) == ([], 0) and valid_orders(None, 3) == ([], 0)


def test_prompt_has_the_plant_facts() -> None:
    system, user = (m["content"] for m in build_messages(LIST_20))
    assert "A: O1 O1 O1 O2 O4 O3 O5 (7 operations)" in system and "O1: M2 M3 M5 M7" in system
    assert "every 100 u.t." in system and "fewer than 10 products" in system and "O8" in system
    assert "at most 200 characters" in system and "2 DIFFERENT orders" in system
    assert "20 products (8 A, 6 B, 3 E, 3 I)" in user and "\n0: A\n" in user and "\n19: E" in user


def test_propose_with_the_fake_llm() -> None:
    out = asyncio.run(propose(FakeLLM(), [{"type": t} for t in LIST_20]))
    assert [o["order"] for o in out["orders"]] == [list(range(19, -1, -1)), list(range(1, 20)) + [0]]
    assert out["heuristic"] == {"order": largest_first(LIST_20), "reasoning": HEURISTIC_REASONING}
    assert out["error"] is None and out["latency_ms"] >= 0


def test_propose_asks_for_enough_tokens_and_survives_failures() -> None:
    llm = FixedLLM({"orders": [{"order": [1, 0], "reasoning": "r"}]})
    out = asyncio.run(propose(llm, ["A", "B"]))
    assert out["orders"] == [{"order": [1, 0], "reasoning": "r"}] and llm.limits[0] > 200
    assert token_limit(200) == 200  # only inside the call
    for answer, error in (({"orders": [{"order": [0], "reasoning": "r"}]}, "no-valid-order"),
                          ("{not json", "llm-invalid-json")):
        out = asyncio.run(propose(FixedLLM(answer), ["A", "B"]))
        assert out["orders"] == [] and out["error"] == error and out["heuristic"]["order"] == [0, 1]
    out = asyncio.run(propose(FixedLLM({}, latency_s=1.0), ["A", "B"], timeout_s=0.1))
    assert out["orders"] == [] and out["error"] == "llm-timeout" and out["latency_ms"] < 1000


def test_endpoint_token_validation_and_llm_down(tmp_path) -> None:
    async def run(llm: LLMClient) -> list[httpx.Response]:
        settings = AgentSettings(token="tok", log_path=str(tmp_path / "d.jsonl"))
        app = create_app(settings, llm=llm)
        auth = {"Authorization": "Bearer tok"}
        body = {"products": [{"type": t, "priority": 80} for t in LIST_20]}
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://agent") as c:
            return [await c.post("/sequence/propose", json=body),
                    await c.post("/sequence/propose", json=body, headers=auth),
                    await c.post("/sequence/propose", json={"products": [{"type": "Z"}]}, headers=auth),
                    await c.post("/sequence/propose", json={"products": []}, headers=auth)]

    no_token, ok, bad_type, empty = asyncio.run(run(FakeLLM()))
    assert no_token.status_code == 401 and bad_type.status_code == 422 and empty.status_code == 422
    body = ok.json()
    assert ok.status_code == 200 and set(body) == {"orders", "heuristic", "latency_ms", "error"}
    assert len(body["orders"]) == 2 and all(sorted(o["order"]) == list(range(20)) for o in body["orders"])
    down = asyncio.run(run(FakeLLM(invalid_rate=1.0)))[1]
    assert down.status_code == 200 and down.json()["orders"] == [] and down.json()["heuristic"]["reasoning"] == "Longest first"
