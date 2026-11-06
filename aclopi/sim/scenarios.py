"""Plant scenarios (STUB written by the platform line; Línea A replaces this module completely).

A scenario changes the plant during the run, from Python and without touching the model, through
a list of events computed in advance (scenario_events, pure and deterministic) and applied by the
worker when the model is at each event's tick (apply_events). Platform side: docs/scenarios.md.

In this stub apply_events does NOT change the model: every event is reported as applied with
before/after None. Tests only: ACLOPI_SCENARIO_STUB_SKIP=1 reports the repair events as skipped
(skip_reason "machine-idle").
"""

from __future__ import annotations

import os
import random
from dataclasses import dataclass
from typing import Any, Literal

ParamType = Literal["int", "float", "machine", "machine_list", "machine_times"]
EventKind = Literal["set_times", "scale_times", "repair"]
MACHINES = ("M2", "M3", "M4", "M5", "M6", "M7")


@dataclass(frozen=True)
class ParamSpec:
    name: str
    type: ParamType
    default: Any
    min: float | None
    max: float | None
    description: str


@dataclass(frozen=True)
class ScenarioSpec:
    id: str
    name: str
    description: str
    params: tuple[ParamSpec, ...]


@dataclass(frozen=True)
class ScenarioEvent:
    tick: int
    kind: EventKind
    machine: str  # "M2".."M7"
    value: float  # set_times: time (u.t.); scale_times: factor; repair: extra time (u.t.)
    label: str


@dataclass(frozen=True)
class AppliedEvent:
    event: ScenarioEvent
    applied: bool
    skip_reason: Literal["machine-idle"] | None
    before: Any
    after: Any


_SCENARIOS = (
    ScenarioSpec("S0", "Base", "La planta sin cambios.", ()),
    ScenarioSpec("S1", "Máquinas heterogéneas",
                 "Cada máquina indicada pasa a tener su propio tiempo de proceso desde el inicio.", (
                     ParamSpec("times", "machine_times",
                               {"M2": 160, "M3": 180, "M4": 200, "M5": 220, "M6": 240, "M7": 260}, 50, 1000,
                               "Tiempo de proceso por máquina (u.t.); una máquina sin valor no cambia"),
                 )),
    ScenarioSpec("S2", "Degradación", "Desde un tick, una máquina se vuelve más lenta.", (
        ParamSpec("machine", "machine", "M7", None, None, "Máquina que se degrada"),
        ParamSpec("factor", "float", 1.75, 1.0, 5.0, "Factor por el que se multiplican sus tiempos"),
        ParamSpec("start_tick", "int", 10000, 0, 1_000_000, "Tick en que empieza la degradación"),
    )),
    ScenarioSpec("S3", "Fallas", "Cada cierto número de ticks falla una máquina, sorteada de antemano.", (
        ParamSpec("interval_ticks", "int", 5000, 500, 1_000_000, "Ticks entre fallas (la primera en este tick)"),
        ParamSpec("repair_ut", "int", 300, 10, 2000, "Duración de la reparación (u.t.)"),
        ParamSpec("machines", "machine_list", list(MACHINES), None, None, "Máquinas que pueden fallar"),
    )),
)


def list_scenarios() -> list[ScenarioSpec]:
    return list(_SCENARIOS)


def _spec(scenario_id: str) -> ScenarioSpec:
    for s in _SCENARIOS:
        if s.id == scenario_id:
            return s
    raise ValueError(f"unknown scenario {scenario_id!r} (valid: {', '.join(s.id for s in _SCENARIOS)})")


def _fmt(v: float) -> str:
    return str(int(v)) if float(v).is_integer() else f"{v:g}"


def _number(spec: ParamSpec, value: Any, integer: bool, what: str | None = None) -> int | float:
    what = what or spec.name
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{what}: must be a number (got {value!r})")
    if integer and value != int(value):
        raise ValueError(f"{what}: must be an integer (got {value!r})")
    if (spec.min is not None and value < spec.min) or (spec.max is not None and value > spec.max):
        raise ValueError(f"{what}: must be between {_fmt(spec.min)} and {_fmt(spec.max)} (got {value!r})")
    return int(value) if integer else float(value)


def _machine(value: Any, what: str) -> str:
    if value not in MACHINES:
        raise ValueError(f"{what}: must be one of {', '.join(MACHINES)} (got {value!r})")
    return str(value)


def _check(spec: ParamSpec, value: Any) -> Any:
    if spec.type == "int":
        return _number(spec, value, integer=True)
    if spec.type == "float":
        return _number(spec, value, integer=False)
    if spec.type == "machine":
        return _machine(value, spec.name)
    if spec.type == "machine_list":
        if not isinstance(value, list) or not value:
            raise ValueError(f"{spec.name}: must be a non-empty list of machines")
        machines = {_machine(m, spec.name) for m in value}
        if len(machines) != len(value):
            raise ValueError(f"{spec.name}: repeated machine")
        return [m for m in MACHINES if m in machines]
    if spec.type == "machine_times":
        if not isinstance(value, dict):
            raise ValueError(f"{spec.name}: must be an object machine -> time")
        for m in value:
            _machine(m, spec.name)
        return {m: _number(spec, value[m], integer=False, what=f"{spec.name}.{m}") for m in MACHINES if value.get(m) is not None}
    raise ValueError(f"{spec.name}: unknown parameter type {spec.type!r}")


def validate_params(scenario_id: str, params: dict[str, Any] | None) -> dict[str, Any]:
    """The scenario's params with the defaults filled in; ValueError with a message if invalid."""
    spec = _spec(scenario_id)
    params = dict(params or {})
    known = {p.name for p in spec.params}
    extra = sorted(set(params) - known)
    if extra:
        raise ValueError(f"scenario {scenario_id}: unknown parameter(s) {', '.join(extra)}")
    return {p.name: _check(p, params[p.name] if p.name in params else p.default) for p in spec.params}


def scenario_events(scenario_id: str, params: dict[str, Any] | None, seed: int, start_tick: int,
                    end_tick: int) -> list[ScenarioEvent]:
    """Events with start_tick <= tick < end_tick, ordered by tick. Pure and deterministic (S3 draws its
    calendar with random.Random(seed), not the model's RNG: the same for every strategy)."""
    p = validate_params(scenario_id, params)
    events: list[ScenarioEvent] = []
    if scenario_id == "S1":
        events = [ScenarioEvent(0, "set_times", m, float(t), f"Tiempo de {m}: {t:g} u.t.")
                  for m, t in p["times"].items()]
    elif scenario_id == "S2":
        events = [ScenarioEvent(p["start_tick"], "scale_times", p["machine"], p["factor"],
                                f"Degradación en {p['machine']}: ×{p['factor']:g}")]
    elif scenario_id == "S3":
        rng = random.Random(seed)
        tick = p["interval_ticks"]
        while tick < end_tick:  # drawn from the first failure on, so a range never changes the calendar
            m = rng.choice(p["machines"])
            events.append(ScenarioEvent(tick, "repair", m, float(p["repair_ut"]),
                                        f"Falla en {m}: +{p['repair_ut']} u.t."))
            tick += p["interval_ticks"]
    return sorted((e for e in events if start_tick <= e.tick < end_tick), key=lambda e: e.tick)


def apply_events(session: Any, events: list[ScenarioEvent]) -> list[AppliedEvent]:
    """Apply the events to the model, in order (the model is at their tick). Stub: no change."""
    skip = os.environ.get("ACLOPI_SCENARIO_STUB_SKIP") == "1"
    return [AppliedEvent(e, applied=False, skip_reason="machine-idle", before=None, after=None)
            if skip and e.kind == "repair" else AppliedEvent(e, applied=True, skip_reason=None, before=None, after=None)
            for e in events]
