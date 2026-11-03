"""Pydantic models of the API requests and responses (the OpenAPI contract for Línea A)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from aclopi.contracts.agent import NextMachineRequest, NextMachineResponse, Strategy  # noqa: F401 (re-exported)

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
    strategy: Strategy | None = Field(
        None, description="Rule 4 only: who decides. b1 / b1b / agent call the agent service (docs/agent-api.md); "
                          "none = rule 4 without a decider (same as rule 3). Default none with rule 4; not "
                          "accepted with rules 1-3")

    @model_validator(mode="after")
    def _strategy_needs_rule4(self) -> "SessionCreate":
        if self.rule != 4 and self.strategy is not None:
            raise ValueError("strategy is only accepted with rule 4")
        if self.rule == 4 and self.strategy is None:
            self.strategy = "none"
        return self


class RunParameters(BaseModel):
    seed: int
    rule: int
    modeling_type: str
    horizon_ticks: int


RunState = Literal["idle", "running_live", "running_fast", "waiting_decision", "paused", "finished", "failed"]


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
    run_state: RunState = Field(description="idle | running_live | running_fast | waiting_decision | paused | "
                                             "finished | failed")
    run_reason: str | None = Field(None, description="Why the run ended, e.g. agent_unavailable (failed)")
    strategy: Strategy | None = Field(None, description="Rule 4: b1 | b1b | agent | none")
    pending_decisions: int = Field(0, description="Fast mode: decisions the run is waiting for")
    warnings: list[str] = Field(default_factory=list, description="e.g. agent_unavailable (live runs still allowed)")
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
    """Provisional fields of Línea A (aclopi/contracts/candidates.py). The platform's stub fills
    own_remaining..delta_finish (simulated time units) and leaves the rest null."""

    model_config = ConfigDict(extra="allow")

    machine: str
    own_remaining: float | None = None
    travel: float | None = None
    arrival: float | None = None
    queue_time: float | None = None
    start: float | None = None
    finish: float | None = None
    delta_finish: float | None = None
    current_remaining: float | None = None
    en_route_time: float | None = None
    available: bool | None = None
    next_machine: str | None = None
    finish_plus_next: float | None = None
    delta_finish_plus_next: float | None = None


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
    loads: dict[str, int] | None = Field(None, description="Products queued at or heading to each machine")
    estimated_entry_ticks: dict[str, int] | None = Field(
        None, description="Estimated ticks from the snapshot until the product enters each machine "
                          "(own remaining operation + travel, or the machine's load); the earlier one runs first")


class SessionMetrics(BaseModel):
    model_config = ConfigDict(extra="allow")

    whatif: dict[str, Any]
    decisions: dict[str, Any] = Field(default_factory=dict, description="Decisions by level, % rule3-fallback, "
                                                                         "single-option, late, latency (L5.5)")


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


class AgentHealth(BaseModel):
    configured: bool
    status: Literal["ok", "down", "unknown", "not_configured"]
    last_check: float | None = None
    last_ok: float | None = None
    last_error: str | None = None
    decide_sent: int = 0
    decide_failed: int = 0


class Health(BaseModel):
    status: Literal["starting", "ready", "degraded", "failed", "stopping"]
    agent: AgentHealth | None = Field(None, description="Agent service (does not affect /health/ready)")
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
