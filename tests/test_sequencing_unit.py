"""Order of a product list: the plant context and figures (aclopi.agent.sequencing_context), details of a
run (aclopi.sim.sequencing.compute_details), largest_first, the prompt and POST /sequence/propose of the
agent service, with fake LLMs. No NetLogo, no network."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx
import pytest

from aclopi.agent.llm.base import LLMClient, call_options, http_timeout, reasoning_effort, token_limit
from aclopi.agent.llm.fake import FakeLLM
from aclopi.agent.llm.openai_compat import OpenAICompatLLM
from aclopi.agent.sequencing import (HEURISTIC_REASONING, REASONING_MAX, build_messages, largest_first, propose,
                                     valid_orders)
from aclopi.agent.sequencing_context import entry_checks, list_figures, load_plant, min_route, parse_model_rules
from aclopi.agent.service import AgentSettings, create_app
from aclopi.sim.sequencing import compute_details

LIST_20 = ["A"] * 8 + ["B"] * 6 + ["I"] * 3 + ["E"] * 3

# A small plant with known answers
TOY = {
    "tick_time": 0.31, "load_unload_machine": "M1",
    "entry": {"period": 100.0, "window": 0.2, "wip_max": 10, "zone": {"xcor": [90, 115], "ycor": [80, 110]},
              "entry_travel": 10.0},
    "time_step": {"step": 0.31, "decimals": 2},
    "stochastic_extra": {"distribution": "exponential", "mean": 10.0, "machines": ["M2", "M3"]},
    "machines": {"M1": {"O8": 100.0, "O9": 100.0}, "M2": {"O1": 200.0}, "M3": {"O1": 200.0, "O2": 200.0}},
    "capable": {"O1": ["M2", "M3"], "O2": ["M3"], "O8": ["M1"], "O9": ["M1"]},
    "distances": {"M1": {"M1": 0, "M2": 10, "M3": 30}, "M2": {"M1": 10, "M2": 0, "M3": 5},
                  "M3": {"M1": 30, "M2": 5, "M3": 0}},
    "types": {"X": ["O8", "O1", "O2", "O9"]},
}


class FixedLLM(LLMClient):
    def __init__(self, answer: Any, latency_s: float = 0.0) -> None:
        self.answer, self.latency_s, self.seen, self.prompts = answer, latency_s, [], []

    async def _complete(self, messages: Any, schema: dict[str, Any], timeout_s: float) -> Any:
        self.seen.append((token_limit(200), reasoning_effort("none"), http_timeout(timeout_s, 30)))
        self.prompts.append(messages)
        await asyncio.sleep(self.latency_s)
        return self.answer


def types(order: list[int], products: list[str]) -> str:
    return "".join(products[i] for i in order)


# ----- plant context and figures -----

def test_entry_checks_follow_the_time_step() -> None:
    # 0.31 u.t. per tick, rounded to 2 decimals: the window after 200 gets no check (199.95, 200.26)
    assert entry_checks(TOY, 6) == [100.13, 300.08, 500.03, 600.16, 800.11, 1000.06]


def test_min_route_and_list_figures() -> None:
    assert min_route(TOY, TOY["types"]["X"], "Deterministic") == (645.0, ["M1", "M2", "M3", "M1"])
    assert min_route(TOY, TOY["types"]["X"], "Stochastic")[0] == 665.0  # +10 on M2 and M3
    f = list_figures(TOY, ["X", "X"])
    assert f["types"]["X"] == {"count": 2, "sequence": ["O8", "O1", "O2", "O9"], "work": 600.0,
                               "machines_per_step": [["M1"], ["M2", "M3"], ["M3"], ["M1"]],
                               "min_time": 655.0, "best_route": ["M1", "M2", "M3", "M1"]}
    assert f["work_per_operation"] == {"O1": 400.0, "O2": 400.0, "O8": 200.0, "O9": 200.0}
    assert f["work_per_possible_machine"] == {"M1": 400.0, "M2": 400.0, "M3": 800.0}
    assert f["m1_load"] == 400.0 and f["earliest_entries"] == [100.13, 300.08]
    assert f["lower_bound"] == {"m1": 510.13, "path": 955.08, "path_product": 1, "value": 955.08, "ticks": 3081}


def test_plant_file_has_the_model_facts() -> None:
    plant = load_plant()
    assert plant["machines"]["M2"] == {"O1": 200.0, "O2": 200.0, "O4": 200.0} and plant["capable"]["O1"] == ["M2", "M3", "M5", "M7"]
    assert {t: sum(o not in ("O8", "O9") for o in ops) for t, ops in plant["types"].items()} == \
        {"A": 7, "B": 7, "L": 7, "E": 6, "I": 4, "P": 4, "T": 4}
    assert plant["entry"]["wip_max"] == 10 and plant["entry"]["period"] == 100 and plant["load_unload_machine"] == "M1"
    assert plant["distances"]["M1"]["M2"] == 111.3 and plant["distances"]["M3"]["M3"] == 0.0


def test_parse_model_rules() -> None:
    text = """to Go
  let counter count products with [xcor >= 90 and xcor <= 115 and ycor >= 80 and ycor <= 110]
  if (simulated.time mod 100 <= 0.2 and count products with [Product.State != "death"] < 10 and counter = 0) [ ]
end
to Product.Movement
  set simulated.time precision (simulated.time + 0.31) 2
end
if (Modeling.Type = "Stochastic") [set Next.Completion Simulated.Time + 100]
if (Modeling.Type = "Stochastic") [set Next.Completion Simulated.Time + 200 + precision (random-exponential 10) 2]
"""
    r = parse_model_rules(text)
    assert r["entry"] == {"period": 100.0, "window": 0.2, "wip_max": 10, "zone": {"xcor": [90.0, 115.0], "ycor": [80.0, 110.0]}}
    assert r["time_step"] == {"step": 0.31, "decimals": 2} and r["stochastic_extra"]["mean"] == 10.0
    with pytest.raises(ValueError):
        parse_model_rules("to Go\nend\n")


# ----- details of a run -----

ROWS = [[200, "X", 100.13, [113.77, 400.0, 700.0], [213.77, 600.0, 800.0], ["M1", "M2", "M1"]],
        [201, "X", 800.11, [813.75, 1000.0], [913.75, 1100.0], ["M1", "M1"]]]


def test_compute_details() -> None:
    d = compute_details(ROWS, TOY, 1100.0)
    assert d["products"] == [{"index": 0, "type": "X", "entry_tick": 323, "start_tick": 367, "end_tick": 2581},
                             {"index": 1, "type": "X", "entry_tick": 2581, "start_tick": 2625, "end_tick": 3548}]
    assert d["last"] == 1 and d["occupancy"] == {"M1": 36.4, "M2": 18.2}
    assert d["m1_idle"] == {"intervals": [[0, 367], [690, 2258], [2581, 2625], [2948, 3226]], "total_ticks": 2257}
    # checks until the last creation: 100.13 created, 300.08 / 500.03 / 600.16 missed (product 0 alive), 800.11 created
    assert d["entry_windows"] == {"checks": 5, "created": 2, "zone_busy": 3, "wip_full": 0}
    full = compute_details(ROWS, {**TOY, "entry": {**TOY["entry"], "wip_max": 1}}, 1100.0)
    assert full["entry_windows"] == {"checks": 5, "created": 2, "zone_busy": 0, "wip_full": 3}


# ----- heuristic -----

def test_largest_first_groups_and_alternates() -> None:
    products = ["I", "A", "E", "B", "L", "T", "A", "P", "B", "E"]
    order = largest_first(products)
    assert sorted(order) == list(range(len(products)))
    assert types(order, products) == "ABABLEEITP"  # 7 ops, then 6, then 4; no type twice in a row inside a group
    order = largest_first(LIST_20)
    assert types(order, LIST_20) == "ABABABABABABAA" + "EEE" + "III"  # A repeats only when B ran out
    assert [i for i in order if LIST_20[i] == "A"] == list(range(8))  # each type keeps list order
    assert largest_first([{"type": "t", "priority": 70}, ("A", 80), "e"]) == [1, 2, 0]


# ----- prompt and answer -----

def test_valid_orders_discard_incomplete_repeated_and_evaluated() -> None:
    long = "x" * 400
    data = {"orders": [{"order": [2, 0, 1], "reasoning": long}, {"order": [0, 1], "reasoning": "short"},
                       {"order": [2, 0, 1], "reasoning": "repeated"}, {"order": [0, 0, 1], "reasoning": "dup"},
                       {"order": [True, 0, 2], "reasoning": "bool"}, {"order": [0, 1, 2], "reasoning": "evaluated"},
                       {"order": [1, 2, 0], "reasoning": "ok"}]}
    kept, discarded = valid_orders(data, 3, evaluated=[[0, 1, 2]])
    assert [k["order"] for k in kept] == [[2, 0, 1], [1, 2, 0]] and discarded == 5
    assert len(kept[0]["reasoning"]) <= REASONING_MAX == 300 and kept[0]["reasoning"].endswith("…")
    assert valid_orders({"orders": "no"}, 3) == ([], 0) and valid_orders(None, 3) == ([], 0)


def details_of(order: list[int]) -> dict[str, Any]:
    """Synthetic details shaped as simulate_list's on the list in that order (by position)."""
    return compute_details([[200 + k, LIST_20[i], 100.13, [113.77], [213.77 + k], ["M1"]] for k, i in enumerate(order)],
                           TOY, 300.0)


def evaluated_20() -> list[dict[str, Any]]:
    heuristic = largest_first(LIST_20)
    return [{"order": list(range(20)), "makespan_ticks": 27745, "details": details_of(list(range(20)))},
            {"order": heuristic, "makespan_ticks": 26612, "details": details_of(heuristic)}]


def test_prompt_has_the_plant_the_figures_and_the_evaluated_orders() -> None:
    system, user = (m["content"] for m in build_messages(LIST_20, evaluated_20()))
    assert "M2: O1 200, O2 200, O4 200" in system and "M1 loads and unloads" in system
    assert "111.3" in system and "fewer than 10 products" in system and "13.64 u.t. to reach M1" in system
    assert "lowest finish_plus_next" in system and "no random extra" in system
    assert f"at most {REASONING_MAX} characters" in system and "2 NEW orders" in system
    assert "20 products (8 A, 3 I, 6 B, 3 E)" in user and "0:A 1:A" in user and "19:E" in user
    assert "- A x8: O8[M1] O1[M2/M3/M5/M7]" in user and "work 1600 u.t." in user and "min_time" in user
    assert "M1 load (O8 + O9 of all): 4000 u.t." in user and "Lower bound of the makespan" in user
    assert "1. ABABABABABABAAEEEIII" in user and "26612" in user and "<- BEST" in user
    assert "DETAILS OF THE BEST (26612 ticks" in user and "M1 idle intervals" in user
    # details are by position: position 1 of the heuristic is index 8 (B); the last one is index 16 (I)
    assert "\n  1: 8 B " in user and "\n  19: 16 I " in user and "last: index 16 (I, position 19)" in user
    assert "missed zone" in user
    stochastic = build_messages(LIST_20, mode="Stochastic")[0]["content"]
    assert "exponential extra of mean 10 u.t." in stochastic


def test_propose_uses_its_own_reasoning_tokens_and_timeout() -> None:
    llm = FixedLLM({"analysis": "M1 idle 40 %", "orders": [{"order": [1, 0], "reasoning": "r"}]})
    out = asyncio.run(propose(llm, ["A", "B"], evaluated=[{"order": [0, 1], "makespan_ticks": 100}]))
    assert out["orders"] == [{"order": [1, 0], "reasoning": "r"}] and out["analysis"] == "M1 idle 40 %"
    assert llm.seen[0] == (8012, "medium", 90.0)
    assert (token_limit(200), reasoning_effort("none"), http_timeout(5.0, 30)) == (200, "none", 5.0)  # only inside
    with call_options(reasoning_effort="high"):
        assert reasoning_effort("none") == "high"


def test_propose_survives_failures() -> None:
    for answer, error in (({"analysis": "a", "orders": [{"order": [0], "reasoning": "r"}]}, "no-valid-order"),
                          ({"analysis": "a", "orders": [{"order": [0, 1], "reasoning": "evaluated"}]}, "no-valid-order"),
                          ("{not json", "llm-invalid-json")):
        out = asyncio.run(propose(FixedLLM(answer), ["A", "B"], evaluated=[{"order": [0, 1], "makespan_ticks": 1}]))
        assert out["orders"] == [] and out["error"] == error and out["heuristic"]["order"] == [0, 1]
    out = asyncio.run(propose(FixedLLM({}, latency_s=1.0), ["A", "B"], timeout_s=0.1))
    assert out["orders"] == [] and out["error"] == "llm-timeout" and out["latency_ms"] < 1000


def test_openai_compat_sends_the_sequencing_options() -> None:
    bodies: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        answer = {"analysis": "a", "orders": [{"order": [1, 0], "reasoning": "r"}]}
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(answer)}}]})

    llm = OpenAICompatLLM("http://llm/v1", "k", "strata", json_mode="json_schema", transport=httpx.MockTransport(handler))
    out = asyncio.run(propose(llm, ["A", "B"], effort="medium"))
    assert out["orders"] == [{"order": [1, 0], "reasoning": "r"}]
    assert bodies[0]["reasoning_effort"] == "medium" and bodies[0]["max_tokens"] == 8012
    asyncio.run(llm.complete_json([{"role": "user", "content": "x"}], {"type": "object"}, 5))
    assert bodies[1]["reasoning_effort"] == "none" and bodies[1]["max_tokens"] == 200  # decisions unchanged


def test_endpoint(tmp_path) -> None:
    async def run(llm: LLMClient, extra: dict[str, Any] | None = None) -> list[httpx.Response]:
        app = create_app(AgentSettings(token="tok", log_path=str(tmp_path / "d.jsonl")), llm=llm)
        auth = {"Authorization": "Bearer tok"}
        body = {"products": [{"type": t, "priority": 80} for t in LIST_20], **(extra or {})}
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://agent") as c:
            return [await c.post("/sequence/propose", json=body),
                    await c.post("/sequence/propose", json=body, headers=auth),
                    await c.post("/sequence/propose", json={"products": [{"type": "Z"}]}, headers=auth),
                    await c.post("/sequence/propose", json={"products": []}, headers=auth),
                    await c.post("/sequence/propose", json={**body, "evaluated": [{"order": [0, 1]}]}, headers=auth),
                    await c.post("/sequence/propose", headers=auth, json={**body, "evaluated": [  # details of another order
                        {"order": largest_first(LIST_20), "makespan_ticks": 1, "details": details_of(list(range(20)))}]})]

    no_token, ok, bad_type, empty, bad_eval, bad_details = asyncio.run(run(FakeLLM(), {"evaluated": evaluated_20()}))
    assert no_token.status_code == 401
    assert {bad_type.status_code, empty.status_code, bad_eval.status_code, bad_details.status_code} == {422}
    body = ok.json()
    assert ok.status_code == 200 and set(body) == {"orders", "analysis", "heuristic", "latency_ms", "error"}
    assert len(body["orders"]) == 2 and all(sorted(o["order"]) == list(range(20)) for o in body["orders"])
    # the fake answers the list reversed and rotated; evaluated: original and heuristic, so both are kept
    rotated = asyncio.run(run(FakeLLM(), {"evaluated": [{"order": list(range(19, -1, -1))}]}))[1].json()
    assert [o["order"] for o in rotated["orders"]] == [list(range(1, 20)) + [0]]  # the evaluated one discarded
    down = asyncio.run(run(FakeLLM(invalid_rate=1.0)))[1]
    assert down.status_code == 200 and down.json()["orders"] == [] and down.json()["heuristic"]["reasoning"] == HEURISTIC_REASONING
