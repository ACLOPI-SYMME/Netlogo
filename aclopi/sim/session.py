"""SimulationSession: one headless NetLogo workspace running Paper.nlogo.

Each session has its own NetLogo workspace and its own output folder
(results/sessions/<session_id>/), set as NetLogo's current directory so that ExportData of
different sessions never overwrite each other. Several sessions can live in the same Python
process (one JVM, one workspace each). Every call into a session's workspace goes through that
session's lock, so a session can be shared between threads (e.g. a live loop and a what-if
export); different sessions run in parallel.

Typical use:

    with SimulationSession() as session:
        session.setup(seed=42, rule=3)
        session.step(100)
        state = session.state()
        events = session.events()
        session.run_to_end()
        kpis = session.kpis()

What-if: export the world once and import it into as many sessions as needed:

    path = base.export_world()
    for other in copies:
        other.import_world(path)
"""

from __future__ import annotations

import json
import logging
import os
import shlex
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from types import TracebackType
from typing import Any

from dotenv import load_dotenv

from aclopi.sim.kpis import Kpis, compute_kpis

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MODEL_PATH = REPO_ROOT / "model" / "Paper.nlogo"
DEFAULT_RESULTS_ROOT = REPO_ROOT / "results" / "sessions"
DEFAULT_HORIZON_TICKS = 10000

# Exact values of the model choosers (Paper.nlogo interface section).
RULES = {
    1: "Rule 1 - Random Machine",
    2: "Rule 2 - Nearest Machine",
    3: "Rule 3 - Potential Fields",
    4: "Rule 4 - AI Agent",  # next machine chosen from Python, see aclopi.sim.decisions
}
MODELING_TYPES = ("Deterministic", "Stochastic")

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class StepResult:
    ticks: int
    advanced: int
    finished: bool


@dataclass(frozen=True)
class RunParameters:
    seed: int | None  # None after import_world: the RNG state comes from the world file
    rule: int
    modeling_type: str
    horizon_ticks: int


def netlogo_string(value: str) -> str:
    """Quote a Python string as a NetLogo string literal."""
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def resolve_netlogo_paths(netlogo_home: str | os.PathLike[str] | None, jvm_path: str | os.PathLike[str] | None) -> tuple[Path, Path]:
    """Explicit arguments win; otherwise NETLOGO_HOME / JVM_PATH from the environment or the repo .env."""
    load_dotenv(REPO_ROOT / ".env")
    home = netlogo_home or os.environ.get("NETLOGO_HOME")
    jvm = jvm_path or os.environ.get("JVM_PATH")
    if not home or not jvm:
        raise RuntimeError("NETLOGO_HOME and JVM_PATH must be set (see .env.example)")
    home_path, jvm_file = Path(home), Path(jvm)
    for name, path in (("NETLOGO_HOME", home_path), ("JVM_PATH", jvm_file)):
        if not path.exists():
            raise FileNotFoundError(f"{name} points to a path that does not exist: {path}")
    return home_path, jvm_file


class SimulationSession:
    """A Paper.nlogo simulation in its own NetLogo workspace and output folder."""

    def __init__(
        self,
        session_id: str | None = None,
        results_root: str | os.PathLike[str] = DEFAULT_RESULTS_ROOT,
        model_path: str | os.PathLike[str] = DEFAULT_MODEL_PATH,
        netlogo_home: str | os.PathLike[str] | None = None,
        jvm_path: str | os.PathLike[str] | None = None,
        jvm_args: list[str] | None = None,
    ) -> None:
        """jvm_args (default: ACLOPI_JVM_ARGS, space separated) only take effect for the first
        session of the process, which starts the JVM; later sessions share that JVM."""
        self.session_id = session_id or uuid.uuid4().hex[:12]
        self.directory = Path(results_root).resolve() / self.session_id
        self.model_path = Path(model_path).resolve()
        if not self.model_path.exists():
            raise FileNotFoundError(f"Model not found: {self.model_path}")
        for sub in ("Results/Data", "Results/Events", "worlds"):
            (self.directory / sub).mkdir(parents=True, exist_ok=True)

        home, jvm = resolve_netlogo_paths(netlogo_home, jvm_path)
        if jvm_args is None:
            jvm_args = shlex.split(os.environ.get("ACLOPI_JVM_ARGS", ""))
        import jpype
        import pynetlogo  # imported late so configuration errors are reported before the JVM starts

        if jvm_args and jpype.isJVMStarted():
            logger.warning("Session %s: JVM already running, jvm_args %s ignored", self.session_id, jvm_args)
        self._link: Any = pynetlogo.NetLogoLink(
            gui=False, netlogo_home=str(home), jvm_path=str(jvm), jvmargs=list(jvm_args)
        )
        # Serializes every call into this workspace: a session may be used from several threads
        # (e.g. a live loop and a what-if export), but a workspace runs one job at a time.
        self._lock = threading.RLock()
        self._closed = False
        self._params: RunParameters | None = None
        self._layout: dict[str, Any] | None = None
        self._world_counter = 0
        try:
            start = time.perf_counter()
            self._link.load_model(str(self.model_path))
            self._apply_directory()
            logger.info("Session %s: model loaded in %.2f s", self.session_id, time.perf_counter() - start)
        except Exception:
            self.close()
            raise

    # ----- lifecycle -----

    def __enter__(self) -> SimulationSession:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        """Dispose of the NetLogo workspace. Safe to call more than once."""
        with self._lock:
            if self._closed:
                return
            self._closed = True
            try:
                self._link.kill_workspace()
            except Exception:  # noqa: BLE001 - the workspace may already be unusable
                logger.exception("Session %s: error while closing the workspace", self.session_id)

    @property
    def closed(self) -> bool:
        return self._closed

    # ----- run control -----

    def setup(
        self,
        seed: int,
        rule: int,
        modeling_type: str = "Stochastic",
        horizon_ticks: int = DEFAULT_HORIZON_TICKS,
    ) -> None:
        """Seed the RNG, set the run parameters and run the model's setup."""
        if rule not in RULES:
            raise ValueError(f"rule must be one of {sorted(RULES)}, got {rule!r}")
        if modeling_type not in MODELING_TYPES:
            raise ValueError(f"modeling_type must be one of {MODELING_TYPES}, got {modeling_type!r}")
        if horizon_ticks < 1:
            raise ValueError("horizon_ticks must be >= 1")
        with self._lock:
            self._command(f"random-seed {int(seed)}")
            self._command(f"set Reactivity.rule {netlogo_string(RULES[rule])}")
            self._command(f"set Modeling.Type {netlogo_string(modeling_type)}")
            self._command("setup")
            self._command(f"set horizon-ticks {int(horizon_ticks)}")
            self._params = RunParameters(int(seed), rule, modeling_type, int(horizon_ticks))
            self._layout = self._report_json("platform-layout")

    def reset(self) -> None:
        """Run setup again with the parameters of the last setup()."""
        params = self._require_params()
        if params.seed is None:
            raise RuntimeError("reset() needs a seed; this session was loaded with import_world()")
        self.setup(params.seed, params.rule, params.modeling_type, params.horizon_ticks)

    def step(self, n: int) -> StepResult:
        """Advance up to n ticks in a single NetLogo call (the model's platform-step reporter).

        Stops early when the run ends. When the horizon is reached, the extra go call that
        runs ExportData and sets terminado is made, so the run finishes cleanly.
        """
        if n < 0:
            raise ValueError("n must be >= 0")
        with self._lock:
            self._require_params()
            ticks, advanced, finished = (int(v) for v in self._report(f"platform-step {int(n)}"))
        return StepResult(ticks=ticks, advanced=advanced, finished=finished == 1)

    def run_to_end(self) -> StepResult:
        """Run until ExportData (tick = horizon_ticks)."""
        params = self._require_params()
        # step never goes past the horizon, so asking for horizon_ticks always reaches the end.
        result = self.step(max(params.horizon_ticks, 1))
        if not result.finished:
            raise RuntimeError(f"Run did not finish (ticks={result.ticks}, horizon={params.horizon_ticks})")
        return result

    @property
    def ticks(self) -> int:
        return int(self._report("ticks"))

    @property
    def finished(self) -> bool:
        return str(self._report("terminado")) == "Si"

    @property
    def parameters(self) -> RunParameters:
        return self._require_params()

    # ----- reading -----

    def state(self) -> dict[str, Any]:
        """Compact state (platform-state)."""
        self._require_params()
        return self._report_json("platform-state")

    def events(self) -> list[dict[str, Any]]:
        """Events recorded since the previous call (platform-events); the buffer is emptied."""
        with self._lock:
            self._require_params()
            payload = self._report_json("platform-events")
            self._command("platform-clear-events")
        fields = payload["fields"]
        return [dict(zip(fields, event)) for event in payload["events"]]

    def layout(self) -> dict[str, Any]:
        """Plant layout (platform-layout), read once after setup or import_world."""
        self._require_params()
        assert self._layout is not None
        return self._layout

    def kpis(self) -> Kpis:
        """KPIs of the current state; does not alter the simulation."""
        with self._lock:
            self._require_params()
            return compute_kpis(self._link)

    def exported_csvs(self) -> list[Path]:
        """CSV files written by ExportData into this session's folder."""
        return sorted((self.directory / "Results").glob("*/*.csv"))

    # ----- what-if: world export / import -----

    def export_world(self, path: str | os.PathLike[str] | None = None) -> Path:
        """Write the full world (agents, globals, RNG state) to a file and return its path."""
        with self._lock:
            self._require_params()
            if path is None:
                self._world_counter += 1
                path = self.directory / "worlds" / f"world_t{self.ticks}_{self._world_counter}.csv"
            target = Path(path).resolve()
            target.parent.mkdir(parents=True, exist_ok=True)
            self._command(f"export-world {netlogo_string(target.as_posix())}")
        return target

    def import_world(self, path: str | os.PathLike[str], seed: int | None = None) -> None:
        """Replace this session's world with an exported one.

        The run parameters travel with the world (they are model globals). The event buffer is
        emptied so the session starts reading events from the moment of the import.
        """
        source = Path(path).resolve()
        if not source.exists():
            raise FileNotFoundError(f"World file not found: {source}")
        with self._lock:
            # import-world clears the world first: until the import succeeds there is no usable run.
            self._params = None
            self._layout = None
            self._command(f"import-world {netlogo_string(source.as_posix())}")
            # Headless NetLogo reports some malformed files only on stderr ("got a fatal error ...")
            # and leaves an empty world, so check that a real run was loaded.
            try:
                nodes = int(self._report("count nodes"))
                int(self._report("ticks"))
            except Exception as exc:  # noqa: BLE001
                raise RuntimeError(f"import-world did not load a valid world from {source}: {exc}") from exc
            if nodes == 0:
                raise RuntimeError(f"import-world did not load a valid world from {source}: no nodes")
            self._apply_directory()
            self._command("platform-clear-events")
            rule_name = str(self._report("Reactivity.rule"))
            rule = next(k for k, v in RULES.items() if v == rule_name)
            self._params = RunParameters(
                seed=seed,
                rule=rule,
                modeling_type=str(self._report("Modeling.Type")),
                horizon_ticks=self._horizon(),
            )
            self._layout = self._report_json("platform-layout")

    def clone_to(self, other: SimulationSession) -> float:
        """Copy this session's current world into another session. Returns the seconds taken."""
        if other is self:
            raise ValueError("cannot clone a session into itself")
        start = time.perf_counter()
        path = self.export_world()
        try:
            other.import_world(path, seed=self._require_params().seed)
        finally:
            path.unlink(missing_ok=True)
        return time.perf_counter() - start

    # ----- low level -----

    @property
    def link(self) -> Any:
        """The underlying pynetlogo NetLogoLink (escape hatch for diagnostics and tests)."""
        self._require_open()
        return self._link

    def _apply_directory(self) -> None:
        self._command(f"set-current-directory {netlogo_string(self.directory.as_posix())}")

    def _horizon(self) -> int:
        return int(self._report("horizon-ticks"))

    def _require_open(self) -> None:
        if self._closed:
            raise RuntimeError(f"Session {self.session_id} is closed")

    def _require_params(self) -> RunParameters:
        self._require_open()
        if self._params is None:
            raise RuntimeError("Call setup() or import_world() first")
        return self._params

    def _command(self, command: str) -> None:
        with self._lock:
            self._require_open()
            self._link.command(command)

    def _report(self, reporter: str) -> Any:
        with self._lock:
            self._require_open()
            return self._link.report(reporter)

    def _report_json(self, reporter: str) -> Any:
        # pynetlogo returns java.lang.String for NetLogo strings.
        return json.loads(str(self._report(reporter)))
