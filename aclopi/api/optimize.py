"""Optimize order (docs/optimize-order.md): before running, look for a better entry order of the session's list.

Rounds, all on the session's own worker (simulate_list, aclopi.sim.sequencing) and the agent service
(POST /sequence/propose, docs/sequencing.md):

- round 0: the original order and the heuristic (largest_first), simulated; no call to the AI;
- rounds 1..N: the AI gets the products and every order evaluated so far (order, makespan_ticks,
  details) and proposes up to 2 new orders; the valid, new ones are simulated and added.
  "quick" = reasoning "none" and 1 round; "full" = reasoning "medium" and ACLOPI_OPTIMIZE_ROUNDS_FULL rounds.

Every simulation uses the session's seed, the strategy of its rule (rules 1-3 -> rule1-rule3; rule 4 ->
b1b, or b1 when the session uses b1), mode Deterministic and the session's horizon as max_ticks. The
times always come from simulate_list, never from the AI's text.

simulate_list sets the worker up again, so at the end (done, cancelled or failed) the session's own setup
is made again: with its order (nothing applied: the session is as it was) or with the chosen one
(apply-order). While an optimization is active the session refuses every other operation (409).

An optimization counts as a fast run for ACLOPI_MAX_FAST_RUNS. Provisional rule (until Línea A
confirms its test): no optimization while a live session with the agent runs
(ACLOPI_OPTIMIZE_BLOCK_WHEN_LIVE_AGENT=0 removes it).

WebSocket (session hub): optimize_progress, optimize_best (after each simulation), optimize_result
(done or cancelled) and optimize_failed.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from typing import TYPE_CHECKING, Any, Sequence

import httpx

from aclopi.agent.sequencing import largest_first
from aclopi.api.errors import FastRunLimit, OptimizationNotFound, OptimizeNotAllowed, OptimizeTooManyProducts
from aclopi.workers.protocol import RUN_WATCHDOG_S, timeout_scale

if TYPE_CHECKING:
    from aclopi.api.registry import SessionRecord, SessionRegistry
    from aclopi.api.settings import Settings

logger = logging.getLogger(__name__)

MODES = ("quick", "full")
REASONING = {"quick": "none", "full": "medium"}
SIM_MODE = "Deterministic"
TERMINAL = ("done", "cancelled", "failed")
AI_DOWN = "the AI is not available; only the original and the heuristic were compared"
BUSY = "optimization busy: the AI had no free turn in time"
STALL_S = 30.0  # no progress from the worker for this long (scaled): it is hung
DEFAULT_RETRY_AFTER_S = 5.0


def sim_strategy(rule: int, strategy: str | None) -> str:
    """The strategy simulate_list uses for a session: rules 1-3 their own rule; rule 4 b1b (b1 with b1)."""
    if int(rule) in (1, 2, 3):
        return f"rule{int(rule)}"
    return "b1" if strategy == "b1" else "b1b"


def is_permutation(order: Any, n: int) -> bool:
    return (isinstance(order, list) and all(isinstance(i, int) and not isinstance(i, bool) for i in order)
            and sorted(order) == list(range(n)))


def classify(orders: Sequence[Any], n: int, known: Sequence[tuple[list[int], str]],
             label: str = "#{}") -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Split the AI's orders ([{order, reasoning}]) into new valid ones and discarded ones: not a complete
    permutation of 0..n-1 ("invalid") or equal to an order already known or earlier in the list
    ("same_as" with that order's label). known: (order, label) already evaluated; label: format of the
    labels of the new ones (1, 2, ...)."""
    seen = [(list(o), label) for o, label in known]
    new: list[dict[str, Any]] = []
    discarded: list[dict[str, Any]] = []
    for item in orders:
        order = item.get("order") if isinstance(item, dict) else None
        reasoning = (item.get("reasoning") or None) if isinstance(item, dict) else None
        if not is_permutation(order, n):
            discarded.append({"order": order if isinstance(order, list) else None, "reason": "invalid",
                              "same_as": None, "reasoning": reasoning})
            continue
        same = next((label for o, label in seen if o == order), None)
        if same is not None:
            discarded.append({"order": list(order), "reason": "same_as", "same_as": same, "reasoning": reasoning})
            continue
        seen.append((list(order), label.format(len(new) + 1)))
        new.append({"order": list(order), "reasoning": reasoning})
    return new, discarded


def live_agent_sessions(registry: "SessionRegistry") -> int:
    return sum(1 for r in registry._records.values()
               if r.status == "active" and r.run_state == "running_live" and int(r.parameters.get("rule", 0)) == 4
               and r.strategy == "agent")


def check_can_optimize(registry: "SessionRegistry", record: "SessionRecord", settings: "Settings") -> None:
    """The 409 / 422 / 503 rules of POST /sessions/{id}/optimize-order, in this order."""
    sid = record.session_id
    if record.optimizer is not None and record.optimizer.active:
        raise OptimizeNotAllowed("an optimization of this session is already in progress", sid)
    if record.run_state != "idle":
        raise OptimizeNotAllowed(f"the session is {record.run_state}: optimize order needs it idle, before running", sid)
    if record.ticks > 0:
        raise OptimizeNotAllowed(f"the session already advanced to tick {record.ticks}: reset it first", sid)
    if not record.product_list:
        raise OptimizeNotAllowed("optimize order needs a product list (this session's products come from the seed)", sid)
    if len(record.product_list) > settings.optimize_max_products:
        raise OptimizeTooManyProducts(f"optimize order accepts at most {settings.optimize_max_products} products "
                                      f"(ACLOPI_OPTIMIZE_MAX_PRODUCTS); the list has {len(record.product_list)}", sid)
    if settings.optimize_block_when_live_agent and live_agent_sessions(registry):
        raise OptimizeNotAllowed("optimize order is not available while there are live simulations with the agent", sid)
    if registry.fast_slots_in_use(record) >= registry.max_fast_runs:
        raise FastRunLimit("another fast simulation or optimization is in progress (ACLOPI_MAX_FAST_RUNS)", sid)


class OptimizeBusy(Exception):
    pass


class OrderOptimization:
    """One optimization of one session: its state (GET), its rounds (run) and its end (restore or apply)."""

    def __init__(self, registry: "SessionRegistry", record: "SessionRecord", settings: "Settings", mode: str) -> None:
        self.registry, self.record, self.settings = registry, record, settings
        self.id = uuid.uuid4().hex
        self.mode = mode
        self.reasoning = REASONING[mode]
        self.rounds = 1 if mode == "quick" else max(1, int(settings.optimize_rounds_full))
        self.round = 0
        self.status = "running"  # running | waiting_turn | waiting_ai | done | cancelled | failed
        self.active = True  # until the session's setup is made again (restore or apply)
        self.products = [dict(p) for p in record.product_list or []]  # the list as it was at the start
        p = record.parameters
        self.seed, self.max_ticks = int(p["seed"]), int(p["horizon_ticks"])
        self.strategy = sim_strategy(int(p["rule"]), record.strategy)
        self.evaluated: list[dict[str, Any]] = []
        self.discarded: list[dict[str, Any]] = []
        self.rounds_info: list[dict[str, Any]] = []
        self.current: dict[str, Any] | None = None
        self.sims_done = 0
        self.sims_planned = 2 + 2 * self.rounds
        self.waited_s = 0.0  # waiting for a turn (429), all calls
        self.ai_started: float | None = None
        self.warning: str | None = None
        self.error: str | None = None
        self.applied: int | None = None
        self.stopped_early = False
        self.started_at, self.finished_at = time.time(), None
        self._stop: str | None = None  # "cancel" or "apply"
        self._apply_index: int | None = None
        self._jobs: dict[str, asyncio.Future[Any]] = {}
        self._last_push = time.monotonic()
        self.task: asyncio.Task[Any] | None = None

    # ----- state -----

    @property
    def n(self) -> int:
        return len(self.products)

    def best(self) -> dict[str, Any] | None:
        done = [c for c in self.evaluated if c["all_done"] and c["makespan_ticks"] is not None]
        return min(done, key=lambda c: (c["makespan_ticks"], c["index"])) if done else None

    def progress_pct(self) -> float:
        if self.status in TERMINAL:
            return 100.0
        frac = 0.0
        if self.current and self.current.get("total"):
            frac = min(1.0, self.current["done"] / self.current["total"])
        return round(min(99.0, 100.0 * (self.sims_done + frac) / max(1, self.sims_planned)), 1)

    @staticmethod
    def public_candidate(c: dict[str, Any]) -> dict[str, Any]:
        return {k: v for k, v in c.items() if k != "details"}

    def public(self) -> dict[str, Any]:
        best = self.best()
        return {
            "optimization_id": self.id, "session_id": self.record.session_id, "status": self.status, "mode": self.mode,
            "reasoning_effort": self.reasoning, "round": self.round, "rounds": self.rounds,
            "progress_pct": self.progress_pct(), "current": self.current,
            "ai_elapsed_s": round(time.monotonic() - self.ai_started, 1) if self.ai_started else None,
            "waited_s": round(self.waited_s, 1),
            "strategy": self.strategy, "simulation_mode": SIM_MODE, "seed": self.seed, "max_ticks": self.max_ticks,
            "products": self.products,
            "evaluated": [self.public_candidate(c) for c in self.evaluated],
            "discarded": self.discarded, "rounds_info": self.rounds_info,
            "best": best["index"] if best else None,
            "warning": self.warning, "error": self.error, "applied": self.applied, "stopped_early": self.stopped_early,
            "started_at": self.started_at, "finished_at": self.finished_at,
        }

    def _publish(self, message: dict[str, Any]) -> None:
        self.record.hub.publish({"optimization_id": self.id, **message})

    def _progress(self, phase: str) -> None:
        self._publish({"type": "optimize_progress", "status": self.status, "phase": phase, "round": self.round,
                       "rounds": self.rounds, "simulation": self.current, "progress_pct": self.progress_pct(),
                       "ai_elapsed_s": round(time.monotonic() - self.ai_started, 1) if self.ai_started else None,
                       "waited_s": round(self.waited_s, 1)})

    # ----- worker pushes (registry.on_push, event loop) -----

    def on_push(self, event: str, data: dict[str, Any]) -> None:
        self._last_push = time.monotonic()
        future = self._jobs.get(str(data.get("job_id")))
        if event == "optimize_sim_progress":
            if self.current is not None and future is not None:
                self.current.update(ticks=data["ticks"], done=data["done"], total=data["total"])
                self._progress("simulating")
        elif future is not None and not future.done():
            if event == "optimize_sim_done":
                future.set_result(data["result"])
            else:
                future.set_exception(RuntimeError(data.get("error") or "order simulation failed"))

    # ----- the rounds -----

    def start(self) -> None:
        self.task = asyncio.ensure_future(self._main())

    async def _main(self) -> None:
        final, error = "done", None
        try:
            await self._round0()
            for k in range(1, self.rounds + 1):
                if self._stop or not await self._ai_round(k):
                    break
            if self._stop == "cancel":
                final = "cancelled"
        except OptimizeBusy:
            final, error = "failed", BUSY
        except Exception as exc:  # noqa: BLE001 - the optimization fails; the session is set up again
            logger.exception("Optimize order failed", extra={"session_id": self.record.session_id})
            final, error = "failed", f"{type(exc).__name__}: {exc}"[:500]
        finally:
            self.current, self.ai_started = None, None
            await self._finish(final, error)

    async def _round0(self) -> None:
        identity = list(range(self.n))
        await self._evaluate("original", 0, "Original", identity, None, None)
        heuristic = largest_first(self.products)
        if heuristic == identity:
            self.discarded.append({"origin": "heuristic", "round": 0, "label": "Heuristic", "order": heuristic,
                                   "reason": "same_as", "same_as": "Original", "reasoning": "Longest first"})
            self.sims_done += 1
        elif not self._stop:
            await self._evaluate("heuristic", 0, "Heuristic", heuristic, "Longest first", None)

    async def _ai_round(self, k: int) -> bool:
        """One round with the AI; False ends the rounds (AI down or failed, no valid new order, stopped)."""
        agent = self.registry.agent
        if agent is None or not agent.url or agent.status in ("down", "not_configured"):
            self.warning = AI_DOWN if k == 1 else f"the AI is not available (round {k}); the result uses the orders evaluated so far"
            return False
        self.round = k
        answer = await self._call_ai(k)
        if answer is None:
            return False
        info = {"round": k, "analysis": answer.get("analysis"), "latency_ms": answer.get("latency_ms"),
                "error": answer.get("error")}
        self.rounds_info.append(info)
        known = [(c["order"], c["label"]) for c in self.evaluated] + \
                [(d["order"], d["label"]) for d in self.discarded if d.get("reason") == "same_as" and d.get("order")]
        new, discarded = classify(answer.get("orders") or [], self.n, known, f"AI round {k} · {{}}")
        for i, d in enumerate(discarded):
            self.discarded.append({"origin": "ai", "round": k, "label": f"AI round {k} (discarded {i + 1})", **d})
        self.sims_planned -= 2 - len(new)
        if not new:
            if self.warning is None:
                self.warning = f"the AI gave no new valid order in round {k}; the result uses the orders evaluated so far"
            return False
        for i, item in enumerate(new):
            if self._stop:
                return False
            await self._evaluate("ai", k, f"AI round {k} · {i + 1}", item["order"], item["reasoning"], info["analysis"])
        return True

    async def _evaluate(self, origin: str, k: int, label: str, order: list[int], reasoning: str | None,
                        analysis: str | None) -> None:
        result = await self._simulate(label, order)
        self.sims_done += 1
        if result is None or result.get("cancelled"):
            return
        c = {"index": len(self.evaluated), "origin": origin, "round": k, "label": label, "order": list(order),
             "types": "".join(str(self.products[i]["type"]) for i in order),
             "makespan_ticks": result.get("makespan_ticks"), "makespan_time": result.get("makespan_time"),
             "all_done": bool(result.get("all_done")), "saving_time": None, "saving_pct": None,
             "reasoning": reasoning, "analysis": analysis, "wall_s": result.get("wall_s"),
             "details": result.get("details")}
        self.evaluated.append(c)
        original = self.evaluated[0]
        if original["all_done"]:
            for e in self.evaluated:
                if e["all_done"] and e["makespan_time"] is not None:
                    e["saving_time"] = round(float(original["makespan_time"]) - float(e["makespan_time"]), 2)
                    e["saving_pct"] = round(100.0 * e["saving_time"] / float(original["makespan_time"]), 1)
        best = self.best()
        self._publish({"type": "optimize_best", "evaluated": self.public_candidate(c),
                       "best": self.public_candidate(best) if best else None})

    async def _simulate(self, label: str, order: list[int]) -> dict[str, Any] | None:
        """One simulation on the session's worker; None if stopped before it started."""
        if self._stop:
            return None
        loop = asyncio.get_running_loop()
        job_id = uuid.uuid4().hex
        future: asyncio.Future[Any] = loop.create_future()
        self._jobs[job_id] = future
        self.status = "running"
        self.current = {"label": label, "ticks": 0, "done": 0, "total": self.n}
        self._progress("simulating")
        products = [[self.products[i]["type"], int(self.products[i].get("priority") or 80)] for i in order]
        try:
            self._last_push = time.monotonic()
            await self.registry.call(self.record.session_id, "optimize_sim", job_id=job_id, products=products,
                                     strategy=self.strategy, mode=SIM_MODE, seed=self.seed, max_ticks=self.max_ticks)
            cancel_sent = False
            stall = max(STALL_S, RUN_WATCHDOG_S) * timeout_scale()
            while not future.done():
                if self._stop and not cancel_sent:
                    cancel_sent = True
                    await self.registry.call(self.record.session_id, "optimize_cancel")
                await asyncio.wait({future}, timeout=0.25)
                if not future.done() and time.monotonic() - self._last_push > stall:
                    reason = f"no progress from the worker for {stall:.0f} s while simulating orders"
                    await asyncio.get_running_loop().run_in_executor(
                        None, self.registry.pool.kill_session_worker, self.record.session_id, reason)
                    raise RuntimeError(reason)
            return future.result()
        finally:
            self._jobs.pop(job_id, None)
            self.current = None

    async def _call_ai(self, k: int) -> dict[str, Any] | None:
        """POST /sequence/propose; None (with a warning) if it fails, times out or the optimization stops.
        429: waits Retry-After (waiting_turn) and retries; OptimizeBusy past ACLOPI_OPTIMIZE_MAX_WAIT_S."""
        agent = self.registry.agent
        body = {"products": [{"type": p["type"], "priority": int(p.get("priority") or 80)} for p in self.products],
                "evaluated": [{"order": c["order"], "makespan_ticks": c["makespan_ticks"], "details": c["details"]}
                              for c in self.evaluated],
                "strategy": self.strategy, "mode": SIM_MODE, "reasoning": self.reasoning}
        timeout = float(self.settings.optimize_ai_timeout_s)
        async with httpx.AsyncClient(timeout=timeout) as http:
            while True:
                self.status, self.ai_started = "waiting_ai", time.monotonic()
                self._progress("waiting_ai")
                task = asyncio.ensure_future(http.post(f"{agent.url}/sequence/propose", json=body,
                                                       headers=agent.headers()))
                try:
                    while not task.done():
                        await asyncio.wait({task}, timeout=1.0)
                        if self._stop:
                            task.cancel()
                            return None
                        if not task.done():
                            self._progress("waiting_ai")
                    r = task.result()
                except httpx.TimeoutException:
                    self.warning = f"the AI did not answer within {timeout:g} s (round {k}); the result uses the orders evaluated so far"
                    return None
                except httpx.HTTPError:
                    self.warning = AI_DOWN if k == 1 else f"the AI is not available (round {k}); the result uses the orders evaluated so far"
                    return None
                finally:
                    self.ai_started = None
                    if not task.done():
                        task.cancel()
                if r.status_code == 429:
                    await self._wait_turn(r.headers.get("Retry-After"))
                    if self._stop:
                        return None
                    continue
                if r.status_code != 200:
                    self.warning = f"the AI answered {r.status_code} (round {k}); the result uses the orders evaluated so far"
                    return None
                self.status = "running"
                return r.json()

    async def _wait_turn(self, retry_after: str | None) -> None:
        try:
            wait = max(0.0, float(retry_after)) if retry_after else DEFAULT_RETRY_AFTER_S
        except ValueError:
            wait = DEFAULT_RETRY_AFTER_S
        left = float(self.settings.optimize_max_wait_s) - self.waited_s
        if left <= 0:
            raise OptimizeBusy()
        self.status = "waiting_turn"
        end = time.monotonic() + min(wait, left)
        while not self._stop and (now := time.monotonic()) < end:
            step = min(1.0, end - now)
            await asyncio.sleep(step)
            self.waited_s += step
            self._progress("waiting_turn")
        if not self._stop and wait > left:
            raise OptimizeBusy()

    # ----- the end: the session's setup again -----

    async def _finish(self, final: str, error: str | None) -> None:
        """The session's setup again (its order, or the one to apply); only then the final status shows,
        so that a client that sees it can run the session at once."""
        index = self._apply_index if self._stop == "apply" else None
        try:
            await self.registry.setup_order(self.record, self.products,
                                            self.evaluated[index]["order"] if index is not None else None)
            if index is not None:
                self._record_applied(index)
        except Exception as exc:  # noqa: BLE001 - e.g. the session was deleted or lost meanwhile
            logger.warning("Optimize order: the session could not be set up again: %s", exc,
                           extra={"session_id": self.record.session_id})
            if final != "failed":
                final, error = "failed", f"the session could not be set up again: {exc}"[:500]
        finally:
            self.status, self.error = final, error
            self.finished_at = time.time()
            self.active = False
            await self.registry.after_optimize_setup(self.record)
        self._publish_end()

    def _publish_end(self) -> None:
        if self.status == "failed":
            self._publish({"type": "optimize_failed", "error": self.error, "result": self.public()})
        else:
            self._publish({"type": "optimize_result", "result": self.public()})

    def _record_applied(self, index: int) -> None:
        c = self.evaluated[index]
        self.applied = index
        self.record.optimization = {
            "optimized": True, "mode": self.mode, "order": list(c["order"]), "origin": c["origin"],
            "label": c["label"], "round": c["round"], "estimated_makespan_ticks": c["makespan_ticks"],
            "estimated_makespan_time": c["makespan_time"], "estimated_saving_time": c["saving_time"],
            "estimated_saving_pct": c["saving_pct"], "estimate_strategy": self.strategy,
            "estimate_mode": SIM_MODE, "optimization_id": self.id}

    # ----- requests -----

    async def cancel(self) -> None:
        if not self.active:
            raise OptimizeNotAllowed(f"the optimization already ended ({self.status})", self.record.session_id)
        self._stop = self._stop or "cancel"
        await self._wait_end()

    async def apply(self, index: int) -> None:
        if not 0 <= index < len(self.evaluated):
            raise OptimizeNotAllowed(f"candidate {index} does not exist (evaluated: {len(self.evaluated)})",
                                     self.record.session_id)
        if self.active:
            self._stop, self._apply_index, self.stopped_early = "apply", index, True
            await self._wait_end()
            return
        # Already ended: set the session up with that order now (it is still idle at tick 0).
        record = self.record
        if record.run_state != "idle" or record.ticks > 0:
            raise OptimizeNotAllowed(f"the session is {record.run_state} (tick {record.ticks}): apply-order needs it "
                                     "idle, before running", record.session_id)
        self.active = True
        try:
            await self.registry.setup_order(record, self.products, self.evaluated[index]["order"])
            self._record_applied(index)
        finally:
            self.active = False
            await self.registry.after_optimize_setup(record)
        self._publish_end()

    async def _wait_end(self) -> None:
        if self.task is not None:
            await asyncio.shield(self.task)

    def abort(self) -> None:
        """The session is being deleted: stop at once (the worker's job is stopped by the 'stop' op)."""
        self._stop = self._stop or "cancel"


def reordered(products: list[dict[str, Any]], order: list[int] | None) -> list[dict[str, Any]]:
    return [dict(p) for p in products] if order is None else [dict(products[i]) for i in order]


def get_optimization(record: "SessionRecord") -> OrderOptimization:
    if record.optimizer is None:
        raise OptimizationNotFound("this session has no optimization (POST /sessions/{id}/optimize-order)",
                                   record.session_id)
    return record.optimizer

