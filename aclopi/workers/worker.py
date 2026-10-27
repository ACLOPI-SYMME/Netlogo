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

    def warm_up(self) -> None:
        """Exercise the code paths a client will use (JIT warm-up) before accepting work."""
        s = self.session
        t0 = time.perf_counter()
        s.setup(seed=WARM_SEED, rule=WARM_RULE)
        s.step(WARM_TICKS)
        s.state()
        s.events()
        s.kpis()
        t1 = time.perf_counter()
        path = s.export_world(self.worlds_dir / f"warm_{self.config.name}_{uuid.uuid4().hex[:8]}.csv")
        t2 = time.perf_counter()
        if self.config.role == "whatif":
            s.import_world(path)
            s.step(300)
        path.unlink(missing_ok=True)
        self.warm_info = {"run_s": round(t1 - t0, 2), "export_s": round(t2 - t1, 3), "total_s": round(time.perf_counter() - t0, 2)}

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
        self.session.setup(seed=seed, rule=rule, modeling_type=modeling_type, horizon_ticks=horizon_ticks)
        self.configured = True
        logger.info("setup seed=%s rule=%s modeling_type=%s horizon_ticks=%s", seed, rule, modeling_type, horizon_ticks)
        return self._params()

    def op_step(self, n: int) -> dict[str, Any]:
        if not isinstance(n, int) or isinstance(n, bool) or n < 1 or n > MAX_STEP_TICKS:
            raise ValueError(
                f"step n must be an integer between 1 and {MAX_STEP_TICKS} (got {n!r}); "
                "long runs are done by the worker in blocks (fast mode), not in one request"
            )
        self._require_configured()
        r = self.session.step(n)
        return {"ticks": r.ticks, "advanced": r.advanced, "finished": r.finished}

    def op_state(self) -> dict[str, Any]:
        self._require_configured()
        return self.session.state()

    def op_events(self) -> list[dict[str, Any]]:
        self._require_configured()
        return self.session.events()

    def op_layout(self) -> dict[str, Any]:
        self._require_configured()
        return self.session.layout()

    def op_kpis(self) -> dict[str, Any]:
        self._require_configured()
        return self.session.kpis().as_dict()

    def op_reset(self) -> dict[str, Any]:
        self._require_configured()
        self.session.reset()
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
                "horizon_ticks": p.horizon_ticks, "ticks": self.session.ticks}

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
    try:
        while running:
            # L5.3: when live mode is active the first get() will not wait (timeout 0) and one live
            # block will run after the requests of this turn; here the worker only serves requests.
            try:
                msg = requests.get(timeout=IDLE_POLL_S)
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
            if parent is not None and not parent.is_alive():
                logger.warning("Parent process is gone; exiting")
                break
    finally:
        state.session.close()


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
    return True
