"""Schema of the candidates computation (Línea A).

STUB written by the platform (L5.4) because this module was not in main yet. Línea A owns the
real schema: when it lands, this file is replaced and the platform keeps calling
aclopi.sim.candidates through the same signatures. Every field below is plain data
(as_dict() is what the worker sends and the API returns), so a richer schema only adds fields.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class CandidateParams:
    """Tuning of compute_candidates. Not exposed by the API yet."""

    stochastic_extra_time: float = 10.0  # mean of random-exponential 10 added in M2-M7 (Stochastic)


@dataclass(frozen=True)
class ModelStatic:
    """What does not change during a run: read once after each setup (read_model_static)."""

    capable_machines: dict[str, list[str]]  # operation "O1".."O9" -> machines that can do it
    operation_times: dict[str, dict[str, float]]  # machine -> operation -> processing time
    nominal_times: dict[str, float]  # operation -> OperationDuration
    modeling_type: str
    tick_time: float = 0.31  # simulated time units per tick
    # Conveyor distance between machines, distances[from][to] (model global `distances`,
    # Set.distances.Machines), and the conveyor speed in the same units per tick (jump 0.300 x
    # speed-factor on straight conveyors). See docs/whatif.md, "Viaje".
    distances: dict[str, dict[str, float]] = field(default_factory=dict)
    conveyor_speed: float = 0.3

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Candidate:
    machine: str
    load: int  # products queued at the machine or heading to it (not the one in process)
    busy: bool  # processing now
    remaining_time: float  # left of the job in process (0 if idle)
    estimated_wait: float  # remaining_time + processing times of the load
    operation_time: float  # processing time of this product's operation on the machine (+ mean random part)


@dataclass(frozen=True)
class CandidatesResult:
    product: int
    seq: int
    operation: str | None
    tick: int
    time: float
    valid: bool
    reason: str | None = None  # why it is not valid (unknown-product, seq-mismatch, ...)
    candidates: list[Candidate] = field(default_factory=list)  # sorted by estimated_wait

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)
