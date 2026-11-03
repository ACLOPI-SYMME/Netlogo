"""What-if of one decision (L5.4): run a copy of the simulation with one machine forced.

The copy is a SimulationSession loaded with import_world from a snapshot of the real session
(rule 4, no decider). Only the tested decision is forced (platform-set-next-machine); every
other decision is made by the rule 3 code, and the copy's decision requests are never read.

run_option() advances the copy until the product ENTERS the tested machine (the go in which
ProductRealStart gets element seq and the machine's Next.Completion is set), or until the cap,
a stall, the comparison window, the horizon or the deadline. It advances with NetLogo commands
built here from existing model names (no model change):

    while [ticks < T and ticks < horizon-ticks and terminado = "No"
           and [length ProductRealStart] of turtle W <= SEQ] [ go ]

The condition reads one agent, so it uses no random numbers: the copy evolves exactly as the
real session would with the same assignment. Between chunks of CHUNK_TICKS ticks it reads
positions and the deadline through platform-local (no random numbers either).

Metric of the other products over [T0, stop] (time units, all products except W):
  work     nominal processing work done in the window (as the work_completed KPI: completed
           operations add OperationDuration, the one in progress its processed fraction)
  wait     time in the system during the window minus processing time received in it
  presence time the other products spent in the plant during the window
  finished products finished in the window
The agent combines them; the platform does not rank the options. Both copies of a request are measured at the same tick (the window), so totals compare fairly.
"""

from __future__ import annotations

import json
import shutil
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from aclopi.contracts.candidates import CandidateParams, ModelStatic
from aclopi.sim.candidates import _op_time, machine_loads, travel_time
from aclopi.sim.decisions import set_next_machine
from aclopi.sim.session import netlogo_string

CHUNK_TICKS = 150  # one status read per chunk (never longer than stall_ticks); a stall is two quiet chunks
STALL_TICKS = 300

# Nominal time of operation #i of the product in context (as aclopi.sim.kpis).
_NOMINAL = "item ((read-from-string (last item {i} ProductOperations)) - 1) OperationDuration"


def _others_reporter(exclude: int, t0: float) -> str:
    """platform-local reporter: [work_nominal_total, processing_in_window, presence_in_window, finished_in_window]."""
    others = f"sort products with [who != {exclude}]"
    work = f"""
      sum map [p -> [
        sum map [i -> {_NOMINAL.format(i="i")}] (range length ProductRealCompletion)
        + ifelse-value (length ProductRealStart > length ProductRealCompletion) [
            {_NOMINAL.format(i="(length ProductRealCompletion)")}
            * max (list 0 min (list 1
                ((Simulated.Time - last ProductRealStart)
                 / ([Next.Completion] of first sort machines with [Machine.Name = [Heading.Workstation] of myself] - last ProductRealStart))))
          ] [0]
      ] of p] {others}"""
    processing = f"""
      sum map [p -> [
        sum (map [[s c] -> max (list 0 (c - max (list s {t0})))]
             (sublist ProductRealStart 0 length ProductRealCompletion) ProductRealCompletion)
        + ifelse-value (length ProductRealStart > length ProductRealCompletion)
            [max (list 0 (Simulated.Time - max (list (last ProductRealStart) {t0})))] [0]
      ] of p] {others}"""
    presence = f"""
      sum map [p -> [
        max (list 0 ((ifelse-value (Product.State = "death" and not empty? ProductRealCompletion)
                        [last ProductRealCompletion] [Simulated.Time])
                     - max (list ProductCreationTime {t0})))
      ] of p] {others}"""
    finished = (f"length filter [p -> [Product.State = \"death\" and not empty? ProductRealCompletion "
                f"and last ProductRealCompletion > {t0}] of p] {others}")
    return f"platform-local [ -> json-any (list ({work}) ({processing}) ({presence}) ({finished})) ]"


def _status_reporter(product: int, seq: int, machine: str) -> str:
    """One read per chunk: [ticks, entered (0/1), entry time, operation end, positions of the alive
    products, machines processing] (positions detect stalls; the count goes to the diagnostic)."""
    entered = f"[length ProductRealStart] of turtle {product} > {seq}"
    return (
        "platform-local [ -> json-any (list ticks "
        f"(ifelse-value ({entered}) [1] [0]) "
        f"(ifelse-value ({entered}) [item {seq} [ProductRealStart] of turtle {product}] [-1]) "
        f"([Next.Completion] of first sort machines with [Machine.Name = {netlogo_string(machine)}]) "
        "(map [p -> [(list who xcor ycor)] of p] sort products with [Product.State != \"death\"]) "
        "(length filter [m -> [Machine.State = \"Machine.Processing\"] of m] sort machines)) ]"
    )


@dataclass
class OptionResult:
    machine: str
    entered: bool = False
    stop_reason: str = "error"  # entered | cap | stalled | pruned | timeout | horizon | error
    entry_tick: int | None = None
    entry_time: float | None = None
    entry_estimated: bool = False
    op_end_time: float | None = None
    op_end_estimated: bool = False
    others: dict[str, Any] | None = None
    ticks_simulated: int = 0
    stop_tick: int | None = None
    cap_reached: bool = False
    stalled: bool = False
    pruned: bool = False
    timed_out: bool = False
    import_ms: float = 0.0
    advance_ms: float = 0.0
    diagnostic_file: str | None = None
    error: str | None = None
    timings: dict[str, float] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _ticks(session: Any) -> int:
    return int(session._report("ticks"))


def _sim_time(session: Any) -> float:
    return float(session._report("Simulated.Time"))


def others_metric(session: Any, exclude: int, t0: float, work0: float) -> dict[str, Any]:
    work, processing, presence, finished = json.loads(str(session._report(_others_reporter(exclude, t0))))
    work_window = float(work) - work0
    wait = float(presence) - float(processing)
    return {
        "window_tick": _ticks(session),
        "work": round(work_window, 4),
        "wait": round(wait, 4),
        "presence": round(float(presence), 4),
        "finished": int(finished),
    }


def _remaining(m: dict[str, Any]) -> float:
    return float(m["remaining"]) if m.get("state") == "Machine.Processing" and m.get("remaining") is not None else 0.0


def estimate_entry(state: dict[str, Any], product: int, machine: str, operation: str, static: ModelStatic,
                   params: CandidateParams = CandidateParams(), origin: str | None = None,
                   left_time: float | None = None) -> tuple[float, float]:
    """(entry time, operation end time) estimated from a platform-state.

    The product can enter when it has arrived AND the machine is free:
      arrival = now + what is left of its own operation (if it is in a machine)
                    + travel from its machine to the tested one (distances / conveyor speed)
      free    = now + what is left of the machine's job + processing times of its load
      entry   = max(arrival, free)
    A product already travelling (not in a machine) needs `origin` (its last machine) and
    `left_time` (when it left it); the travel already done is subtracted.
    TODO(Línea A): when the real candidates arrives, use its estimated start instead of this.
    """
    now = float(state["time"])
    machines = {m["name"]: m for m in state["machines"]}
    current = next((m for m in state["machines"] if m.get("product") == product), None)
    if current is not None:  # being processed: waits for its own operation, then travels
        own, origin, travelled = _remaining(current), current["name"], 0.0
    else:
        own, travelled = 0.0, max(0.0, now - left_time) if left_time is not None else 0.0
    arrival = now + own + max(0.0, travel_time(static, origin, machine) - travelled)
    queued = sum(_op_time(static, params, machine, str(q.get("next_operation")))
                 for q in machine_loads(state, exclude=product)[machine])
    free = now + _remaining(machines[machine]) + queued
    entry = max(arrival, free)
    return entry, entry + _op_time(static, params, machine, operation)


def run_option(
    session: Any,
    static: ModelStatic,
    product: int,
    seq: int,
    machine: str,
    max_ticks: int,
    window_tick: int | None = None,
    deadline: float | None = None,
    stall_ticks: int = STALL_TICKS,
    chunk_ticks: int = CHUNK_TICKS,
    diagnostic: tuple[Path, Path, dict[str, Any]] | None = None,
) -> OptionResult:
    """Run one option on a session that has just imported the snapshot (see module docstring).

    window_tick: for the second option, the tick where the first one stopped. The copy stops
    there if the product has not entered (pruned: it enters later than the first option), and
    if it entered earlier it keeps running until the window, so both metrics share one tick.
    diagnostic: (snapshot file, folder, request info) to save when the copy stalls.
    """
    out = OptionResult(machine=machine)
    t_start = time.perf_counter()
    reason = set_next_machine(session, product, machine, seq)
    if reason != "ok":
        out.error = f"platform-set-next-machine rejected the option: {reason}"
        return out
    start_tick, t0, operation, horizon = json.loads(str(session._report(
        f"platform-local [ -> json-any (list ticks Simulated.Time (item {seq} [ProductOperations] of turtle {product}) "
        "horizon-ticks) ]")))
    work0 = float(json.loads(str(session._report(_others_reporter(product, t0))))[0])
    cap_tick = start_tick + max_ticks
    entered_cond = f"[length ProductRealStart] of turtle {product} > {seq}"
    status = _status_reporter(product, seq, machine)
    chunk_ticks = max(1, min(chunk_ticks, stall_ticks))
    last_activity: Any = None
    quiet = 0
    tick = start_tick
    while True:
        limit = cap_tick if window_tick is None else min(cap_tick, max(window_tick, start_tick))
        if out.entered:
            limit = window_tick if window_tick is not None else tick
        if tick >= limit:
            if not out.entered:
                if window_tick is not None and limit == window_tick and window_tick < cap_tick:
                    out.stop_reason, out.pruned = "pruned", True
                else:
                    out.stop_reason, out.cap_reached = "cap", True
            break
        if tick >= horizon:
            out.stop_reason = out.stop_reason if out.entered else "horizon"
            break
        if deadline is not None and time.time() > deadline:
            out.timed_out = True
            if not out.entered:
                out.stop_reason = "timeout"
            break
        target = min(tick + chunk_ticks, limit)
        until = "" if out.entered else f" and not ({entered_cond})"
        session._command(f'while [ticks < {target} and ticks < horizon-ticks and terminado = "No"{until}] [ go ]')
        previous = tick
        tick, entered, entry_time, op_end, positions, processing = json.loads(str(session._report(status)))
        if not out.entered and entered:
            out.entered, out.stop_reason = True, "entered"
            out.entry_tick, out.entry_time, out.op_end_time = tick, float(entry_time), float(op_end)
            if window_tick is None or tick >= window_tick:
                break
            continue
        if tick == previous:  # nothing advanced: the run ended (horizon or terminado)
            if not out.entered:
                out.stop_reason = "horizon"
            break
        # Stall: no product moved for stall_ticks (positions compared between chunks, which are
        # never longer than stall_ticks). `processing` is kept for the diagnostic only.
        if positions == last_activity:
            quiet += tick - previous
        else:
            quiet = 0
        last_activity = positions
        if quiet >= stall_ticks and not out.entered:
            out.stop_reason, out.stalled = "stalled", True
            if diagnostic is not None:
                out.diagnostic_file = _save_diagnostic(*diagnostic, machine=machine, tick=tick,
                                                        quiet_ticks=quiet, machines_processing=processing)
            break
    out.stop_tick = tick
    out.ticks_simulated = tick - start_tick
    out.others = others_metric(session, product, t0, work0)
    if not out.entered:
        state = session.state()
        # If it already left its machine: where from and when (for the travel still to do).
        last_machine, left = json.loads(str(session._report(
            f"platform-local [ -> json-any [(list (ifelse-value empty? Machine.Used [\"\"] [last Machine.Used]) "
            f"(ifelse-value empty? ProductRealCompletion [-1] [last ProductRealCompletion]))] of turtle {product} ]")))
        entry, end = estimate_entry(state, product, machine, operation, static, origin=str(last_machine) or None,
                                    left_time=float(left) if float(left) >= 0 else None)
        tick_time = static.tick_time
        out.entry_time, out.op_end_time = round(entry, 4), round(end, 4)
        out.entry_tick = tick + int(round((entry - float(state["time"])) / tick_time))
        out.entry_estimated = out.op_end_estimated = True
    out.advance_ms = round(1000 * (time.perf_counter() - t_start), 1)
    return out


def _save_diagnostic(snapshot: Path, folder: Path, info: dict[str, Any], machine: str, tick: int,
                     quiet_ticks: int, machines_processing: int) -> str:
    folder.mkdir(parents=True, exist_ok=True)
    stem = f"stall_{info.get('session_id', 'session')}_{info.get('snapshot_tick')}_{machine}_{int(time.time())}"
    target = folder / f"{stem}.csv"
    shutil.copyfile(snapshot, target)
    (folder / f"{stem}.json").write_text(json.dumps({**info, "machine": machine, "stall_tick": tick, "quiet_ticks": quiet_ticks,
                                                     "machines_processing": machines_processing}, indent=1),
                                         encoding="utf-8")
    return str(target)
