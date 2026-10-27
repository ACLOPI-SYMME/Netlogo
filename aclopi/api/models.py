"""Pydantic models of the API requests and responses (the OpenAPI contract for Línea A)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from aclopi.workers.protocol import MAX_STEP_TICKS

NETLOGO_SEED_MIN = -2147483648
NETLOGO_SEED_MAX = 2147483647


class SessionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    seed: int = Field(ge=NETLOGO_SEED_MIN, le=NETLOGO_SEED_MAX, description="NetLogo random-seed")
    rule: Literal[1, 2, 3] = Field(description="1 Random Machine, 2 Nearest Machine, 3 Potential Fields")
    modeling_type: Literal["Stochastic", "Deterministic"] = "Stochastic"
    horizon_ticks: int = Field(10000, ge=1, le=1_000_000, description="The run ends (ExportData) at this tick")


class RunParameters(BaseModel):
    seed: int
    rule: int
    modeling_type: str
    horizon_ticks: int


class SessionInfo(BaseModel):
    session_id: str
    status: Literal["active", "lost", "expired"]
    parameters: RunParameters
    ticks: int = Field(description="Last known tick (every advance goes through the API)")
    finished: bool
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
    mean_flow_time: float | None
    utilization: dict[str, float]


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
