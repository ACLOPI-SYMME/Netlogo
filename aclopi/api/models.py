"""Pydantic models of the API requests and responses (the OpenAPI contract for Línea A)."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator, model_serializer, model_validator

from aclopi.contracts.agent import NextMachineRequest, NextMachineResponse, Strategy  # noqa: F401 (re-exported)
# GET /sessions/{id}/candidates answers Línea A's schema as is (no copy in the API).
from aclopi.contracts.candidates import Candidate, CandidatesResult  # noqa: F401 (re-exported)

from aclopi.workers.protocol import MAX_STEP_TICKS

NETLOGO_SEED_MIN = -2147483648
NETLOGO_SEED_MAX = 2147483647


ProductType = Literal["A", "I", "P", "B", "E", "L", "T"]


class ProductItem(BaseModel):
    """One product of an order list. PO, Item ID and # together identify the product (`id`); they and
    the due date are platform data: the NetLogo model only receives the type and the priority."""

    model_config = ConfigDict(extra="forbid")

    po: str | None = Field(None, max_length=100, description="Product Order (PO)")
    item_id: str | None = Field(None, max_length=100, description="Item ID")
    number: str | None = Field(None, max_length=100, description='"#" column of the order')
    type: ProductType = Field(description="One of the model's product types (case-insensitive on input)")
    priority: int = Field(80, ge=60, le=100, description="Stored on the product; no rule nor the agent uses it today")
    due_date: float | None = Field(None, ge=0, description="Due date in simulated time units (u.t.); stored and "
                                                           "shown, not used by the simulation")

    @model_validator(mode="before")
    @classmethod
    def _drop_derived(cls, value: Any) -> Any:
        if isinstance(value, dict) and "id" in value:  # the derived id may come back (e.g. a saved run repeated)
            value = {k: v for k, v in value.items() if k != "id"}
        return value

    @field_validator("type", mode="before")
    @classmethod
    def _upper(cls, value: Any) -> Any:
        return value.strip().upper() if isinstance(value, str) else value

    @field_validator("po", "item_id", "number", mode="before")
    @classmethod
    def _text(cls, value: Any) -> Any:
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    @computed_field(description='"PO-Item ID-#" when the three are given: the product\'s id (stored with it)')
    @property
    def id(self) -> str | None:
        return product_id(self.po, self.item_id, self.number)

    @model_serializer(mode="wrap")
    def _no_nulls(self, handler: Any) -> dict[str, Any]:
        return {k: v for k, v in handler(self).items() if v is not None}  # missing optional fields are left out


def product_id(po: Any, item_id: Any, number: Any) -> str | None:
    """The product's id: PO, Item ID and # joined with "-" (None unless the three are given)."""
    parts = [str(x).strip() if x is not None else "" for x in (po, item_id, number)]
    return "-".join(parts) if all(parts) else None


def unique_ids(products: list[Any]) -> list[Any]:
    """Raises ValueError if two products share an id (PO-Item ID-#). Accepts ProductItem or dicts."""
    seen: dict[str, int] = {}
    for n, p in enumerate(products, start=1):
        pid = p.id if isinstance(p, ProductItem) else product_id(p.get("po"), p.get("item_id"), p.get("number"))
        if pid is not None:
            if pid in seen:
                raise ValueError(f"product {n}: the id {pid} (PO-Item ID-#) repeats product {seen[pid]}")
            seen[pid] = n
    return products


# The platform runs at most 30 products per list (the size of Línea A's experiments); SimulationSession
# itself accepts up to MAX_PRODUCT_LIST (1000) for in-process experiments.
MAX_PLATFORM_PRODUCTS = 30
ProductList = Annotated[list[ProductItem], Field(min_length=1, max_length=MAX_PLATFORM_PRODUCTS)]


class ScenarioChoice(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field("S0", description="Only S0 (the original plant): scenarios are not available")
    params: dict[str, Any] | None = Field(None, description="Must be empty")


class ScenarioRef(BaseModel):
    id: str
    params: dict[str, Any] = Field(description="The parameters used, defaults filled in")


class ScenarioSummary(BaseModel):
    applied: int = 0
    skipped: int = Field(0, description="Events not applied, e.g. a failure on an idle machine (machine-idle)")


class SessionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    seed: int | None = Field(None, ge=NETLOGO_SEED_MIN, le=NETLOGO_SEED_MAX,
                             description="NetLogo random-seed. Optional: without it the platform draws one "
                                         "(secrets) and returns it, with seed_source 'random'")
    product_set_id: str | None = Field(None, description="Saved product set to use (the session keeps a copy)")
    products: ProductList | None = Field(None, description="Product list inline, in entry order")
    rule: Literal[1, 2, 3, 4] = Field(description="1 Random Machine, 2 Nearest Machine, 3 Potential Fields, "
                                                  "4 AI Agent (without a decider it behaves exactly as rule 3)")
    modeling_type: Literal["Stochastic", "Deterministic"] = "Stochastic"
    horizon_ticks: int = Field(10000, ge=1, le=1_000_000, description="The run ends (ExportData) at this tick")
    strategy: Strategy | None = Field(
        None, description="Rule 4 only, optional: who decides. Default agent (the AI agent: code, LLM, what-if; "
                          "docs/agent-api.md). b1 / b1b (baselines of the experiments) and none (rule 4 without a "
                          "decider, same as rule 3; tests) are accepted but are not user options. Not accepted "
                          "with rules 1-3")
    scenario: ScenarioChoice | None = Field(
        None, description="Scenarios are not available on the platform (docs/scenarios.md): it is accepted only "
                          "as S0 without params (the original plant); any other: 422 scenarios_unavailable")

    @field_validator("products")
    @classmethod
    def _ids(cls, value: list[ProductItem] | None) -> list[ProductItem] | None:
        return unique_ids(value) if value else value

    @model_validator(mode="after")
    def _strategy_needs_rule4(self) -> "SessionCreate":
        if self.rule != 4 and self.strategy is not None:
            raise ValueError("strategy is only accepted with rule 4")
        if self.rule == 4 and self.strategy is None:
            self.strategy = "agent"
        if self.product_set_id is not None and self.products is not None:
            raise ValueError("give product_set_id or products, not both")
        return self


class RunParameters(BaseModel):
    seed: int = Field(description="The seed used, given or drawn (see seed_source): the run can be repeated")
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
    seed_source: Literal["user", "random"] = "user"
    product_set_id: str | None = None
    products_total: int | None = Field(None, description="Length of the session's product list (None: generated "
                                                         "from the seed, as before)")
    products_hash: str | None = Field(None, description="sha256 of the session's product list")
    products: list[ProductItem] | None = Field(None, description="The session's own copy of the list, in entry order "
                                                                 "(apply-order changes it; the saved set does not change)")
    scenario: ScenarioRef = Field(default_factory=lambda: ScenarioRef(id="S0", params={}))
    scenario_summary: ScenarioSummary = Field(default_factory=ScenarioSummary,
                                              description="Scenario events of this run: applied and skipped")
    last_run_id: str | None = Field(None, description="Last run of this session saved to the results store")
    optimize_status: str | None = Field(None, description="Status of the session's last optimize order, if any")
    optimization: "AppliedOptimization | None" = Field(None, description="The order applied by optimize order")
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
    products_total: int | None = Field(None, description="Product list: its length (None without a list)")
    all_done: bool = Field(False, description="Product list: every product created and finished")
    makespan_ticks: int | None = Field(None, description="Ticks until the last product of the list finished")
    makespan_time: float | None = Field(None, description="Simulated time until the last product of the list finished")
    created: int = Field(description="Products created so far (finished + wip)")
    work_completed: float = Field(description="Processing work done, in time units of nominal processing time "
                                              "(OperationDuration); an operation in progress adds its processed fraction")


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


class ProductSetIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=200)
    products: ProductList

    @field_validator("products")
    @classmethod
    def _ids(cls, value: list[ProductItem]) -> list[ProductItem]:
        return unique_ids(value)


class ProductSetSummary(BaseModel):
    id: str
    name: str
    total: int
    counts: dict[str, int]
    hash: str
    created_at: float
    updated_at: float


class ProductSet(ProductSetSummary):
    products: list[ProductItem]


class ParsedCsv(BaseModel):
    products: list[ProductItem]
    total: int
    counts: dict[str, int]
    hash: str


class GenerateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    seed: int | None = Field(None, ge=NETLOGO_SEED_MIN, le=NETLOGO_SEED_MAX,
                             description="Optional; without it a random seed is drawn and returned")
    count: int = Field(ge=1, le=MAX_PLATFORM_PRODUCTS)


class GeneratedProducts(BaseModel):
    seed: int
    seed_source: Literal["user", "random"]
    products: list[ProductItem]
    total: int
    counts: dict[str, int]
    hash: str


class RunRecord(BaseModel):
    """A saved run (L5.7): parameters, outcome and summaries."""

    model_config = ConfigDict(extra="allow")

    run_id: str
    session_id: str
    created_at: float
    finished_at: float
    status: Literal["finished", "failed", "stopped"]
    reason: str | None = None
    ticks: int | None = None
    rule: int
    strategy: str | None = None
    seed: int
    seed_source: str
    horizon_ticks: int
    mode: str | None = None
    product_set_id: str | None = None
    products_hash: str | None = None
    products: list[ProductItem] | None = None
    scenario_id: str = "S0"
    scenario: ScenarioRef | None = None
    scenario_events: list[dict[str, Any]] = Field(default_factory=list, description="AppliedEvent records "
                                                  "(tick, kind, machine, value, label, applied, skip_reason, before, after)")
    scenario_summary: ScenarioSummary | None = None
    kpis: dict[str, Any]
    decisions_summary: dict[str, Any] | None = None
    whatif_summary: dict[str, Any] | None = None
    optimization: AppliedOptimization | None = Field(None, description="Optimize order applied before the run: "
                                                                       "estimated makespan and saving")


class RunPage(BaseModel):
    runs: list[RunRecord]
    next_cursor: str | None = None


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


# ----- optimize order (docs/optimize-order.md) -----

OptimizeStatus = Literal["running", "waiting_turn", "waiting_ai", "done", "cancelled", "failed"]


class OptimizeRequest(BaseModel):
    """No fields: a single mode (ACLOPI_OPTIMIZE_ROUNDS rounds with the AI). The body may be empty; fields sent by
    older clients (e.g. "mode") are ignored."""

    model_config = ConfigDict(extra="ignore")


class ApplyOrderRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate: int = Field(ge=0, description="index of an evaluated order (GET .../optimize-order: evaluated[].index)")


class OptimizeCandidate(BaseModel):
    index: int
    origin: Literal["original", "heuristic", "ai"]
    round: int = Field(description="0: original and heuristic; 1..N: the AI's rounds")
    label: str = Field(description='"Original", "Heuristic" or "AI round k · i"')
    order: list[int] = Field(description="permutation of the positions of the session's list at the start")
    types: str = Field(description="product types in that order, e.g. ABIE")
    makespan_ticks: int | None = None
    makespan_time: float | None = Field(None, description="u.t.")
    all_done: bool
    saving_time: float | None = Field(None, description="u.t. saved against the original (negative: worse)")
    saving_pct: float | None = None
    reasoning: str | None = None
    analysis: str | None = Field(None, description="the AI's analysis of its round")
    wall_s: float | None = None


class OptimizeDiscarded(BaseModel):
    model_config = ConfigDict(extra="allow")

    origin: str
    round: int
    label: str
    order: list[Any] | None = None
    reason: Literal["invalid", "same_as"]
    same_as: str | None = None
    reasoning: str | None = None


class OptimizeRound(BaseModel):
    round: int
    analysis: str | None = None
    latency_ms: float | None = None
    error: str | None = None


class Optimization(BaseModel):
    optimization_id: str
    session_id: str
    status: OptimizeStatus
    round: int = Field(description="round in progress or last one (0: original and heuristic)")
    rounds: int = Field(description="rounds with the AI planned")
    progress_pct: float
    current: dict[str, Any] | None = Field(None, description="simulation in progress: label, ticks, done, total")
    ai_elapsed_s: float | None = Field(None, description="seconds the AI has been thinking (waiting_ai)")
    waited_s: float = Field(description="seconds waited for a turn at the AI (429)")
    strategy: str = Field(description="simulate_list strategy: rule1-rule3, b1 or b1b")
    simulation_mode: str
    seed: int
    max_ticks: int
    products: list[ProductItem] = Field(description="the session's list at the start (the orders index it)")
    evaluated: list[OptimizeCandidate]
    discarded: list[OptimizeDiscarded]
    rounds_info: list[OptimizeRound]
    best: int | None = Field(None, description="index of the order with the lowest makespan")
    warning: str | None = None
    error: str | None = None
    applied: int | None = Field(None, description="index of the order applied (apply-order)")
    stopped_early: bool
    started_at: float
    finished_at: float | None = None


class AppliedOptimization(BaseModel):
    """Saved in the session and in its runs when an order is applied: the estimate next to the real run."""

    model_config = ConfigDict(extra="allow")

    optimized: bool
    order: list[int]
    origin: str
    label: str | None = None
    round: int | None = None
    estimated_makespan_ticks: int | None = None
    estimated_makespan_time: float | None = None
    estimated_saving_time: float | None = None
    estimated_saving_pct: float | None = None
    estimate_strategy: str | None = None
    estimate_mode: str | None = None
    optimization_id: str | None = None


class ApplyOrderResponse(BaseModel):
    session: SessionInfo
    products: list[ProductItem] = Field(description="the session's list in its new entry order")
    optimization: Optimization


SessionInfo.model_rebuild()
RunRecord.model_rebuild()
ApplyOrderResponse.model_rebuild()

STEP_N_DESCRIPTION = f"Ticks to advance, 1..{MAX_STEP_TICKS}"
