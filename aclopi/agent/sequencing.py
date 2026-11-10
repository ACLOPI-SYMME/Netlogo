"""Entry order of a product list, for the "Optimize order" button (docs/sequencing.md).

    largest_first(products) -> [indices]      heuristic without an LLM
    await propose(llm, products, timeout_s)   answer of the agent service's POST /sequence/propose:
        {"orders": [{"order", "reasoning"}] (0-2, from the LLM), "heuristic": {"order", "reasoning"},
         "latency_ms", "error"}
Indices are 0-based positions in `products`; an order is a permutation of all of them. Orders of the
LLM that are not a complete permutation are discarded, and so is a repeated one. If the LLM fails
(timeout, invalid JSON, provider error) the answer has no orders, only the heuristic.
Plant facts from model/Paper.nlogo (AgregateOperations and the machines' Machine.Operations.Type).
"""

from __future__ import annotations

import logging
import time
from typing import Any, Mapping, Sequence

from pydantic import BaseModel, ConfigDict, Field, field_validator

from aclopi.agent.llm import LLMClient
from aclopi.agent.llm.base import LLMError, min_tokens
from aclopi.agent.strategies import short_reason

logger = logging.getLogger(__name__)

# Operations of each product type without O8 / O9 (on M1, first and last of every product)
TYPE_OPERATIONS: dict[str, tuple[str, ...]] = {
    "A": ("O1", "O1", "O1", "O2", "O4", "O3", "O5"),
    "B": ("O1", "O1", "O1", "O2", "O2", "O3", "O5"),
    "L": ("O1", "O1", "O1", "O3", "O3", "O5", "O5"),
    "E": ("O1", "O1", "O1", "O2", "O2", "O4"),
    "I": ("O1", "O1", "O3", "O5"),
    "P": ("O1", "O1", "O2", "O4"),
    "T": ("O1", "O1", "O2", "O4"),
}
MACHINE_OPERATIONS: dict[str, tuple[str, ...]] = {
    "M1": ("O8", "O9"), "M2": ("O1", "O2", "O4"), "M3": ("O1", "O2", "O5"), "M4": ("O3", "O4", "O5"),
    "M5": ("O1", "O3", "O5", "O6"), "M6": ("O2", "O3", "O4", "O6"), "M7": ("O1", "O2", "O3", "O4", "O5"),
}
MAX_PRODUCTS = 100
REASONING_MAX = 200
HEURISTIC_REASONING = "Longest first"
TIMEOUT_S = 30.0


def product_type(p: Any) -> str:
    """Type of a product given as {"type": ...}, a (type, priority) pair or a bare type."""
    t = p.get("type") if isinstance(p, Mapping) else (p if isinstance(p, str) else p[0])
    return str(t).strip().upper()


def largest_first(products: Sequence[Any]) -> list[int]:
    """Types with more operations first (A, B, L: 7; E: 6; I, P, T: 4). Inside each group the next
    product is of the type with the most products left that is not the type just placed (ties: the
    type seen first in the list), so the same type is repeated only when nothing else is left. Each
    type keeps its products in list order."""
    types = [product_type(p) for p in products]
    unknown = sorted(set(types) - set(TYPE_OPERATIONS))
    if unknown:
        raise ValueError(f"unknown product types {unknown}")
    first_seen = {t: types.index(t) for t in set(types)}
    order: list[int] = []
    for size in sorted({len(TYPE_OPERATIONS[t]) for t in types}, reverse=True):
        left = {t: [i for i, x in enumerate(types) if x == t] for t in first_seen if len(TYPE_OPERATIONS[t]) == size}
        last = types[order[-1]] if order else None
        while any(left.values()):
            choices = [t for t in left if left[t] and t != last] or [t for t in left if left[t]]
            t = min(choices, key=lambda x: (-len(left[x]), first_seen[x]))
            order.append(left[t].pop(0))
            last = t
    return order


# ----- LLM -----

SYSTEM = f"""You plan the ENTRY ORDER of a list of products into a monorail plant with 7 machines (M1-M7).

PLANT
- Every product starts with O8 and ends with O9, both on M1 (100 u.t. each). In between it does the
  operations of its type, in this order (200 u.t. each, plus about 10 random):
{chr(10).join(f"  {t}: {' '.join(ops)} ({len(ops)} operations)" for t, ops in TYPE_OPERATIONS.items())}
- Machines that can do each operation (the plant routes every operation to one of them):
{chr(10).join(f"  {o}: {' '.join(m for m, ops in MACHINE_OPERATIONS.items() if o in ops)}" for o in ("O1", "O2", "O3", "O4", "O5"))}
- Entry rule: a new product enters (in list order) every 100 u.t. if the entry zone of M1 is free and
  there are fewer than 10 products in the plant.

OBJECTIVE: finish the WHOLE list as early as possible (minimum makespan).

ANSWER: only the JSON object requested, with 2 DIFFERENT orders. Each "order" lists every index of
the list exactly once (a complete permutation). Each "reasoning": in English,
at most {REASONING_MAX} characters, why that order should finish early."""


def answer_schema(n: int) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {"orders": {"type": "array", "minItems": 1, "maxItems": 2, "items": {
            "type": "object",
            "properties": {"order": {"type": "array", "minItems": n, "maxItems": n,
                                     "items": {"type": "integer", "minimum": 0, "maximum": n - 1}},
                           "reasoning": {"type": "string"}},
            "required": ["order", "reasoning"]}}},
        "required": ["orders"],
    }


def build_messages(products: Sequence[Any]) -> list[dict[str, str]]:
    types = [product_type(p) for p in products]
    counts = ", ".join(f"{types.count(t)} {t}" for t in TYPE_OPERATIONS if t in types)
    lines = "\n".join(f"{i}: {t}" for i, t in enumerate(types))
    user = (f"List of {len(types)} products ({counts}), index: type, in the current order:\n{lines}\n\n"
            f"Give 2 different orders of the indices 0-{len(types) - 1}.")
    return [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}]


def valid_orders(data: Any, n: int) -> tuple[list[dict[str, Any]], int]:
    """The orders of an answer that are complete permutations of range(n), without repeats (at most 2),
    and how many were discarded."""
    items = data.get("orders") if isinstance(data, dict) else None
    if not isinstance(items, list):
        return [], 0
    kept: list[dict[str, Any]] = []
    for item in items:
        order = item.get("order") if isinstance(item, dict) else None
        ok = (isinstance(order, list) and all(isinstance(i, int) and not isinstance(i, bool) for i in order)
              and sorted(order) == list(range(n)))
        if ok and len(kept) < 2 and all(k["order"] != order for k in kept):
            kept.append({"order": list(order), "reasoning": short_reason(str(item.get("reasoning") or ""), REASONING_MAX)})
    return kept, len(items) - len(kept)


async def propose(llm: LLMClient, products: Sequence[Any], timeout_s: float = TIMEOUT_S) -> dict[str, Any]:
    start = time.perf_counter()
    n = len(products)
    heuristic = {"order": largest_first(products), "reasoning": HEURISTIC_REASONING}
    # an index costs ~2 tokens; 2 orders, 2 reasonings and the JSON around them
    with min_tokens(600 + 6 * n):
        data, _ = await llm.complete_json(build_messages(products), answer_schema(n), timeout_s)
    if isinstance(data, LLMError):
        orders, error = [], f"llm-{data.kind}"
        logger.warning("sequence: LLM failed (%s: %s); heuristic only", data.kind, data.detail[:120])
    else:
        orders, discarded = valid_orders(data, n)
        error = None if orders else "no-valid-order"
        if discarded:
            logger.info("sequence: %d order(s) of the LLM discarded", discarded)
    return {"orders": orders, "heuristic": heuristic, "latency_ms": round(1000 * (time.perf_counter() - start), 1),
            "error": error}


class SequenceProduct(BaseModel):
    model_config = ConfigDict(extra="ignore")

    type: str
    priority: int | None = None

    @field_validator("type")
    @classmethod
    def _known(cls, v: str) -> str:
        t = v.strip().upper()
        if t not in TYPE_OPERATIONS:
            raise ValueError(f"type must be one of {', '.join(TYPE_OPERATIONS)}")
        return t


class SequenceRequest(BaseModel):
    products: list[SequenceProduct] = Field(min_length=1, max_length=MAX_PRODUCTS)
