"""Candidate machines for a pending decision (rule 4), with their load and estimated wait.

STUB with the signatures agreed with Línea A, which owns the real implementation:

    compute_candidates(state, product, seq, static, params=CandidateParams()) -> CandidatesResult
    read_model_static(session) -> ModelStatic
    candidates_for_session(session, product, seq, static) -> CandidatesResult

compute_candidates is pure: it only reads a platform-state dict (SimulationSession.state()) and the
ModelStatic read once after setup, so calling it never touches the simulation. Schema:
aclopi/contracts/candidates.py.

Load of a machine = products alive whose Heading.Workstation is that machine (queued at it or on
their way), excluding the one it is processing and the product being decided.
"""

from __future__ import annotations

import json
from typing import Any

from aclopi.contracts.candidates import Candidate, CandidateParams, CandidatesResult, ModelStatic

# Static data of the model, read inside platform-local (no random numbers; machines in who order).
STATIC_REPORTER = (
    "platform-local [ -> json-any (list operations OperationDuration Modeling.Type "
    "(map [m -> [(list Machine.Name Machine.Operations.Type Machine.Operations.Time)] of m] sort machines)) ]"
)


def read_model_static(session: Any) -> ModelStatic:
    """Read the operations table and processing times (call once after each setup)."""
    operations, nominal, modeling_type, machines = json.loads(str(session._report(STATIC_REPORTER)))
    names = [f"O{i + 1}" for i in range(len(operations))]
    return ModelStatic(
        capable_machines={op: [str(m) for m in machines_] for op, machines_ in zip(names, operations)},
        operation_times={str(name): {str(o): float(t) for o, t in zip(types, times)} for name, types, times in machines},
        nominal_times={op: float(t) for op, t in zip(names, nominal)},
        modeling_type=str(modeling_type),
    )


def machine_loads(state: dict[str, Any], exclude: int | None = None) -> dict[str, list[dict[str, Any]]]:
    """Products queued at or heading to each machine (not the one in process, not `exclude`)."""
    in_process = {m["name"]: m.get("product") for m in state["machines"]}
    loads: dict[str, list[dict[str, Any]]] = {name: [] for name in in_process}
    for p in state["products"]:
        machine = p.get("heading_workstation")
        if machine in loads and p["id"] != exclude and p["id"] != in_process[machine]:
            loads[machine].append(p)
    return loads


def _op_time(static: ModelStatic, params: CandidateParams, machine: str, operation: str) -> float:
    base = static.operation_times.get(machine, {}).get(operation, 0.0)
    extra = params.stochastic_extra_time if static.modeling_type == "Stochastic" and machine != "M1" else 0.0
    return base + extra


def compute_candidates(
    state: dict[str, Any],
    product: int,
    seq: int,
    static: ModelStatic,
    params: CandidateParams = CandidateParams(),
) -> CandidatesResult:
    tick, time = int(state["tick"]), float(state["time"])
    p = next((x for x in state["products"] if x["id"] == product), None)

    def invalid(reason: str, operation: str | None = None) -> CandidatesResult:
        return CandidatesResult(product, seq, operation, tick, time, valid=False, reason=reason)

    if p is None:
        return invalid("unknown-or-finished-product")
    operations = list(p.get("operations") or [])
    if not 0 <= seq < len(operations):
        return invalid("invalid-seq")
    operation = str(operations[seq])
    if seq != int(p["sequence_order"]) + 1:
        return invalid("seq-mismatch", operation)
    if not any(m.get("product") == product for m in state["machines"]):
        return invalid("not-in-machine", operation)

    machines = {m["name"]: m for m in state["machines"]}
    loads = machine_loads(state, exclude=product)
    candidates = []
    for name in static.capable_machines.get(operation, []):
        m = machines[name]
        busy = m.get("state") == "Machine.Processing"
        remaining = float(m["remaining"]) if busy and m.get("remaining") is not None else 0.0
        queued = sum(_op_time(static, params, name, str(q.get("next_operation"))) for q in loads[name])
        candidates.append(Candidate(
            machine=name, load=len(loads[name]), busy=busy, remaining_time=round(remaining, 4),
            estimated_wait=round(remaining + queued, 4),
            operation_time=round(_op_time(static, params, name, operation), 4),
        ))
    candidates.sort(key=lambda c: (c.estimated_wait, c.machine))
    return CandidatesResult(product, seq, operation, tick, time, valid=True, candidates=candidates)


def candidates_for_session(session: Any, product: int, seq: int, static: ModelStatic) -> CandidatesResult:
    """compute_candidates on the session's current state (platform-state: no random numbers)."""
    return compute_candidates(session.state(), product, seq, static)
