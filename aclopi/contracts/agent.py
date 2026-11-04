"""Platform <-> agent contract (L5.5), agreed with Línea A on 4 Nov: docs/agent-api.md.

Shared by the API, the mock agent (aclopi.agent_mock) and the agent (aclopi.agent).

    platform -> agent   POST {ACLOPI_AGENT_URL}/decide        DecideRequest   -> 202 at once
    agent -> platform   POST /sessions/{id}/next-machine     NextMachineRequest
    agent -> platform   GET /sessions/{id}/candidates, POST /sessions/{id}/what-if (L5.4)
    platform -> agent   GET {ACLOPI_AGENT_URL}/health        -> 200 when the agent is up

With ACLOPI_AGENT_TOKEN set, every call in both directions carries Authorization: Bearer <token>.
"""

from __future__ import annotations

import secrets
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Strategy = Literal["b1", "b1b", "agent", "none"]
DecisionLevel = Literal["code-obvious", "code-fallback", "llm", "llm-what-if", "heuristic"]
DECIDING_STRATEGIES = ("b1", "b1b", "agent")  # "none" = rule 4 without a decider (equals rule 3)


def bearer_matches(authorization: str | None, token: str) -> bool:
    """Authorization header == "Bearer <token>", compared in constant time (secrets.compare_digest,
    on bytes so a non-ASCII header is a mismatch instead of a TypeError)."""
    if authorization is None:
        return False
    return secrets.compare_digest(authorization.encode("utf-8"), f"Bearer {token}".encode("utf-8"))


class M1Summary(BaseModel):
    busy: bool
    remaining: float = Field(description="What is left of its job (u.t.; 0 if idle)")
    queue_length: int


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
    # Agreed with Línea A on 4 Nov: product context and plant summary, read in the platform's worker
    # from one platform-state when the request is collected (no random numbers consumed). In live
    # mode that is the end of the block that read the request (context_tick >= tick); in fast mode the
    # end of the go that queued it (tick or tick + 1).
    context_tick: int | None = Field(None, description="Tick of the state the context was read from")
    current_machine: str | None = Field(None, description="Machine processing the product (null if it left it)")
    current_operation: str | None = Field(None, description="Operation in process (seq - 1)")
    own_remaining: float | None = Field(None, description="What is left of the current operation (u.t.)")
    next_operation: str | None = Field(None, description="Operation seq + 1, after the one decided (null if last)")
    pending_operations: list[str] | None = Field(
        None, description="Operations from seq onwards, in order (the one decided first)")
    products_in_plant: int | None = Field(None, description="Products alive in the plant")
    m1: M1Summary | None = Field(None, description="M1 (O8 / O9, shared by every product)")


DECIDE_CONTEXT_FIELDS = ("context_tick", "current_machine", "current_operation", "own_remaining", "next_operation",
                         "pending_operations", "products_in_plant", "m1")


class Latencies(BaseModel):
    """Extra keys are kept (e.g. what_if_ms from the agent)."""

    model_config = ConfigDict(extra="allow")

    total_ms: float | None = None
    llm_ms: list[float] | None = Field(None, description="One value per LLM call")
    what_if_ms: float | None = Field(None, description="Time spent in POST /what-if, if the agent asked for one")


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
