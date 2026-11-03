"""Pydantic models of the API requests and responses (the OpenAPI contract for Línea A)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from aclopi.workers.protocol import MAX_STEP_TICKS

NETLOGO_SEED_MIN = -2147483648
NETLOGO_SEED_MAX = 2147483647


class SessionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    seed: int = Field(ge=NETLOGO_SEED_MIN, le=NETLOGO_SEED_MAX, description="NetLogo random-seed")
    rule: Literal[1, 2, 3, 4] = Field(description="1 Random Machine, 2 Nearest Machine, 3 Potential Fields, "
                                                  "4 AI Agent (without a decider it behaves exactly as rule 3)")
    modeling_type: Literal["Stochastic", "Deterministic"] = "Stochastic"
    horizon_ticks: int = Field(10000, ge=1, le=1_000_000, description="The run ends (ExportData) at this tick")


class RunParameters(BaseModel):
    seed: int
    rule: int
    modeling_type: str
    horizon_ticks: int


RunState = Literal["idle", "running_live", "running_fast", "paused", "finished"]


class RunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["live", "fast"] = Field(description="live: paced (32 ticks/s x speed); fast: no speed limit")
    speed: Literal[0.5, 1, 2, 4] = Field(1, description="Live speed factor (ignored in fast mode)")


class SessionInfo(BaseModel):
    session_id: str
    status: Literal["active", "lost", "expired"]
    parameters: RunParameters
    ticks: int = Field(description="Last known tick (from requests and from the run's pushes)")
    finished: bool
    run_state: RunState = Field(description="idle | running_live | running_fast | paused | finished")
    mode: Literal["live", "fast"] | None = Field(description="Mode of the current or paused run")
    speed: float | None = Field(description="Live speed factor of the current or paused run")
    watchers: int = Field(description="WebSocket clients connected to /ws/sessions/{id}")
    lost_reason: str | None = Field(None, description="Why the session is lost or expired")
    worker_slot: int | None
    created_at: float = Field(description="Unix time (s)")
    last_activity: float = Field(description="Unix time (s) of the last request to this session")


class StepResult(BaseModel):
    ticks: int
    advanced: int = Field(description="Ticks actually advanced (fewer when the run ends)")
    finished: bool


class PlantState(BaseModel):
    """platform-state: compact state of the plant at the current tick."""

    model_config = ConfigDict(extra="allow")

    tick: int
    time: float = Field(description="Simulated.Time")
    terminado: str
    finished: int = Field(description="Finished products")
    segments: dict[str, float]
    gates: list[dict[str, Any]]
    machines: list[dict[str, Any]]
    products: list[dict[str, Any]] = Field(description="Products not finished")


class PlantLayout(BaseModel):
    """platform-layout: static geometry of the plant."""

    model_config = ConfigDict(extra="allow")

    nodes: list[dict[str, Any]]
    conveyors: list[dict[str, Any]]
    curves: dict[str, Any]
    machines: list[dict[str, Any]]
    sensors: list[dict[str, Any]]
    switches: dict[str, list[int]]


class Event(BaseModel):
    model_config = ConfigDict(extra="allow")

    tick: int
    event: str
    who: Any = None
    product_type: Any = None
    location: Any = None
    operation: Any = None
    next_operation: Any = None
    destination: Any = None
    time: Any = None


class Kpis(BaseModel):
    ticks: int
    simulated_time: float
    finished: int
    wip: int
    throughput: float
    mean_flow_time: float | None = Field(description="Mean of (last completion - first operation start, "
                                                     "ProductRealStart) over finished products; not from creation")
    utilization: dict[str, float]
    created: int = Field(description="Products created so far (finished + wip)")
    work_completed: float = Field(description="Processing work done, in time units of nominal processing time "
                                              "(OperationDuration); an operation in progress adds its processed fraction")


class CandidateInfo(BaseModel):
    model_config = ConfigDict(extra="allow")

    machine: str
    load: int = Field(description="Products queued at the machine or heading to it (not the one in process)")
    busy: bool
    remaining_time: float
    estimated_wait: float
    operation_time: float


class CandidatesResponse(BaseModel):
    """Schema owned by Línea A (aclopi/contracts/candidates.py); extra fields are allowed."""

    model_config = ConfigDict(extra="allow")

    product: int
    seq: int
    operation: str | None
    tick: int
    time: float
    valid: bool
    reason: str | None = Field(None, description="Why the request is not valid (e.g. seq-mismatch)")
    candidates: list[CandidateInfo]


class WhatIfRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product: int = Field(ge=0, description="who of the product being processed")
    seq: int = Field(ge=0, description="Index in ProductOperations of the operation to decide (CurrentSequenceOrder + 1)")
    options: list[str] = Field(min_length=2, max_length=2, description="Exactly two different machines to test")
    max_ticks: int = Field(3000, ge=1, le=5000, description="Cap of ticks simulated per copy")
    budget_ms: int = Field(10000, ge=2000, le=15000,
                           description="Time budget of the whole what-if (both copies, in series). The agent sets it "
                                       "from its decision deadline: ~10 s fits from M2-M7; from M1 (~8 s) it does not "
                                       "fit together with the LLM calls")

    @field_validator("options")
    @classmethod
    def _distinct(cls, value: list[str]) -> list[str]:
        if len(set(value)) != len(value):
            raise ValueError("the two options must be different machines")
        return value


class OthersMetric(BaseModel):
    window_tick: int
    work: float = Field(description="Nominal processing work done by the other products in the window")
    wait: float = Field(description="Time the other products spent in the plant without being processed")
    presence: float = Field(description="Time the other products spent in the plant during the window")
    finished: int


class WhatIfOption(BaseModel):
    model_config = ConfigDict(extra="allow")

    machine: str
    entered: bool = False
    stop_reason: Literal["entered", "cap", "stalled", "pruned", "timeout", "horizon", "error"] | None = None
    entry_tick: int | None = None
    entry_time: float | None = None
    entry_estimated: bool = False
    op_end_time: float | None = None
    op_end_estimated: bool = False
    others: OthersMetric | None = None
    ticks_simulated: int = 0
    stop_tick: int | None = None
    cap_reached: bool = False
    stalled: bool = False
    pruned: bool = False
    timed_out: bool = False
    skipped: bool = False
    duration_ms: float | None = None
    import_ms: float | None = None
    advance_ms: float | None = None
    diagnostic_file: str | None = None
    error: str | None = None


class WhatIfTimings(BaseModel):
    export: float | None
    import_: float | None = Field(alias="import")
    advance: float | None
    total: float

    model_config = ConfigDict(populate_by_name=True)


class WhatIfResponse(BaseModel):
    status: Literal["ok", "timeout", "skipped", "error"]
    skipped_reason: Literal["no-free-worker", "already-used", "entry-beyond-cap"] | None = None
    snapshot_tick: int | None = None
    snapshot_time: float | None = None
    operation: str | None = None
    window_tick: int | None = None
    run_order: list[str]
    timings_ms: WhatIfTimings
    options: list[WhatIfOption]
    would_skip_entry_beyond_cap: bool | None = None
    loads: dict[str, int] | None = None
    saturation_queue: int | None = None


class SessionMetrics(BaseModel):
    model_config = ConfigDict(extra="allow")

    whatif: dict[str, Any]


class WorkerInfo(BaseModel):
    slot: int
    role: Literal["session", "whatif"]
    ready: bool
    state: str = Field(description="starting | free | busy | restarting | failed | stopped")
    pid: int | None
    rss_mib: float | None
    restarts: int
    session_id: str | None


class SessionCounts(BaseModel):
    active: int
    max: int


class Health(BaseModel):
    status: Literal["starting", "ready", "degraded", "failed", "stopping"]
    uptime_s: float
    startup_s: float | None
    sessions: SessionCounts
    workers: list[WorkerInfo]


class Probe(BaseModel):
    status: str


class ErrorBody(BaseModel):
    code: str
    detail: str
    session_id: str | None = None


STEP_N_DESCRIPTION = f"Ticks to advance, 1..{MAX_STEP_TICKS}"
