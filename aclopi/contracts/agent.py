"""Platform <-> agent contract (L5.5). PROPOSAL for Línea A's review: docs/agent-api.md.

No schema for /decide or next-machine existed in the repo (docs/rule4-decision-hook.md and
contracts/ only define the model hook), so the platform defines it here. Shared by the API and the
mock agent (aclopi.agent_mock).

    platform -> agent   POST {ACLOPI_AGENT_URL}/decide        DecideRequest   -> 202 at once
    agent -> platform   POST /sessions/{id}/next-machine     NextMachineRequest
    agent -> platform   GET /sessions/{id}/candidates, POST /sessions/{id}/what-if (L5.4)
    platform -> agent   GET {ACLOPI_AGENT_URL}/health        -> 200 when the agent is up

With ACLOPI_AGENT_TOKEN set, every call in both directions carries Authorization: Bearer <token>.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Strategy = Literal["b1", "b1b", "agent", "none"]
DecisionLevel = Literal["code-obvious", "code-fallback", "llm", "llm-what-if", "heuristic"]
DECIDING_STRATEGIES = ("b1", "b1b", "agent")  # "none" = rule 4 without a decider (equals rule 3)


class DecideRequest(BaseModel):
    """A product entered a machine and its next operation has several capable machines."""

    model_config = ConfigDict(extra="allow")

    session_id: str
    product: int = Field(description="who of the product")
    seq: int = Field(description="Index in ProductOperations of the operation to decide")
    strategy: Strategy
    mode: Literal["live", "fast"]
    ticks_per_second: float | None = Field(description="Live: 32 x speed; null in fast mode (the run waits)")
    tick: int = Field(description="Tick of the request (the product entered its machine)")
    simulated_time: float
    operation: str | None = Field(None, description="Operation to decide (O1..O9)")
    origin: str | None = Field(None, description="Machine the product is in")
    candidates: list[str] | None = Field(None, description="Machines capable of the operation")


class Latencies(BaseModel):
    model_config = ConfigDict(extra="allow")

    total_ms: float | None = None
    llm_ms: list[float] | None = Field(None, description="One value per LLM call")


class NextMachineRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product: int = Field(ge=0)
    seq: int = Field(ge=0)
    machine: str = Field(pattern=r"^M[1-7]$")
    decision_level: DecisionLevel
    reason: str | None = Field(None, max_length=500)
    latencies: Latencies | None = None


class NextMachineResponse(BaseModel):
    applied: bool
    tick: int
    late: bool = False
    run_state: str | None = None
    pending_decisions: int | None = None
