"""Prompt of the agent: fixed part first (role, objective, rules, examples; cacheable), variable part last.

    build_messages(...)            call 1 (uncertain: decide only; very_close: decide or what_if)
    build_messages(..., what_if=)  call 2, with the what-if results per option (decide only)
    answer_schema(machines, allow_what_if) and parse_answer(...) validate the answer with pydantic.
Times in the variable part are relative to now, in u.t. (1 tick = 0.31 u.t.). The reason is asked in
Spanish, at most 120 characters (the code cuts it anyway: aclopi.agent.strategies.short_reason).
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError, model_validator

SYSTEM = """You route products in a monorail plant with 7 machines (M1-M7). A product just entered a machine;
choose the machine for its NEXT operation among the candidates given.

OBJECTIVE: finish the WHOLE list of products as early as possible (minimum makespan), not only this
operation. A choice that is slightly slower for this product but keeps a busy machine free for the
others, or that leaves this product close to the machine of its following operation, can be better.

FACTS
- Times are in simulated time units (u.t.), relative to now. M1 does the first (O8) and last (O9)
  operation of every product and is the shared bottleneck at the plant entrance.
- finish = when this operation would end on that machine (travel, queue and products on their way
  included). finish_plus_next = finish + travel to the closest machine of the following operation.
- If the candidate is the machine the product is in, it is processed again in place: no travel and
  it goes ahead of that machine's queue.
- Estimates assume mean processing times (200 u.t. on M2-M7 plus about 10 random, 100 on M1).

RULES
- Answer only with the JSON object requested. "machine" must be one of the candidates.
- "reason": in Spanish, at most 120 characters, with the number that decided (it is shown to the
  plant operator), e.g. "M3 termina 220 u.t. antes".
- "what_if" (only when offered) simulates the two options given and returns, per option, when this
  operation ends and how the other products progress in the meantime. Ask for it only when the
  numbers are too close to choose.

EXAMPLES (synthetic)
1. Candidates: M3 finish +260 finish_plus_next +330 | M5 finish +480 finish_plus_next +540.
   -> {"action": "decide", "machine": "M3", "reason": "M3 termina 220 u.t. antes y también es mejor con el siguiente paso"}
2. Candidates: M2 finish +300 finish_plus_next +590 | M7 finish +330 finish_plus_next +420.
   -> {"action": "decide", "machine": "M7", "reason": "Solo 30 u.t. más tarde ahora, pero 170 u.t. antes con el siguiente paso"}
3. What-if: option M2 op_end_time +310, others work 420 wait 90 | option M4 op_end_time +330, others work 560 wait 40.
   -> {"action": "decide", "machine": "M4", "reason": "20 u.t. más para este producto; los demás avanzan 140 u.t. más y esperan menos"}
"""


class Answer(BaseModel):
    action: Literal["decide", "what_if"]
    machine: str | None = None
    reason: str | None = Field(None, max_length=500)

    @model_validator(mode="after")
    def _machine_when_deciding(self) -> "Answer":
        if self.action == "decide" and not self.machine:
            raise ValueError("decide needs a machine")
        return self


def answer_schema(machines: list[str], allow_what_if: bool) -> dict[str, Any]:
    """JSON schema of the answer: decide only, or decide | what_if (very close cases)."""
    actions = ["decide", "what_if"] if allow_what_if else ["decide"]
    schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": actions},
            "machine": {"type": "string", "enum": list(machines)},
            "reason": {"type": "string"},
        },
        "required": ["action", "reason"] if allow_what_if else ["action", "machine", "reason"],
        "additionalProperties": False,
    }
    return schema


def parse_answer(data: dict[str, Any], machines: list[str], allow_what_if: bool) -> Answer | str:
    """The validated answer, or why it is not valid."""
    try:
        answer = Answer(**data)
    except ValidationError as exc:
        return f"invalid-answer: {exc.errors()[0]['msg']}"
    if answer.action == "what_if" and not allow_what_if:
        return "what-if-not-offered"
    if answer.action == "decide" and answer.machine not in machines:
        return f"machine-not-candidate: {answer.machine}"
    return answer


def _row(c: dict[str, Any], now: float) -> str:
    def rel(v: Any) -> str:
        return "-" if v is None else f"+{float(v) - now:.0f}"

    def dur(v: Any) -> str:
        return "-" if v is None else f"{float(v):.0f}"

    here = " (current machine: in place)" if c.get("is_current_machine") else ""
    return (f"| {c['machine']}{here} | {rel(c.get('finish'))} | {dur(c.get('delta_finish'))} | {rel(c.get('finish_plus_next'))} | "
            f"{dur(c.get('delta_finish_plus_next'))} | {c.get('next_machine') or '-'} | {dur(c.get('travel'))} | "
            f"{dur(c.get('current_remaining'))} | {dur(c.get('queue_time'))} ({len(c.get('queue') or [])}) | "
            f"{dur(c.get('en_route_time'))} ({len(c.get('en_route') or [])}) |")


def _what_if_lines(what_if: dict[str, Any], now: float) -> list[str]:
    lines = [f"WHAT-IF RESULT (status {what_if.get('status')}"
             + (f", {what_if.get('skipped_reason')}" if what_if.get("skipped_reason") else "") + ")"]
    for o in what_if.get("options") or []:
        if o.get("skipped"):
            lines.append(f"- option {o['machine']}: not simulated")
            continue
        others = o.get("others") or {}
        est = " (estimated)" if o.get("op_end_estimated") or o.get("entry_estimated") else ""
        end = o.get("op_end_time")
        lines.append(f"- option {o['machine']}: op_end_time {(float(end) - now) if end is not None else float('nan'):.1f}{est}; "
                     f"others work {others.get('work', 0):.0f}, wait {others.get('wait', 0):.0f}, "
                     f"presence {others.get('presence', 0):.0f}, finished {others.get('finished', 0)}")
    if len(lines) == 1:
        lines.append("- no result: decide with the table above")
    return lines


def build_messages(context: dict[str, Any], candidates: dict[str, Any], finalists: list[dict[str, Any]],
                   allow_what_if: bool, what_if_options: tuple[str, str] | None = None,
                   what_if: dict[str, Any] | None = None) -> list[dict[str, str]]:
    """context: aclopi.agent.core decision context {"products_in_plant", "m1_remaining", "m1_queue",
    "pending_operations", "product_type" (optional)}; candidates: CandidatesResult dict; finalists:
    candidates after the discard."""
    now = float(candidates["time"])
    pending = list(context.get("pending_operations") or [])
    seq = int(candidates["seq"])
    ptype = f" type {context['product_type']}" if context.get("product_type") else ""
    lines = [
        f"NOW t={now:.1f}. Products in plant: {context.get('products_in_plant')}. "
        f"M1: {context.get('m1_remaining', 0):.0f} u.t. left of its job, {context.get('m1_queue', 0)} waiting.",
        f"PRODUCT {candidates['product']}{ptype}, in {candidates.get('current_machine')} "
        f"({candidates.get('own_remaining', 0):.0f} u.t. left). Operation to place: {candidates.get('operation')} "
        f"(step {seq} of {seq + len(pending) - 1}). Pending after it: {' '.join(map(str, pending[1:])) or 'none'}.",
        f"Gaps between the two best: finish {candidates.get('gap_finish')}, finish_plus_next {candidates.get('gap_finish_plus_next')}.",
        "| machine | finish | delta | finish_plus_next | delta | next machine | travel | job left | queue (n) | on the way (n) |",
        "|---|---|---|---|---|---|---|---|---|---|",
        *[_row(c, now) for c in finalists],
    ]
    if what_if is not None:
        lines += _what_if_lines(what_if, now)
        lines.append('Answer {"action": "decide", "machine": ..., "reason": ...}.')
    elif allow_what_if and what_if_options:
        lines.append(f'Answer {{"action": "decide", "machine": ..., "reason": ...}} or {{"action": "what_if", "reason": ...}} '
                     f"to simulate {what_if_options[0]} vs {what_if_options[1]} first.")
    else:
        lines.append('Answer {"action": "decide", "machine": ..., "reason": ...}.')
    return [{"role": "system", "content": SYSTEM}, {"role": "user", "content": "\n".join(lines)}]


def estimated_tokens(messages: list[dict[str, str]]) -> int:
    return sum(len(m["content"]) for m in messages) // 4
