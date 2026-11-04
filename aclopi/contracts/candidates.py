"""Schema of the candidates computation (Línea A). Implementation: aclopi/sim/candidates.py.

Replaces the platform's stub (L5.4) and keeps every field it had, with the same names and types,
so the worker, the API (CandidatesResponse / CandidateInfo allow extra fields) and the mock agent
keep working; new fields are only added. as_dict() is what the worker sends and the API returns.

Units: simulated time units (u.t.; 1 tick = 0.31 u.t.). Durations: own_remaining, travel,
current_remaining, queue_time, en_route_time, available_in, proc_time, travel_next, gap_*, delta_*.
Absolute times (Simulated.Time), as in the stub: arrival, start, finish, finish_plus_next.
    arrival = now + own_remaining + travel
    start   = now + max(own_remaining + travel, available_in)
    finish  = start + proc_time;  finish_plus_next = finish + travel_next
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class CandidateParams:
    """Tuning of compute_candidates. Not exposed by the API."""

    stochastic_extra_time: float = 10.0  # mean of random-exponential 10 added in M2-M7 (Stochastic)
    # en_route_time: False counts every product heading to the machine; True only those expected
    # to arrive before this product.
    en_route_only_earlier: bool = False
    # The product occupying a candidate (and the first of its queue) may stay for its following
    # operation: products are reprocessed in place when the same machine is chosen again, which is
    # what b1 and rule 3 usually do. Diagnosed in the smoke test: 96 % of the lateness of finish.
    occupant_may_stay: bool = True

    @property
    def stochastic_extra_mean(self) -> float:  # name used in Línea A's design
        return self.stochastic_extra_time


@dataclass(frozen=True)
class ModelStatic:
    """What does not change during a run: read once after each setup (read_model_static)."""

    capable_machines: dict[str, list[str]]  # operation "O1".."O9" -> machines that can do it
    operation_times: dict[str, dict[str, float]]  # machine -> operation -> Machine.Operations.Time
    nominal_times: dict[str, float]  # operation -> OperationDuration
    modeling_type: str
    tick_time: float = 0.31  # simulated time units per tick
    # Model global `distances` (Set.distances.Machines), distances[from][to]. Measured in A0 phase 0
    # (data/a0/travel_times.csv): the minimum travel time from A to B is distances[A][B] u.t. on
    # every route. The diagonal (1) is not a distance: travel to the same machine is 0.
    distances: dict[str, dict[str, float]] = field(default_factory=dict)
    conveyor_speed: float = 0.3  # kept for the platform's estimate_start (aclopi.sim.whatif)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Candidate:
    """One machine able to do the operation. The first fields are the stub's, unchanged."""

    machine: str
    own_remaining: float | None = None  # left of the product's current operation
    travel: float | None = None  # current machine -> this one (0 if it is the current machine)
    arrival: float | None = None  # absolute: now + own_remaining + travel
    queue_time: float | None = None  # processing times of the products in its physical queue (Products.Queue)
    start: float | None = None  # absolute
    finish: float | None = None  # absolute: start + proc_time
    delta_finish: float | None = None  # finish - best finish
    current_remaining: float | None = None  # left of the job in process here (0 if idle or current machine)
    en_route_time: float | None = None  # processing times of the products heading here, not queued nor in process here
    available: bool | None = None  # machine-available? hook of the model (always true for now)
    next_machine: str | None = None  # for operation seq+1: capable machine closest to this one (null if none)
    finish_plus_next: float | None = None  # absolute: finish + travel_next
    delta_finish_plus_next: float | None = None  # finish_plus_next - best finish_plus_next
    # Added by Línea A:
    available_in: float | None = None  # current_remaining + queue_time + en_route_time (own_remaining if current machine)
    proc_time: float | None = None  # Machine.Operations.Time + stochastic extra (not on M1)
    travel_next: float | None = None  # this machine -> next_machine
    is_current_machine: bool | None = None  # reprocessed in place: no travel, ahead of its queue
    queue: list[int] = field(default_factory=list)  # products counted in queue_time
    en_route: list[int] = field(default_factory=list)  # products counted in en_route_time
    stay_time: float | None = None  # occupant / first queued product expected to stay for one more operation
    stay: list[int] = field(default_factory=list)  # products counted in stay_time


@dataclass(frozen=True)
class CandidatesResult:
    product: int
    seq: int
    operation: str | None
    tick: int
    time: float
    valid: bool
    reason: str | None = None  # why it is not valid (unknown-or-finished-product, seq-mismatch, ...)
    candidates: list[Candidate] = field(default_factory=list)  # sorted by finish (ties: machine number)
    # Added by Línea A:
    current_machine: str | None = None
    own_remaining: float | None = None
    next_operation: str | None = None  # operation seq+1 (null if seq is the last one)
    best_by_finish: str | None = None
    best_by_finish_plus_next: str | None = None
    gap_finish: float | None = None  # second - best finish (null with one candidate)
    gap_finish_plus_next: float | None = None
    travel_source: str = "distances"

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)
