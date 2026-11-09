"""Decision flow of the agent (strategy "agent"):

    fetch (candidates + context) -> triage -> code ..........................-> done
                                         -> llm1 -> [what_if -> llm2] -> validate -> done
                                                 (failure / timeout) -> fallback -> done

Built with LangGraph's StateGraph when langgraph is installed; otherwise a minimal runner with the
same nodes and edges (GraphRunner), so the flow and its tests do not depend on the package.
Limits: at most 2 LLM calls and 1 what-if per decision. Deadlines:
    live: deadline_s = own_remaining / 0.31 / ticks_per_second - 2 s. The what_if action is offered
          only if the product is not in M1 and the time left >= what-if p95 + estimated latency of
          call 2; budget_ms = min(15000, left - call 2), within 2000-15000.
    fast: safety deadline of 60 s; budget_ms = 15000.
On LLM failure, invalid answer or timeout with time left: best by finish (code-fallback). Live
with no time left: nothing is sent (the model applies rule 3) and it is logged. Fast never leaves
the decision to rule 3. Decision levels: code-obvious, code-fallback, llm, llm-what-if.
Context of the prompt (product and plant): the fields /decide carries (docs/agent-api.md); only if
the request lacks them (older platform, mock) one GET /state, with M1's remaining work computed as
next_completion - time (platform-state has no "remaining" field).
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Protocol

from aclopi.agent.llm import LLMClient, LLMError
from aclopi.agent.prompts import answer_schema, build_messages, parse_answer
from aclopi.agent.strategies import Decision, fallback_reason, obvious_reason, short_reason
from aclopi.agent.triage import Triage, TriageParams, classify, ranked

logger = logging.getLogger(__name__)
END = "__end__"


@dataclass(frozen=True)
class AgentConfig:
    triage: TriageParams = TriageParams()
    tick_time: float = 0.31
    live_margin_s: float = 2.0
    fast_deadline_s: float = 60.0
    what_if_p95_s: float = 5.5
    llm2_latency_s: float = 3.0
    budget_min_ms: int = 2000
    budget_max_ms: int = 15000
    max_llm_calls: int = 2


class Platform(Protocol):
    async def candidates(self, session_id: str, product: int, seq: int) -> dict[str, Any]: ...
    async def state(self, session_id: str) -> dict[str, Any]: ...
    async def what_if(self, session_id: str, product: int, seq: int, options: list[str], budget_ms: int) -> dict[str, Any]: ...


@dataclass
class Flow:
    """State carried through the graph (also the decision record)."""

    request: dict[str, Any]
    started: float
    deadline: float
    candidates: dict[str, Any] | None = None
    context: dict[str, Any] | None = None  # decision_context(): product and plant summary for the prompt
    context_source: str | None = None  # "decide" or "state"
    triage: Triage | None = None
    allow_what_if: bool = False
    answer1: Any = None
    what_if_requested: bool = False
    what_if: dict[str, Any] | None = None
    what_if_reason: str | None = None
    answer2: Any = None
    decision: Decision | None = None
    error: str | None = None
    llm_calls: int = 0
    latencies: dict[str, Any] = field(default_factory=lambda: {"llm_ms": []})

    def left(self) -> float:
        return self.deadline - time.monotonic()


def deadline_s(request: dict[str, Any], own_remaining: float, config: AgentConfig) -> float:
    if request.get("mode") == "live" and request.get("ticks_per_second"):
        return own_remaining / config.tick_time / float(request["ticks_per_second"]) - config.live_margin_s
    return config.fast_deadline_s


def context_from_request(request: dict[str, Any]) -> dict[str, Any] | None:
    """Decision context from the /decide fields; None if the platform did not send them."""
    m1 = request.get("m1")
    if m1 is None or request.get("products_in_plant") is None or request.get("pending_operations") is None:
        return None
    return {"products_in_plant": int(request["products_in_plant"]), "m1_busy": bool(m1.get("busy")),
            "m1_remaining": float(m1.get("remaining") or 0.0), "m1_queue": int(m1.get("queue_length") or 0),
            "pending_operations": list(request["pending_operations"]), "product_type": request.get("product_type")}


def context_from_state(state: dict[str, Any], product: int, seq: int) -> dict[str, Any]:
    """Same context from one platform-state: M1's remaining = next_completion - time while processing."""
    now = float(state.get("time") or 0.0)
    m1 = next((m for m in state.get("machines", []) if m.get("name") == "M1"), {})
    busy = m1.get("state") == "Machine.Processing" and m1.get("next_completion") is not None
    p = next((p for p in state.get("products", []) if p.get("id") == product), {})
    return {"products_in_plant": len(state.get("products", [])), "m1_busy": busy,
            "m1_remaining": max(0.0, float(m1["next_completion"]) - now) if busy else 0.0,
            "m1_queue": len(m1.get("queue") or []), "pending_operations": list(p.get("operations") or [])[seq:],
            "product_type": p.get("type")}


class GraphRunner:
    """Minimal stand-in for a compiled LangGraph StateGraph (same nodes and edges)."""

    def __init__(self, nodes: dict[str, Callable[[Flow], Awaitable[None]]], edges: dict[str, Callable[[Flow], str]], entry: str) -> None:
        self.nodes, self.edges, self.entry = nodes, edges, entry

    async def ainvoke(self, flow: Flow) -> Flow:
        node = self.entry
        while node != END:
            await self.nodes[node](flow)
            node = self.edges[node](flow)
        return flow


class Agent:
    def __init__(self, platform: Platform, llm: LLMClient, config: AgentConfig = AgentConfig(),
                 llm_semaphore: asyncio.Semaphore | None = None) -> None:
        self.platform, self.llm, self.config = platform, llm, config
        self.semaphore = llm_semaphore or asyncio.Semaphore(2)
        self.graph = self._build()

    # ----- graph -----

    def _build(self) -> Any:
        nodes = {"fetch": self._fetch, "triage": self._triage, "code": self._code, "llm1": self._llm1,
                 "what_if": self._what_if, "llm2": self._llm2, "fallback": self._fallback, "validate": self._validate}
        edges: dict[str, Callable[[Flow], str]] = {
            "fetch": lambda f: "triage" if f.error is None else "fallback",
            "triage": lambda f: "code" if f.triage is not None and f.triage.level == "obvious" else "llm1",
            "code": lambda f: END,
            "llm1": lambda f: "what_if" if f.what_if_requested else ("validate" if f.decision else "fallback"),
            "what_if": lambda f: "llm2",
            "llm2": lambda f: "validate" if f.decision else "fallback",
            "fallback": lambda f: END,
            "validate": lambda f: END,
        }
        try:
            from langgraph.graph import StateGraph
        except ImportError:
            return GraphRunner(nodes, edges, "fetch")
        graph = StateGraph(dict)

        def wrap(fn: Callable[[Flow], Awaitable[None]]) -> Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]:
            async def node(s: dict[str, Any]) -> dict[str, Any]:
                await fn(s["flow"])
                return s
            return node

        for name, fn in nodes.items():
            graph.add_node(name, wrap(fn))
        for name, route in edges.items():
            graph.add_conditional_edges(name, (lambda r: lambda s: r(s["flow"]))(route))
        graph.set_entry_point("fetch")
        compiled = graph.compile()

        class Adapter:
            async def ainvoke(self, flow: Flow) -> Flow:
                return (await compiled.ainvoke({"flow": flow}))["flow"]

        return Adapter()

    async def decide(self, request: dict[str, Any]) -> tuple[Decision | None, dict[str, Any]]:
        """Run the flow. Returns the decision (None: nothing to send) and the decision record."""
        now = time.monotonic()
        flow = Flow(request=request, started=now, deadline=now + self.config.fast_deadline_s)
        flow = await self.graph.ainvoke(flow)
        flow.latencies["total_ms"] = round(1000 * (time.monotonic() - now), 1)
        if flow.decision is not None:
            flow.decision.latencies = dict(flow.latencies)
        return flow.decision, self.record(flow)

    # ----- nodes -----

    async def _fetch(self, f: Flow) -> None:
        r = f.request
        f.context = context_from_request(r)
        try:
            if f.context is not None:
                f.context_source = "decide"
                f.candidates = await self.platform.candidates(r["session_id"], r["product"], r["seq"])
            else:
                f.context_source = "state"
                f.candidates, state = await asyncio.gather(
                    self.platform.candidates(r["session_id"], r["product"], r["seq"]), self.platform.state(r["session_id"]))
                f.context = context_from_state(state, r["product"], r["seq"])
        except Exception as exc:  # noqa: BLE001
            f.error = f"platform: {type(exc).__name__}: {exc}"[:300]
            return
        if not f.candidates.get("valid") or not f.candidates.get("candidates"):
            f.error = f"candidates-invalid: {f.candidates.get('reason')}"
            return
        own = float(f.candidates.get("own_remaining") or 0.0)
        f.deadline = f.started + deadline_s(r, own, self.config)

    async def _triage(self, f: Flow) -> None:
        f.triage = classify(f.candidates["candidates"], self.config.triage)

    async def _code(self, f: Flow) -> None:
        t = f.triage
        f.decision = Decision(t.best_by_finish, f.request["seq"], "code-obvious",
                              obvious_reason(t, f.candidates["candidates"], f.candidates.get("current_machine")), triage=t)

    def _offer_what_if(self, f: Flow) -> bool:
        if f.triage.level != "very_close" or f.triage.what_if_options is None:
            return False
        if f.request.get("mode") == "live":
            if f.candidates.get("current_machine") == "M1":
                return False
            return f.left() >= self.config.what_if_p95_s + self.config.llm2_latency_s
        return True

    async def _ask(self, f: Flow, allow_what_if: bool, what_if: dict[str, Any] | None) -> Any:
        if f.llm_calls >= self.config.max_llm_calls:
            return "llm-call-limit"
        machines = [c["machine"] for c in f.triage.finalists]
        messages = build_messages(f.context or {}, f.candidates, f.triage.finalists, allow_what_if,
                                  f.triage.what_if_options, what_if)
        async with self.semaphore:
            timeout = f.left()
            if timeout <= 0.05:
                return "deadline"
            f.llm_calls += 1
            data, latency = await self.llm.complete_json(messages, answer_schema(machines, allow_what_if), timeout)
        f.latencies["llm_ms"].append(round(1000 * latency, 1))
        if isinstance(data, LLMError):
            return f"llm-{data.kind}"
        return parse_answer(data, machines, allow_what_if)

    async def _llm1(self, f: Flow) -> None:
        f.allow_what_if = self._offer_what_if(f)
        answer = await self._ask(f, f.allow_what_if, None)
        f.answer1 = answer
        if isinstance(answer, str):
            f.error = answer
        elif answer.action == "what_if":
            f.what_if_requested = True
        else:
            f.decision = Decision(answer.machine, f.request["seq"], "llm", short_reason(answer.reason), triage=f.triage)

    async def _what_if(self, f: Flow) -> None:
        if f.request.get("mode") == "live":
            left_ms = 1000 * (f.left() - self.config.llm2_latency_s)
            budget = int(min(self.config.budget_max_ms, max(self.config.budget_min_ms, left_ms)))
        else:
            budget = self.config.budget_max_ms
        start = time.monotonic()
        try:
            f.what_if = await self.platform.what_if(f.request["session_id"], f.request["product"], f.request["seq"],
                                                    list(f.triage.what_if_options), budget)
            f.what_if_reason = f.what_if.get("skipped_reason") or f.what_if.get("status")
        except Exception as exc:  # noqa: BLE001 - a failed what-if is answered like a skipped one
            f.what_if = {"status": "error", "options": []}
            f.what_if_reason = f"error: {type(exc).__name__}"
        f.latencies["what_if_ms"] = round(1000 * (time.monotonic() - start), 1)
        f.latencies["what_if_budget_ms"] = budget

    async def _llm2(self, f: Flow) -> None:
        answer = await self._ask(f, False, f.what_if or {"status": "error", "options": []})
        f.answer2 = answer
        if isinstance(answer, str):
            f.error = answer
        else:
            used = bool(f.what_if and f.what_if.get("status") in ("ok", "timeout") and f.what_if.get("options"))
            f.decision = Decision(answer.machine, f.request["seq"], "llm-what-if" if used else "llm",
                                  short_reason(answer.reason), triage=f.triage)

    async def _fallback(self, f: Flow) -> None:
        if not f.candidates or not f.candidates.get("candidates"):
            return  # nothing valid to choose from: no answer (logged)
        if f.request.get("mode") == "live" and f.left() <= 0:
            f.error = (f.error or "") + " | no time left: rule 3 decides"
            return
        best = ranked(f.candidates["candidates"], "finish")[0]
        f.decision = Decision(best["machine"], f.request["seq"], "code-fallback",
                              fallback_reason(f.error, best, f.candidates.get("time")), triage=f.triage)

    async def _validate(self, f: Flow) -> None:
        machines = [c["machine"] for c in f.candidates["candidates"]]
        if f.decision.machine not in machines:  # parse_answer already checks; defensive
            f.error, f.decision = f"invalid-machine {f.decision.machine}", None
            await self._fallback(f)

    # ----- helpers -----

    def record(self, f: Flow) -> dict[str, Any]:
        r, d, t = f.request, f.decision, f.triage
        chosen = next((c for c in (f.candidates or {}).get("candidates", []) if d and c["machine"] == d.machine), None)
        return {
            "session_id": r.get("session_id"), "product": r.get("product"), "seq": r.get("seq"),
            "strategy": r.get("strategy"), "mode": r.get("mode"), "tick": r.get("tick"),
            "level": d.decision_level if d else None, "triage": t.level if t else None,
            "context_source": f.context_source,
            **candidates_summary(f.candidates),
            "gap_finish": t.gap_finish if t else None, "gap_finish_plus_next": t.gap_finish_plus_next if t else None,
            "discarded": t.discarded if t else [],
            "what_if_offered": f.allow_what_if, "what_if_requested": f.what_if_requested,
            "what_if_options": list(t.what_if_options) if t and t.what_if_options and f.what_if_requested else None,
            "what_if_reason": f.what_if_reason, "what_if": _what_if_summary(f.what_if),
            "machine": d.machine if d else None, "reason": d.reason if d else None, "error": f.error,
            "latencies": dict(f.latencies), "estimated_finish": chosen.get("finish") if chosen else None,
            "estimated_start": chosen.get("start") if chosen else None, "now": (f.candidates or {}).get("time"),
        }


def candidates_summary(cands: dict[str, Any] | None) -> dict[str, Any]:
    """Fields of the decision record taken from a CandidatesResult (agent, b1 and b1b records)."""
    cands = cands or {}
    return {"operation": cands.get("operation"), "current_machine": cands.get("current_machine"),
            "candidates": [{k: c.get(k) for k in ("machine", "finish", "finish_plus_next", "delta_finish",
                                                  "delta_finish_plus_next", "available_in", "travel")}
                           for c in cands.get("candidates", [])]}


def _what_if_summary(w: dict[str, Any] | None) -> dict[str, Any] | None:
    if not w:
        return None
    return {"status": w.get("status"), "skipped_reason": w.get("skipped_reason"),
            "options": [{k: o.get(k) for k in ("machine", "op_end_time", "op_end_estimated", "others", "skipped")}
                        for o in w.get("options") or []]}
