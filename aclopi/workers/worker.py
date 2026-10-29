"""Worker process: one SimulationSession, driven from the main thread of its own process.

The loop never blocks on the request queue for more than IDLE_POLL_S, so that later (L5.3) the
worker can run live blocks and still serve requests between them, and so that it notices when the
parent process is gone (then it closes its session and exits: no orphan processes).

See aclopi.workers.protocol for the message format and the rule that no request may take more
than a few seconds.
"""

from __future__ import annotations

import logging
import multiprocessing as mp
import os
import queue
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from aclopi import logjson
from aclopi.workers import procinfo
from aclopi.workers.protocol import (
    DEBUG_OPS, MAX_STEP_TICKS, OPS, error_response, ok_response, push_message,
)
from aclopi.sim.candidates import candidates_for_session, machine_loads, read_model_static
from aclopi.sim.session import netlogo_string
from aclopi.sim.whatif import CHUNK_TICKS, STALL_TICKS, estimate_entry, run_option
from aclopi.workers.runner import RunController, RunStateError

IDLE_POLL_S = 0.2
MAX_REQUESTS_PER_TURN = 16
WARM_RULE = 3
WARM_SEED = 1
WARM_TICKS = 2000

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class WorkerConfig:
    slot: int
    role: str  # "session" or "whatif"
    generation: int
    work_dir: str  # pool work folder: <work_dir>/worlds (world files), <work_dir>/sessions (ExportData)
    jvm_args: tuple[str, ...] = ()
    debug: bool = False
    warm: bool = True
    # Continuous runs (L5.3, see runner.py)
    live_update_s: float = 0.1
    fast_block_ticks: int = 1000
    fast_yield: float = 0.0

    @property
    def name(self) -> str:
        return f"{self.role}{self.slot}"


def to_plain(value: Any) -> Any:
    """Convert any result into plain Python data that unpickles without a JVM.

    Exact type checks matter: JPype's java.lang.String subclasses str and numpy floats subclass
    float, but both pickle as their own classes (a JString cannot be unpickled in the main
    process, which has no JVM).
    """
    if value is None or type(value) in (bool, int, float, str):
        return value
    if hasattr(value, "tolist"):  # numpy arrays and scalars
        return to_plain(value.tolist())
    if isinstance(value, bool):
        return bool(value)
    if isinstance(value, int):
        return int(value)
    if isinstance(value, float):
        return float(value)
    if isinstance(value, str):
        return str(value)
    if isinstance(value, (list, tuple)):
        return [to_plain(v) for v in value]
    if isinstance(value, dict):
        return {str(k): to_plain(v) for k, v in value.items()}
    return str(value)


class WorkerState:
    """The worker's SimulationSession plus what the operations need to know about it."""

    def __init__(self, config: WorkerConfig) -> None:
        from aclopi.sim import SimulationSession

        self.config = config
        self.worlds_dir = Path(config.work_dir) / "worlds"
        self.worlds_dir.mkdir(parents=True, exist_ok=True)
        self.session = SimulationSession(
            f"{config.name}_g{config.generation}",
            results_root=Path(config.work_dir) / "sessions",
            jvm_args=list(config.jvm_args),
        )
        self.configured = False  # True after a client setup() or import_world()
        self.warm_info: dict[str, float] = {}
        self.runner = RunController(
            self.session, update_s=config.live_update_s, fast_block_ticks=config.fast_block_ticks,
            fast_yield=config.fast_yield,
        )
        self.pushes: list[tuple[str, Any]] = []  # sent after the current response
        self.static: Any = None  # ModelStatic, read after each setup (candidates, what-if)

    def warm_up(self) -> None:
        """Exercise the code paths a client will use (JIT warm-up) before accepting work."""
        s = self.session
        t0 = time.perf_counter()
        s.setup(seed=WARM_SEED, rule=WARM_RULE)
        s.step(WARM_TICKS)
        s.state()
        s.state_json()
        s.finished_products()
        s.events()
        s.kpis()
        t1 = time.perf_counter()
        path = s.export_world(self.worlds_dir / f"warm_{self.config.name}_{uuid.uuid4().hex[:8]}.csv")
        t2 = time.perf_counter()
        if self.config.role == "whatif":
            s.import_world(path)
            s.step(300)
            self._warm_whatif()
        path.unlink(missing_ok=True)
        self.warm_info = {"run_s": round(t1 - t0, 2), "export_s": round(t2 - t1, 3), "total_s": round(time.perf_counter() - t0, 2)}

    def _warm_whatif(self) -> None:
        """What-if workers: exercise the what-if path once (rule 4 decision, import, run_option)."""
        from aclopi.sim.decisions import clear_decisions, pending_decisions, run_until_decision

        s = self.session
        s.setup(seed=WARM_SEED, rule=4)
        run_until_decision(s, 5000)
        requests = pending_decisions(s)
        clear_decisions(s)
        if not requests:
            return
        req = requests[0]
        static = read_model_static(s)
        path = s.export_world(self.worlds_dir / f"warmwi_{self.config.name}_{uuid.uuid4().hex[:8]}.csv")
        try:
            for machine in req.candidates[:2]:
                s.import_world(path)
                run_option(s, static, req.who, req.seq, machine, 600)
        finally:
            path.unlink(missing_ok=True)

    # ----- operations -----

    def op_ping(self) -> dict[str, Any]:
        ticks = None
        if self.configured:
            try:
                ticks = self.session.ticks
            except Exception:  # noqa: BLE001 - ping must answer whatever the world's state
                ticks = None
        return {
            "pid": os.getpid(),
            "slot": self.config.slot,
            "role": self.config.role,
            "generation": self.config.generation,
            "configured": self.configured,
            "ticks": ticks,
            **self.runner.info(),
        }

    def op_setup(
        self,
        seed: int,
        rule: int,
        modeling_type: str = "Stochastic",
        horizon_ticks: int = 10000,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        """session_id (optional) only tags this worker's log lines until the next setup."""
        logjson.session_id_var.set(session_id)
        try:
            self.session.setup(seed=seed, rule=rule, modeling_type=modeling_type, horizon_ticks=horizon_ticks)
        finally:
            self.pushes += self.runner.reset()  # any run stops, also if setup fails
        self.configured = True
        self.static = read_model_static(self.session)
        logger.info("setup seed=%s rule=%s modeling_type=%s horizon_ticks=%s", seed, rule, modeling_type, horizon_ticks)
        return self._params()

    # ----- decisions: candidates and what-if (L5.4) -----

    def op_candidates(self, product: int, seq: int) -> dict[str, Any]:
        """Candidate machines for a pending decision (aclopi.sim.candidates); between blocks when running."""
        self._require_configured()
        if self.static is None:
            self.static = read_model_static(self.session)
        return candidates_for_session(self.session, int(product), int(seq), self.static).as_dict()

    def op_whatif_snapshot(self, product: int, seq: int, options: list[str], saturation_queue: int = 0,
                           enforce_saturation: bool = False) -> dict[str, Any]:
        """Session worker: validate the options, measure the load of the tested machines and, if
        everything is valid (and not skipped for saturation), export ONE snapshot of the world."""
        self._require_configured()
        if self.static is None:
            self.static = read_model_static(self.session)
        s = self.session
        reasons = {m: str(s._report(f"platform-local [ -> platform-check-next-machine {int(product)} "
                                     f"{netlogo_string(str(m))} {int(seq)} ]")) for m in options}
        result: dict[str, Any] = {"tick": s.ticks, "reasons": reasons, "valid": all(r == "ok" for r in reasons.values())}
        if not result["valid"]:
            return result
        state = s.state()
        loads = machine_loads(state, exclude=int(product))
        operation = next(str(p["operations"][int(seq)]) for p in state["products"] if p["id"] == int(product))
        result.update({
            "time": float(state["time"]),
            "operation": operation,
            "loads": {m: len(loads[m]) for m in options},
            "estimated_entry": {m: estimate_entry(state, int(product), m, operation, self.static)[0] for m in options},
        })
        result["saturated"] = bool(saturation_queue) and all(n >= saturation_queue for n in result["loads"].values())
        if result["saturated"] and enforce_saturation:
            return result
        t0 = time.perf_counter()
        path = s.export_world(self.worlds_dir / f"whatif_{self.config.name}_{uuid.uuid4().hex}.csv")
        result.update({"path": str(path), "export_ms": round(1000 * (time.perf_counter() - t0), 1)})
        return result

    def op_whatif_option(self, path: str, product: int, seq: int, machine: str, max_ticks: int,
                         window_tick: int | None = None, deadline: float | None = None,
                         stall_ticks: int = STALL_TICKS, chunk_ticks: int = CHUNK_TICKS,
                         diag_dir: str | None = None, info: dict[str, Any] | None = None) -> dict[str, Any]:
        """What-if worker: import the snapshot (kept for the next option) and run one option."""
        t0 = time.perf_counter()
        self.pushes += self.runner.reset()
        self.configured = False
        self.session.import_world(Path(path))
        self.configured = True
        self.static = read_model_static(self.session)
        import_ms = round(1000 * (time.perf_counter() - t0), 1)
        diagnostic = (Path(path), Path(diag_dir), info or {}) if diag_dir else None
        out = run_option(self.session, self.static, int(product), int(seq), str(machine), int(max_ticks),
                         window_tick=window_tick, deadline=deadline, stall_ticks=stall_ticks,
                         chunk_ticks=chunk_ticks, diagnostic=diagnostic)
        out.import_ms = import_ms
        return out.as_dict()

    def op_step(self, n: int, with_state: bool = False) -> dict[str, Any]:
        """with_state: also return platform-state (JSON text), for clients watching the session."""
        if not isinstance(n, int) or isinstance(n, bool) or n < 1 or n > MAX_STEP_TICKS:
            raise ValueError(
                f"step n must be an integer between 1 and {MAX_STEP_TICKS} (got {n!r}); "
                "long runs are done by the worker in blocks (fast mode), not in one request"
            )
        self._require_configured()
        self._require_not_running("step")
        r = self.session.step(n)
        self.pushes += self.runner.mark_finished_after_step(r.finished)
        result: dict[str, Any] = {"ticks": r.ticks, "advanced": r.advanced, "finished": r.finished}
        if with_state:
            result["state"] = self.session.state_json()
        return result

    def op_state(self) -> dict[str, Any]:
        self._require_configured()
        return self.session.state()

    def op_events(self) -> list[dict[str, Any]]:
        self._require_configured()
        self._require_not_running("events")  # while running, events travel in the run's pushes
        return self.session.events()

    # ----- continuous runs (runner.py) -----

    def op_run(self, mode: str, speed: float | None = None) -> dict[str, Any]:
        self._require_configured()
        self.pushes += self.runner.start(mode, speed)
        return self._params()

    def op_pause(self) -> dict[str, Any]:
        self._require_configured()
        self.pushes += self.runner.pause()
        return self._params()

    def op_resume(self) -> dict[str, Any]:
        self._require_configured()
        self.pushes += self.runner.resume()
        return self._params()

    def op_stop(self) -> dict[str, Any]:
        """Stop any run (idle); used before the worker is released. Never fails."""
        self.pushes += self.runner.stop()
        return self.runner.info()

    def op_snapshot(self) -> dict[str, Any]:
        """Run state, tick, platform-state (JSON text) and KPIs, read between two blocks."""
        self._require_configured()
        return self.runner.snapshot()

    def _require_not_running(self, op: str) -> None:
        if self.runner.running:
            raise RunStateError(f"{op} is not allowed while the session is {self.runner.state}; pause it first")

    def op_layout(self) -> dict[str, Any]:
        self._require_configured()
        return self.session.layout()

    def op_kpis(self) -> dict[str, Any]:
        self._require_configured()
        return self.session.kpis().as_dict()

    def op_reset(self) -> dict[str, Any]:
        self._require_configured()
        try:
            self.session.reset()
        finally:
            self.pushes += self.runner.reset()
        return self._params()

    def op_export_world(self) -> dict[str, Any]:
        self._require_configured()
        t0 = time.perf_counter()
        path = self.session.export_world(self.worlds_dir / f"{self.config.name}_{uuid.uuid4().hex}.csv")
        return {"path": str(path), "ticks": self.session.ticks, "export_ms": round(1000 * (time.perf_counter() - t0), 1)}

    def op_import_world(self, path: str, seed: int | None = None, delete_after: bool = True) -> dict[str, Any]:
        source = Path(path)
        # import-world clears the world before reading the file: if the import fails, the
        # previous simulation is gone, so the worker needs a new setup or import_world.
        self.configured = False
        try:
            self.session.import_world(source, seed=seed)
        finally:
            self.pushes += self.runner.reset()
            if delete_after:
                source.unlink(missing_ok=True)
        self.configured = True
        return self._params()

    def op_command(self, code: str) -> None:
        self.session.link.command(code)

    def op_report(self, code: str) -> Any:
        return to_plain(self.session.link.report(code))

    def _params(self) -> dict[str, Any]:
        p = self.session.parameters
        return {"seed": p.seed, "rule": p.rule, "modeling_type": p.modeling_type,
                "horizon_ticks": p.horizon_ticks, "ticks": self.session.ticks, **self.runner.info()}

    def _require_configured(self) -> None:
        if not self.configured:
            raise RuntimeError("call setup or import_world first")

    def handler(self, op: str) -> Callable[..., Any]:
        if op in DEBUG_OPS and not self.config.debug:
            raise PermissionError(f"operation {op!r} is only available in debug mode")
        if op not in OPS and op not in DEBUG_OPS:
            raise ValueError(f"unknown operation {op!r}")
        return getattr(self, f"op_{op}")


def worker_main(config: WorkerConfig, requests: mp.Queue, outbox: mp.Queue) -> None:
    logjson.configure(os.environ.get("ACLOPI_LOG_LEVEL", "INFO"), static={"worker": f"{config.name}[g{config.generation}]"})
    priority = procinfo.lower_own_priority() if config.role == "whatif" else "normal"
    t0 = time.perf_counter()
    try:
        state = WorkerState(config)
        load_s = time.perf_counter() - t0
        if config.warm:
            state.warm_up()
    except Exception as exc:  # noqa: BLE001 - reported to the pool, then exit
        logger.exception("Worker failed to start")
        outbox.put(push_message("fatal", {"error": f"{type(exc).__name__}: {exc}"}))
        return

    outbox.put(push_message("ready", {
        "pid": os.getpid(), "slot": config.slot, "role": config.role, "generation": config.generation,
        "load_s": round(load_s, 2), "warm": state.warm_info, "priority": priority,
    }))
    parent = mp.parent_process()
    running = True
    last_parent_check = time.monotonic()
    try:
        while running:
            # Wait for a request only until the next block of a continuous run is due (runner.py);
            # without a run the loop just serves requests.
            wait = state.runner.time_to_next()
            timeout = IDLE_POLL_S if wait is None else min(wait, IDLE_POLL_S)
            try:
                msg = requests.get(timeout=timeout) if timeout > 0 else requests.get_nowait()
            except queue.Empty:
                msg = None
            served = 0
            while msg is not None:
                running = _serve(state, msg, outbox)
                served += 1
                if not running or served >= MAX_REQUESTS_PER_TURN:
                    break
                try:
                    msg = requests.get_nowait()
                except queue.Empty:
                    msg = None
            if running:
                _run_block(state, outbox)
            now = time.monotonic()
            if now - last_parent_check >= IDLE_POLL_S:
                last_parent_check = now
                if parent is not None and not parent.is_alive():
                    logger.warning("Parent process is gone; exiting")
                    break
    finally:
        state.session.close()


def _run_block(state: WorkerState, outbox: mp.Queue) -> None:
    """One block of the current run, if due. A failing block stops the run and is reported."""
    try:
        pushes = state.runner.run_block()
    except Exception as exc:  # noqa: BLE001 - the worker stays alive; the run stops
        logger.exception("Run block failed")
        pushes = [("run_error", {"error": f"{type(exc).__name__}: {exc}"[:4000]})] + state.runner.stop()
    for event, data in pushes:
        outbox.put(push_message(event, to_plain(data)))


def _serve(state: WorkerState, msg: dict[str, Any], outbox: mp.Queue) -> bool:
    """Run one request and put its response in the outbox. Returns False after shutdown."""
    request_id, op = msg.get("id"), msg.get("op")
    t0 = time.perf_counter()
    if op == "shutdown":
        outbox.put(ok_response(request_id, None, 0.0))
        return False
    try:
        result = to_plain(state.handler(op)(**(msg.get("args") or {})))
        outbox.put(ok_response(request_id, result, 1000 * (time.perf_counter() - t0)))
    except Exception as exc:  # noqa: BLE001 - every failure becomes an error response
        outbox.put(error_response(request_id, exc, 1000 * (time.perf_counter() - t0)))
    # Run-state changes caused by the operation (also when it failed half-way, e.g. setup).
    pushes, state.pushes = state.pushes, []
    for event, data in pushes:
        outbox.put(push_message(event, to_plain(data)))
    return True
