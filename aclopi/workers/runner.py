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

L5.5 (rule 4 decisions): `advance` becomes platform-run-until-decision. When a block stops with
pending decision requests (BlockResult.stop_reason == "decision") the controller will enter a
"waiting_decision" state and push "decision_required"; the worker loop does not change.
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass
from typing import Any, Callable

BASE_RATE = 32.0  # ticks/s at speed 1
SPEEDS = (0.5, 1.0, 2.0, 4.0)
RUNNING = ("running_live", "running_fast")
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
        self._history: deque[tuple[float, int]] = deque()

    # ----- state -----

    @property
    def running(self) -> bool:
        return self.state in RUNNING

    def info(self) -> dict[str, Any]:
        return {"run_state": self.state, "mode": self.mode, "speed": self.speed}

    def _set(self, state: str) -> tuple[str, Any]:
        self.state = state
        if state in ("idle", "finished"):
            self.mode, self.speed = None, None
        return push("run_state", {**self.info(), "tick": self._ticks()})

    def reset(self, finished: bool = False) -> list[tuple[str, Any]]:
        """After setup/reset/import_world/stop: not running."""
        previous = self.state
        new = "finished" if finished else "idle"
        if previous == new:
            return []
        return [self._set(new)]

    def mark_finished_after_step(self, finished: bool) -> list[tuple[str, Any]]:
        if finished and self.state != "finished":
            return [self._set("finished")]
        return []

    def start(self, mode: str, speed: float | None) -> list[tuple[str, Any]]:
        if mode not in ("live", "fast"):
            raise ValueError(f"mode must be 'live' or 'fast', got {mode!r}")
        if self.state == "finished":
            raise RunStateError("the run is finished; reset the session to run it again")
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
        if not self.running:
            raise RunStateError(f"cannot pause: the session is {self.state}")
        return [self._set("paused")]

    def resume(self) -> list[tuple[str, Any]]:
        if self.state != "paused":
            raise RunStateError(f"cannot resume: the session is {self.state}")
        self._restart_schedule()
        return [self._set(f"running_{self.mode}")]

    def stop(self) -> list[tuple[str, Any]]:
        if self.state in ("idle", "finished"):
            return []
        return [self._set("idle")]

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
        self._history.clear()

    def time_to_next(self) -> float | None:
        """Seconds until the next block is due (0 = now), or None when not running."""
        if not self.running:
            return None
        return max(0.0, self._next_due - self.clock())

    # ----- blocks -----

    def _platform_step(self, n: int) -> BlockResult:
        r = self.session.step(n)
        return BlockResult(ticks=r.ticks, advanced=r.advanced, finished=r.finished)

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
        pushes = [push("tick", data)]
        self._next_due = due + n / self.rate
        if done - self._next_due > MAX_LAG_S:  # starved: re-anchor instead of catching up
            self._next_due = done
        if result.finished:
            pushes += self._finish(result, kpis)
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
        pushes = [push("progress", data)]
        # Optional pause between fast blocks (fraction of the block time) to leave CPU to live runs.
        self._next_due = done + self.fast_yield * (done - now)
        if result.finished:
            pushes += self._finish(result, kpis)
        return pushes

    def _finish(self, result: BlockResult, kpis: dict[str, Any] | None) -> list[tuple[str, Any]]:
        final = kpis if kpis is not None else self.session.kpis().as_dict()
        return [push("finished", {"tick": result.ticks, "kpis": final}), self._set("finished")]

    def snapshot(self) -> dict[str, Any]:
        return {
            **self.info(),
            "tick": int(self.session.ticks),
            "state": self.session.state_json(),
            "kpis": self.session.kpis().as_dict(),
        }
