"""RunController: continuous execution inside a worker (live and fast modes, L5.3).

A run is never one long request (see protocol.py): the worker loop alternates between serving
requests and calling run_block(), which advances one short block and returns the push messages to
send. Between blocks the worker keeps answering state, kpis, pause, export_world, etc.

- Live: target rate BASE_RATE x speed ticks/s. Blocks of max(1, round(rate * update_s)) ticks run
  on a fixed schedule (block k is due at t0 + ticks_k / rate), so the rate does not drift. When the
  worker falls more than MAX_LAG_S behind (CPU starved) the schedule is re-anchored instead of
  catching up at full speed. Each block pushes "tick": tick, platform-state (as JSON text),
  the new events, the measured rate and KPIs about once a second.
- Fast: no speed limit, blocks of fast_block_ticks ticks; each block pushes "progress" with the
  tick, finished products, ticks/s, the block's events and KPIs about once a second.
- At the horizon: push "finished" with the final KPIs; the run state becomes "finished".

Results never depend on speed or block size: platform-step n is n calls to go, and every read
(state, events, kpis) runs with the model's RNG restored.

Run states: idle -> running_live | running_fast <-> paused; -> finished at the horizon; any ->
idle on setup/reset/import_world/stop.

Rule 4 with a decider (L5.5, `decisions=True` in start):
- live: after every block the decision requests queued in the model (decision-queue) are read,
  cleared and pushed with the "tick" message; the run never waits (if the agent answers late the
  model applies rule 3 when the operation ends: rule3-fallback);
- fast: blocks use platform-run-until-decision; when a block stops with pending requests the
  controller enters "waiting_decision", pushes "decision_required" and runs no block until
  next_machine() has been called for every pending request. The waiting itself (timeout, calls to
  the agent) lives in the API; meanwhile the worker keeps serving requests and pushes a
  "heartbeat" every HEARTBEAT_S so the API watchdog does not take it for a hung worker.
- the model's decision log (Decision.Source of every rule-4 assignment) is read and cleared after
  every block and pushed as "assignments" (also without a decider: strategy none).
- fail(reason) ends the run with run state "failed" (e.g. agent_unavailable).

With a product list (docs/product-sets.md) the run also ends, with reason "all_products_done",
as soon as every product of the list has been created and finished (checked after every block);
at the horizon the reason is "horizon".
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass
from dataclasses import asdict
from typing import Any, Callable

from aclopi.sim.decisions import (
    clear_decisions, decision_log, pending_decisions, run_until_decision, set_next_machine,
)

BASE_RATE = 32.0  # ticks/s at speed 1
SPEEDS = (0.5, 1.0, 2.0, 4.0)
RUNNING = ("running_live", "running_fast", "waiting_decision")
HEARTBEAT_S = 2.0
ENDED = ("idle", "finished", "failed")
MAX_LAG_S = 1.0
RATE_WINDOW_S = 1.0


class RunStateError(Exception):
    """The operation is not allowed in the current run state (the API answers 409)."""


@dataclass(frozen=True)
class BlockResult:
    ticks: int
    advanced: int
    finished: bool
    stop_reason: str | None = None  # L5.5: "decision" when requests are pending


def push(event: str, data: Any) -> tuple[str, Any]:
    return (event, data)


class RunController:
    def __init__(
        self,
        session: Any,
        update_s: float = 0.1,
        fast_block_ticks: int = 1000,
        kpi_interval_s: float = 1.0,
        fast_yield: float = 0.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.session = session
        self.update_s = update_s
        self.fast_block_ticks = fast_block_ticks
        self.kpi_interval_s = kpi_interval_s
        self.fast_yield = fast_yield
        self.clock = clock
        # One block of simulation; L5.5 swaps it for platform-run-until-decision.
        self.advance: Callable[[int], BlockResult] = self._platform_step
        self.state = "idle"
        self.mode: str | None = None
        self.speed: float | None = None
        self._next_due = 0.0
        self._last_kpis = 0.0
        self._last_state = 0.0
        self.state_interval_s = 1.0  # fast mode: platform-state in "progress" at most this often
        self._history: deque[tuple[float, int]] = deque()
        self.rule4 = False  # read the decision log (and keep decision-queue empty) after each block
        self.decisions = False  # rule 4 with a decider: hand the requests to the API
        self.pending: set[tuple[int, int]] = set()  # fast mode: requests waiting for next_machine
        self.reason: str | None = None  # why the run ended (failed: agent_unavailable)
        self.product_list = False  # the session has a product list: stop when all are done
        self._last_heartbeat = 0.0

    # ----- state -----

    @property
    def running(self) -> bool:
        return self.state in RUNNING

    def info(self) -> dict[str, Any]:
        return {"run_state": self.state, "mode": self.mode, "speed": self.speed, "reason": self.reason,
                "pending_decisions": len(self.pending)}

    def _set(self, state: str, reason: str | None = None) -> tuple[str, Any]:
        self.state, self.reason = state, reason
        if state in ENDED:
            self.mode, self.speed = None, None
            self.pending.clear()
        return push("run_state", {**self.info(), "tick": self._ticks()})

    def reset(self, finished: bool = False) -> list[tuple[str, Any]]:
        """After setup/reset/import_world/stop: not running."""
        previous = self.state
        new = "finished" if finished else "idle"
        self.pending.clear()
        if previous == new:
            return []
        return [self._set(new)]

    def mark_finished_after_step(self, finished: bool) -> list[tuple[str, Any]]:
        if self.state == "finished":
            return []
        if finished:
            return [self._set("finished", "horizon")]
        if self.all_products_done():
            return [self._set("finished", "all_products_done")]
        return []

    def all_products_done(self) -> bool:
        """With a product list: every product of the list created and finished (no random numbers)."""
        if not self.product_list:
            return False
        return bool(self.session._report(
            'platform-local [ -> product-list? and products-created >= length product-list '
            'and not any? products with [Product.State != "death"] ]'))

    def start(self, mode: str, speed: float | None, decisions: bool = False,
              rule4: bool = False) -> list[tuple[str, Any]]:
        if mode not in ("live", "fast"):
            raise ValueError(f"mode must be 'live' or 'fast', got {mode!r}")
        if self.state in ("finished", "failed"):
            raise RunStateError(f"the run is {self.state}; reset the session to run it again")
        if self.state == "waiting_decision":
            raise RunStateError("the run is waiting for the agent's decisions")
        self.rule4, self.decisions = bool(rule4 or decisions), bool(decisions)
        if self.rule4:
            clear_decisions(self.session)  # requests left by manual steps are stale
        self.advance = self._until_decision if (self.decisions and mode == "fast") else self._platform_step
        if mode == "live":
            speed = 1.0 if speed is None else float(speed)
            if speed not in SPEEDS:
                raise ValueError(f"speed must be one of {SPEEDS}, got {speed!r}")
        else:
            speed = None
        self.mode, self.speed = mode, speed
        self._restart_schedule()
        return [self._set(f"running_{mode}")]

    def pause(self) -> list[tuple[str, Any]]:
        if self.state == "waiting_decision":
            raise RunStateError("cannot pause: the run is waiting for the agent's decisions")
        if not self.running:
            raise RunStateError(f"cannot pause: the session is {self.state}")
        return [self._set("paused")]

    def resume(self) -> list[tuple[str, Any]]:
        if self.state != "paused":
            raise RunStateError(f"cannot resume: the session is {self.state}")
        self._restart_schedule()
        return [self._set(f"running_{self.mode}")]

    def stop(self) -> list[tuple[str, Any]]:
        if self.state in ENDED:
            return []
        return [self._set("idle")]

    def fail(self, reason: str) -> list[tuple[str, Any]]:
        """End the run as failed (e.g. agent_unavailable: no decision within the API's timeout)."""
        if self.state in ENDED:
            return []
        return [self._set("failed", reason)]

    def next_machine(self, product: int, seq: int, machine: str) -> tuple[str, list[tuple[str, Any]]]:
        """Apply an agent's decision (platform-set-next-machine). In fast mode, when it was the last
        pending request, the run goes on. Returns the model's answer ("ok" or the reason)."""
        result = set_next_machine(self.session, int(product), str(machine), int(seq))
        pushes: list[tuple[str, Any]] = []
        if result == "ok":
            self.pending.discard((int(product), int(seq)))
            if self.state == "waiting_decision" and not self.pending:
                self._restart_schedule()
                pushes.append(self._set("running_fast"))
        return result, pushes

    # ----- scheduling -----

    @property
    def rate(self) -> float:
        return BASE_RATE * (self.speed or 1.0)

    @property
    def live_block_ticks(self) -> int:
        return max(1, round(self.rate * self.update_s))

    def _restart_schedule(self) -> None:
        now = self.clock()
        self._next_due = now
        self._last_kpis = 0.0
        self._last_state = 0.0
        self._history.clear()

    def time_to_next(self) -> float | None:
        """Seconds until the next block is due (0 = now), or None when not running."""
        if not self.running:
            return None
        if self.state == "waiting_decision":
            return max(0.0, self._last_heartbeat + HEARTBEAT_S - self.clock())
        return max(0.0, self._next_due - self.clock())

    # ----- blocks -----

    def _platform_step(self, n: int) -> BlockResult:
        if self.product_list:  # stop exactly when the last product finishes (session.step_product_list)
            r, _ = self.session.step_product_list(n)
        else:
            r = self.session.step(n)
        return BlockResult(ticks=r.ticks, advanced=r.advanced, finished=r.finished)

    def _until_decision(self, n: int) -> BlockResult:
        r = run_until_decision(self.session, n)
        return BlockResult(ticks=r.ticks, advanced=r.advanced, finished=r.finished,
                           stop_reason="decision" if r.pending and not r.finished else None)

    def _decision_data(self, data: dict[str, Any]) -> list[dict[str, Any]]:
        """Add the block's rule-4 assignments and, with a decider, its decision requests."""
        if not self.rule4:
            return []
        data["assignments"] = [asdict(d) for d in decision_log(self.session, clear=True)]
        requests = [dict(asdict(r), candidates=list(r.candidates)) for r in pending_decisions(self.session)]
        clear_decisions(self.session)
        if self.decisions:
            data["decision_requests"] = requests
            return requests
        return []

    def _ticks(self) -> int | None:
        try:
            return int(self.session.ticks)
        except Exception:  # noqa: BLE001 - informative only
            return None

    def _measured_rate(self, now: float, ticks: int) -> float | None:
        self._history.append((now, ticks))
        while len(self._history) > 2 and now - self._history[1][0] >= RATE_WINDOW_S:
            self._history.popleft()
        t0, k0 = self._history[0]
        return round((ticks - k0) / (now - t0), 2) if now > t0 else None

    def _kpis_due(self, now: float, finished: bool) -> dict[str, Any] | None:
        if finished or now - self._last_kpis >= self.kpi_interval_s:
            self._last_kpis = now
            return self.session.kpis().as_dict()
        return None

    def run_block(self) -> list[tuple[str, Any]]:
        """Run one block if it is due; returns the pushes to send (empty if nothing ran)."""
        # L5.5: in "waiting_decision" no block runs, but this method must still return a
        # "heartbeat" push every few seconds: the API watchdog (protocol.RUN_WATCHDOG_S) kills a
        # running session that pushes nothing, and waiting for the agent is not being hung.
        if not self.running:
            return []
        now = self.clock()
        if self.state == "waiting_decision":
            if now - self._last_heartbeat >= HEARTBEAT_S:
                self._last_heartbeat = now
                return [push("heartbeat", {"tick": self._ticks(), "pending_decisions": len(self.pending)})]
            return []
        if now < self._next_due:
            return []
        if self.state == "running_live":
            pushes = self._live_block(now)
        else:
            pushes = self._fast_block(now)
        return pushes

    def _live_block(self, now: float) -> list[tuple[str, Any]]:
        due = self._next_due
        n = self.live_block_ticks
        result = self.advance(n)
        events = self.session.events()
        state = self.session.state_json()
        done = self.clock()
        kpis = self._kpis_due(done, result.finished)
        data: dict[str, Any] = {
            "tick": result.ticks,
            "advanced": result.advanced,
            "speed": self.speed,
            "rate": self._measured_rate(done, result.ticks),
            "lag_ms": round(max(0.0, now - due) * 1000, 1),
            "events": events,
            "state": state,
        }
        if kpis is not None:
            data["kpis"] = kpis
        self._decision_data(data)  # live: requests go to the agent, the run does not wait
        pushes = [push("tick", data)]
        self._next_due = due + n / self.rate
        if done - self._next_due > MAX_LAG_S:  # starved: re-anchor instead of catching up
            self._next_due = done
        if result.finished:
            pushes += self._finish(result, kpis, "horizon")
        elif self.all_products_done():
            pushes += self._finish(result, None, "all_products_done")
        return pushes

    def _fast_block(self, now: float) -> list[tuple[str, Any]]:
        result = self.advance(self.fast_block_ticks)
        events = self.session.events()
        done = self.clock()
        kpis = self._kpis_due(done, result.finished)
        data: dict[str, Any] = {
            "tick": result.ticks,
            "advanced": result.advanced,
            "finished_products": self.session.finished_products(),
            "ticks_per_s": self._measured_rate(done, result.ticks),
            "block_ms": round((done - now) * 1000, 1),
            "events": events,
        }
        if kpis is not None:
            data["kpis"] = kpis
        # platform-state at most once a second (and in the last block): the client's canvas shows
        # the fast run as an accelerated video instead of standing still.
        if result.finished or done - self._last_state >= self.state_interval_s:
            self._last_state = done
            data["state"] = self.session.state_json()
        requests = self._decision_data(data)
        pushes = [push("progress", data)]
        # Optional pause between fast blocks (fraction of the block time) to leave CPU to live runs.
        self._next_due = done + self.fast_yield * (done - now)
        if result.finished:
            pushes += self._finish(result, kpis, "horizon")
        elif self.all_products_done():
            pushes += self._finish(result, None, "all_products_done")
        elif requests:  # fast mode: no block runs until every request has its next_machine
            self.pending = {(int(r["who"]), int(r["seq"])) for r in requests}
            self._last_heartbeat = done
            pushes += [push("decision_required", {"tick": result.ticks, "requests": requests}),
                       self._set("waiting_decision")]
        return pushes

    def _finish(self, result: BlockResult, kpis: dict[str, Any] | None, reason: str) -> list[tuple[str, Any]]:
        final = kpis if kpis is not None else self.session.kpis().as_dict()
        return [push("finished", {"tick": result.ticks, "kpis": final, "reason": reason}),
                self._set("finished", reason)]

    def snapshot(self) -> dict[str, Any]:
        return {
            **self.info(),
            "tick": int(self.session.ticks),
            "state": self.session.state_json(),
            "kpis": self.session.kpis().as_dict(),
        }
