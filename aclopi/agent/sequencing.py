"""Entry order of a product list, for the "Optimize order" button (docs/sequencing.md).

    largest_first(products) -> [indices]      heuristic without an LLM
    await propose(llm, products, evaluated, strategy, mode, timeout_s, effort)
        answer of the agent service's POST /sequence/propose:
        {"orders": [{"order", "reasoning"}] (0-2, from the LLM), "analysis", "heuristic": {"order",
         "reasoning"}, "latency_ms", "error"}
Indices are 0-based positions in `products`; an order is a permutation of all of them. The prompt has
the plant facts read from the model (aclopi.agent.sequencing_context), the figures of the list and the
orders already simulated ("evaluated", with simulate_list's details): the LLM explains why the best one
loses time and proposes 2 new orders. Orders that are not a complete permutation, repeat each other or
repeat an evaluated order are discarded. If the LLM fails (timeout, invalid JSON, provider error) the
answer has no orders, only the heuristic.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Literal, Mapping, Sequence

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from aclopi.agent.llm import LLMClient
from aclopi.agent.llm.base import LLMError, call_options
from aclopi.agent.sequencing_context import ROUTING, list_figures, load_plant
from aclopi.agent.strategies import short_reason

logger = logging.getLogger(__name__)

MAX_PRODUCTS = 100
REASONING_MAX = 300
HEURISTIC_REASONING = "Longest first"
TIMEOUT_S = 90.0
EFFORT = "medium"
EFFORTS = ("none", "low", "medium")
MIN_TOKENS = 8000  # room for the reasoning tokens (reasoning_effort) and the answer
FAST_TIMEOUT_S = 30.0  # reasoning "none": no reasoning tokens, a short answer
FAST_MIN_TOKENS = 1000
TOKENS_PER_PRODUCT = 6  # the 2 orders: ~2 tokens per index each, plus margin
PROMPT_BUDGET = 30_000  # tokens (characters / 4) before the details are cut to the best FULL_DETAILS_KEPT
FULL_DETAILS_KEPT = 3


def product_type(p: Any) -> str:
    """Type of a product given as {"type": ...}, a (type, priority) pair or a bare type."""
    t = p.get("type") if isinstance(p, Mapping) else (p if isinstance(p, str) else p[0])
    return str(t).strip().upper()


def _operations(plant: dict[str, Any], t: str) -> int:
    return sum(o not in plant["machines"][plant["load_unload_machine"]] for o in plant["types"][t])


def largest_first(products: Sequence[Any], plant: dict[str, Any] | None = None) -> list[int]:
    """Types with more operations first (O8 / O9 not counted: A, B, L: 7; E: 6; I, P, T: 4). Inside each
    group the next product is of the type with the most products left that is not the type just placed
    (ties: the type seen first in the list), so the same type is repeated only when nothing else is
    left. Each type keeps its products in list order."""
    plant = plant or load_plant()
    types = [product_type(p) for p in products]
    unknown = sorted(set(types) - set(plant["types"]))
    if unknown:
        raise ValueError(f"unknown product types {unknown}")
    first_seen = {t: types.index(t) for t in set(types)}
    order: list[int] = []
    for size in sorted({_operations(plant, t) for t in types}, reverse=True):
        left = {t: [i for i, x in enumerate(types) if x == t] for t in first_seen if _operations(plant, t) == size}
        last = types[order[-1]] if order else None
        while any(left.values()):
            choices = [t for t in left if left[t] and t != last] or [t for t in left if left[t]]
            t = min(choices, key=lambda x: (-len(left[x]), first_seen[x]))
            order.append(left[t].pop(0))
            last = t
    return order


# ----- prompt -----

def _fmt(x: float) -> str:
    return f"{x:g}"


def system_prompt(plant: dict[str, Any], strategy: str, mode: str) -> str:
    m1 = plant["load_unload_machine"]
    ex, entry = plant["stochastic_extra"], plant["entry"]
    machines = "\n".join(f"  {m}: " + ", ".join(f"{o} {_fmt(t)}" for o, t in ops.items())
                         for m, ops in plant["machines"].items())
    names = list(plant["distances"])
    dist = "\n".join(f"  {a:>3} " + " ".join(f"{plant['distances'][a][b]:>6g}" for b in names) for a in names)
    extra = (f"Mode {mode}: each operation on {', '.join(ex['machines'])} takes its time plus a random "
             f"exponential extra of mean {_fmt(ex['mean'])} u.t.; {m1} has no extra." if mode == "Stochastic" else
             f"Mode {mode}: processing times are exactly the ones above (no random extra; in Stochastic mode "
             f"{', '.join(ex['machines'])} add an exponential extra of mean {_fmt(ex['mean'])} u.t.).")
    return f"""You plan the ENTRY ORDER of a list of products into a simulated monorail plant, to finish the
WHOLE list as early as possible (minimum makespan). Every order you propose is simulated and you get
the results back; use them.

PLANT (read from the simulation model; times in simulated time units, u.t.; 1 tick = {_fmt(plant['tick_time'])} u.t.)
- Machines, operations they can do and processing time (Machine.Operations.Time, u.t.):
{machines}
- {m1} loads and unloads: EVERY product starts with O8 and ends with O9 on {m1}, so {m1} is shared by all.
- {extra}
- Travel time between machines (u.t., row = from, column = to; 0 = staying on the same machine,
  which also skips that machine's queue):
      {' '.join(f'{b:>6}' for b in names)}
{dist}

ENTRY RULE
- Products enter in list order. The model checks the entry when the simulated time is within
  {_fmt(entry['window'])} u.t. after a multiple of {_fmt(entry['period'])} u.t. (time advances {_fmt(plant['time_step']['step'])} u.t. per tick, so some
  {_fmt(entry['period'])} u.t. windows get no check). A new product enters only if there are fewer than {entry['wip_max']} products
  in the plant AND no product is in the entry zone next to {m1} (x {_fmt(entry['zone']['xcor'][0])}-{_fmt(entry['zone']['xcor'][1])}, y {_fmt(entry['zone']['ycor'][0])}-{_fmt(entry['zone']['ycor'][1])} of the
  plant layout). A missed check waits for the next one.
- A new product needs {_fmt(entry['entry_travel'])} u.t. to reach {m1}.

ROUTING ({strategy}): {ROUTING.get(strategy, strategy)}

ANSWER: only the JSON object requested.
- "analysis": at most {REASONING_MAX} characters, why the best evaluated order loses time, with the
  numbers of its details (idle time of {m1}, missed entry checks, last product, occupancy, lower bound).
- "orders": 2 NEW orders that correct that, different from every evaluated order. Each "order" lists
  every index of the list exactly once. Each "reasoning": at most {REASONING_MAX} characters, what you changed
  and why it should finish earlier. Write in English.
- NUMBERS: cite only numbers that appear in the data you were given (makespans, details of the evaluated
  orders, precomputed figures). Do NOT estimate times of your own (no "finishes by ~X", no predicted
  makespan or entry tick for a new order): describe the expected effect without a number."""


def _types(order: Sequence[int], types: Sequence[str]) -> str:
    return "".join(types[i] for i in order)


def user_prompt(plant: dict[str, Any], products: Sequence[Any], evaluated: Sequence[Mapping[str, Any]],
                strategy: str, mode: str, with_details: set[int] | None = None) -> str:
    """with_details: positions in `evaluated` whose details are shown (None: all); the others show only
    their makespan."""
    types = [product_type(p) for p in products]
    fig = list_figures(plant, types, strategy, mode)
    m1 = plant["load_unload_machine"]
    tk = float(plant["tick_time"])
    counts = ", ".join(f"{types.count(t)} {t}" for t in plant["types"] if t in types)
    lines = [f"LIST: {len(types)} products ({counts}). Index: type, in the current order:",
             " ".join(f"{i}:{t}" for i, t in enumerate(types)), "",
             "PRODUCT TYPES IN THE LIST (min_time = from creation to the end of O9 with no waiting: "
             "entry travel + processing + travel on the best route)"]
    for t, info in fig["types"].items():
        steps = " ".join(f"{o}[{'/'.join(ms)}]" for o, ms in zip(info["sequence"], info["machines_per_step"]))
        lines.append(f"- {t} x{info['count']}: {steps}; work {_fmt(info['work'])} u.t.; "
                     f"min_time {_fmt(info['min_time'])} u.t. ({round(info['min_time'] / tk)} ticks) via {'-'.join(info['best_route'])}")
    lb = fig["lower_bound"]
    lines += ["", "FIGURES OF THE LIST (u.t.)",
              "- Work per operation: " + ", ".join(f"{o} {_fmt(w)}" for o, w in fig["work_per_operation"].items()),
              "- Work each machine could take (sum of the operations it can do): "
              + ", ".join(f"{m} {_fmt(w)}" for m, w in fig["work_per_possible_machine"].items()),
              f"- {m1} load (O8 + O9 of all): {_fmt(fig['m1_load'])} u.t.",
              f"- Earliest entries (one per entry check, if nothing blocks): first {_fmt(fig['earliest_entries'][0])}, "
              f"last {_fmt(fig['earliest_entries'][-1])} u.t.",
              f"- Lower bound of the makespan in the current order: {lb['ticks']} ticks ({_fmt(lb['value'])} u.t.) = max("
              f"{m1} bound {_fmt(lb['m1'])}: first arrival + {m1} load; path bound {_fmt(lb['path'])}: earliest entry + "
              f"min_time, worst for index {lb['path_product']})"]
    if evaluated:
        best = min(evaluated, key=lambda e: (e.get("makespan_ticks") is None, e.get("makespan_ticks") or 0))
        lines += ["", "EVALUATED ORDERS (simulated; makespan in ticks; idle = ticks without processing; "
                  "missed = entry checks missed because the zone was occupied / the plant was full)"]
        # details come from simulate_list on the list in that order: their "index" / "last" are positions
        # in the order; order[position] is the index in this list.
        for k, e in enumerate(evaluated):
            d = (e.get("details") or {}) if with_details is None or k in with_details else {}
            row = f"{k}. {_types(e['order'], types)} order {list(e['order'])}: makespan {e.get('makespan_ticks')}"
            if d:
                w = d["entry_windows"]
                occ = " ".join(f"{m} {v:g}%" for m, v in d["occupancy"].items())
                last = e["order"][d["last"]]
                row += (f"; last: index {last} ({types[last]}, position {d['last']}); {m1} idle {d['m1_idle']['total_ticks']}; "
                        f"missed zone {w['zone_busy']} / full {w['wip_full']} of {w['checks']} checks; occupancy {occ}")
            lines.append(row + (" <- BEST" if e is best else ""))
        d = best.get("details")
        if d:
            longest = sorted(d["m1_idle"]["intervals"], key=lambda iv: iv[0] - iv[1])[:6]
            lines += ["", f"DETAILS OF THE BEST ({best.get('makespan_ticks')} ticks, "
                      f"{best.get('makespan_ticks', 0) - lb['ticks']} above the lower bound of the current order)",
                      "position: index type entry_tick start_tick end_tick (entry = created; start = O8 starts on M1)"]
            for p in sorted(d["products"], key=lambda p: p["index"]):
                i = best["order"][p["index"]]
                lines.append(f"  {p['index']}: {i} {types[i]} {p['entry_tick']} {p['start_tick']} {p['end_tick']}")
            lines.append(f"- {m1} idle intervals, longest first (ticks): "
                         + ", ".join(f"[{a}-{b}]" for a, b in sorted(longest)))
    else:
        lines += ["", "EVALUATED ORDERS: none yet."]
    lines += ["", f"Give the analysis and 2 NEW orders of the indices 0-{len(types) - 1}."]
    return "\n".join(lines)


def prompt_tokens(messages: Sequence[Mapping[str, str]]) -> int:
    """Approximate size of a prompt in tokens: characters / 4."""
    return sum(len(m["content"]) for m in messages) // 4


def best_positions(evaluated: Sequence[Mapping[str, Any]], k: int) -> set[int]:
    """Positions of the k evaluated orders with the lowest makespan (None last; ties: first given)."""
    ranked = sorted(range(len(evaluated)), key=lambda i: (evaluated[i].get("makespan_ticks") is None,
                                                           evaluated[i].get("makespan_ticks") or 0, i))
    return set(ranked[:k])


def build_messages(products: Sequence[Any], evaluated: Sequence[Mapping[str, Any]] = (), strategy: str = "b1b",
                   mode: str = "Deterministic", plant: dict[str, Any] | None = None,
                   budget: int | None = PROMPT_BUDGET) -> list[dict[str, str]]:
    """Over `budget` tokens (prompt_tokens), only the FULL_DETAILS_KEPT best evaluated orders keep their
    details; the others show only their makespan."""
    plant = plant or load_plant()
    system = {"role": "system", "content": system_prompt(plant, strategy, mode)}
    messages = [system, {"role": "user", "content": user_prompt(plant, products, evaluated, strategy, mode)}]
    if budget is not None and prompt_tokens(messages) > budget and len(evaluated) > FULL_DETAILS_KEPT:
        keep = best_positions(evaluated, FULL_DETAILS_KEPT)
        messages = [system, {"role": "user", "content": user_prompt(plant, products, evaluated, strategy, mode, keep)}]
        logger.info("sequence: prompt over %d tokens; details of the %d best orders only (%d tokens)",
                    budget, FULL_DETAILS_KEPT, prompt_tokens(messages))
    return messages


def answer_schema(n: int) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "analysis": {"type": "string"},
            "orders": {"type": "array", "minItems": 1, "maxItems": 2, "items": {
                "type": "object",
                "properties": {"order": {"type": "array", "minItems": n, "maxItems": n,
                                         "items": {"type": "integer", "minimum": 0, "maximum": n - 1}},
                               "reasoning": {"type": "string"}},
                "required": ["order", "reasoning"]}}},
        "required": ["analysis", "orders"],
    }


def valid_orders(data: Any, n: int, evaluated: Sequence[Sequence[int]] = ()) -> tuple[list[dict[str, Any]], int]:
    """The orders of an answer that are complete permutations of range(n), not evaluated already and
    without repeats (at most 2), and how many were discarded."""
    items = data.get("orders") if isinstance(data, dict) else None
    if not isinstance(items, list):
        return [], 0
    seen = [list(o) for o in evaluated]
    kept: list[dict[str, Any]] = []
    for item in items:
        order = item.get("order") if isinstance(item, dict) else None
        ok = (isinstance(order, list) and all(isinstance(i, int) and not isinstance(i, bool) for i in order)
              and sorted(order) == list(range(n)))
        if ok and len(kept) < 2 and order not in seen:
            seen.append(list(order))
            kept.append({"order": list(order), "reasoning": short_reason(str(item.get("reasoning") or ""), REASONING_MAX)})
    return kept, len(items) - len(kept)


async def propose(llm: LLMClient, products: Sequence[Any], evaluated: Sequence[Mapping[str, Any]] = (),
                  strategy: str = "b1b", mode: str = "Deterministic", timeout_s: float = TIMEOUT_S,
                  effort: str | None = EFFORT, min_tokens: int | None = None,
                  budget: int | None = PROMPT_BUDGET) -> dict[str, Any]:
    """min_tokens: max_tokens of the call, plus TOKENS_PER_PRODUCT per product (default: MIN_TOKENS, or
    FAST_MIN_TOKENS with effort "none")."""
    start = time.perf_counter()
    n = len(products)
    plant = load_plant()
    heuristic = {"order": largest_first(products, plant), "reasoning": HEURISTIC_REASONING}
    messages = build_messages(products, evaluated, strategy, mode, plant, budget)
    if min_tokens is None:
        min_tokens = FAST_MIN_TOKENS if effort == "none" else MIN_TOKENS
    with call_options(min_tokens=min_tokens + TOKENS_PER_PRODUCT * n, reasoning_effort=effort, timeout_s=timeout_s):
        data, _ = await llm.complete_json(messages, answer_schema(n), timeout_s)
    analysis = None
    if isinstance(data, LLMError):
        orders, error = [], f"llm-{data.kind}"
        logger.warning("sequence: LLM failed (%s: %s); heuristic only", data.kind, data.detail[:120])
    else:
        orders, discarded = valid_orders(data, n, [e["order"] for e in evaluated])
        analysis = short_reason(str(data.get("analysis") or ""), REASONING_MAX) or None
        error = None if orders else "no-valid-order"
        if discarded:
            logger.info("sequence: %d order(s) of the LLM discarded", discarded)
    return {"orders": orders, "analysis": analysis, "heuristic": heuristic,
            "latency_ms": round(1000 * (time.perf_counter() - start), 1), "error": error}


class SequenceProduct(BaseModel):
    model_config = ConfigDict(extra="ignore")

    type: str
    priority: int | None = None

    @field_validator("type")
    @classmethod
    def _known(cls, v: str) -> str:
        t = v.strip().upper()
        if t not in load_plant()["types"]:
            raise ValueError(f"type must be one of {', '.join(load_plant()['types'])}")
        return t


class Evaluated(BaseModel):
    model_config = ConfigDict(extra="ignore")

    order: list[int]
    makespan_ticks: int | None = None
    details: dict[str, Any] | None = None


class SequenceRequest(BaseModel):
    products: list[SequenceProduct] = Field(min_length=1, max_length=MAX_PRODUCTS)
    evaluated: list[Evaluated] = Field(default_factory=list, max_length=50)
    strategy: str = "b1b"
    mode: str = "Deterministic"
    reasoning: Literal["none", "low", "medium"] | None = None  # None: ACLOPI_SEQUENCE_REASONING

    @model_validator(mode="after")
    def _check(self) -> "SequenceRequest":
        n = len(self.products)
        for e in self.evaluated:
            if sorted(e.order) != list(range(n)):
                raise ValueError(f"every evaluated order must be a permutation of 0-{n - 1}")
            got = [str(p.get("type")) for p in sorted((e.details or {}).get("products") or [], key=lambda p: p.get("index", 0))]
            if got and got != [self.products[i].type for i in e.order]:
                raise ValueError("details.products must be the run of the list in that order (types by position)")
        if self.strategy not in ROUTING:
            raise ValueError(f"strategy must be one of {', '.join(ROUTING)}")
        if self.mode not in ("Deterministic", "Stochastic"):
            raise ValueError("mode must be Deterministic or Stochastic")
        return self
