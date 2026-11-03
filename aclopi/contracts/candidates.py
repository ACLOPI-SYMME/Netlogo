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
    """Provisional fields agreed with Línea A. The platform's stub fills the first group with the
    what-if estimate (aclopi.sim.candidates.estimate_start) and leaves the rest null. Times are in
    simulated time units: own_remaining, travel and queue_time are durations; arrival, start and
    finish are absolute (Simulated.Time); delta_* are differences to the best candidate."""

    machine: str
    own_remaining: float | None = None  # left of the product's operation in its current machine
    travel: float | None = None  # from its machine to this one (distances / conveyor speed)
    arrival: float | None = None  # now + own_remaining + travel
    queue_time: float | None = None  # left of the machine's job + processing times of its load
    start: float | None = None  # max(arrival, now + queue_time)
    finish: float | None = None  # start + processing time of the operation here
    delta_finish: float | None = None  # finish - best finish among the candidates
    # Filled by Línea A's implementation (null in the stub):
    current_remaining: float | None = None
    en_route_time: float | None = None
    available: bool | None = None
    next_machine: str | None = None
    finish_plus_next: float | None = None
    delta_finish_plus_next: float | None = None


@dataclass(frozen=True)
class CandidatesResult:
    product: int
    seq: int
    operation: str | None
    tick: int
    time: float
    valid: bool
    reason: str | None = None  # why it is not valid (unknown-product, seq-mismatch, ...)
    candidates: list[Candidate] = field(default_factory=list)  # sorted by finish

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)
