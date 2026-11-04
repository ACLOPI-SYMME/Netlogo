"""Candidate machines for a pending decision (rule 4), with their load and estimated wait.

compute_candidates is Línea A's implementation (below). estimate_start, machine_loads and
travel_time are the platform's stub helpers, kept unchanged because aclopi.sim.whatif and the
worker use them. Signatures agreed with the platform:

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
    "(map [m -> [(list Machine.Name Machine.Operations.Type Machine.Operations.Time)] of m] sort machines) "
    "distances) ]"
)

# Conveyor speed per tick on straight conveyors: `jump (0.300 * speed-factor)` in Product.Movement,
# with speed-factor 1 for every product (create.product). Curves move a little slower.
CONVEYOR_SPEED = 0.3


def read_model_static(session: Any) -> ModelStatic:
    """Read the operations table, processing times and distances (call once after each setup)."""
    operations, nominal, modeling_type, machines, distances = json.loads(str(session._report(STATIC_REPORTER)))
    names = [f"O{i + 1}" for i in range(len(operations))]
    machine_names = [f"M{i + 1}" for i in range(len(distances))]  # rows and columns are M1..M7
    return ModelStatic(
        capable_machines={op: [str(m) for m in machines_] for op, machines_ in zip(names, operations)},
        operation_times={str(name): {str(o): float(t) for o, t in zip(types, times)} for name, types, times in machines},
        nominal_times={op: float(t) for op, t in zip(names, nominal)},
        modeling_type=str(modeling_type),
        distances={a: {b: float(d) for b, d in zip(machine_names, row)} for a, row in zip(machine_names, distances)},
        conveyor_speed=CONVEYOR_SPEED,
    )


def travel_time(static: ModelStatic, origin: str | None, target: str) -> float:
    """Simulated time to travel from machine `origin` to machine `target` (0 if unknown or the same)."""
    if not origin or origin == target or origin not in static.distances:
        return 0.0
    return static.distances[origin].get(target, 0.0) / static.conveyor_speed * static.tick_time


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


def _remaining(m: dict[str, Any]) -> float:
    return float(m["remaining"]) if m.get("state") == "Machine.Processing" and m.get("remaining") is not None else 0.0


def estimate_start(state: dict[str, Any], product: int, machine: str, operation: str, static: ModelStatic,
                   params: CandidateParams = CandidateParams(), origin: str | None = None,
                   left_time: float | None = None) -> dict[str, float]:
    """When the product could start (and finish) the operation on `machine`, from a platform-state.

      arrival    = now + own_remaining + travel (minus the travel already done, if it left)
      queue_time = what is left of the machine's job + processing times of its load
      start      = max(arrival, now + queue_time);  finish = start + processing time here
    own_remaining: what is left of its operation if it is in a machine (origin = that machine);
    otherwise `origin` (its last machine) and `left_time` (when it left) give the travel left.
    The travel ignores gates and products ahead (docs/whatif.md, "Estimación de la entrada").
    TODO(Línea A): replaced by the real candidates' estimated start when it arrives.
    """
    now = float(state["time"])
    machines = {m["name"]: m for m in state["machines"]}
    current = next((m for m in state["machines"] if m.get("product") == product), None)
    if current is not None:
        own, origin, travelled = _remaining(current), current["name"], 0.0
    else:
        own, travelled = 0.0, max(0.0, now - left_time) if left_time is not None else 0.0
    travel = max(0.0, travel_time(static, origin, machine) - travelled)
    queue = _remaining(machines[machine]) + sum(
        _op_time(static, params, machine, str(q.get("next_operation"))) for q in machine_loads(state, exclude=product)[machine])
    arrival = now + own + travel
    start = max(arrival, now + queue)
    return {"own_remaining": own, "travel": travel, "arrival": arrival, "queue_time": queue, "start": start,
            "finish": start + _op_time(static, params, machine, operation)}


# ----- Línea A: candidates for a rule 4 decision (docs/agent-status.md, aclopi/contracts/candidates.py) -----
#
# Measured facts used here (A0 phase 0, data/a0/travel_times.csv):
# - travel(A -> B) = distances[A][B] u.t. (minimum observed on every route); the diagonal is not a distance.
# - Same machine: when the next operation is assigned to the machine the product is in, the product
#   starts it in place in the same tick it completes (the entry gate still has the product on its
#   station sensor, the machine has just become Idle and the gate indicator is still 1), so it has no
#   travel and goes ahead of the machine's queue.


def machine_number(name: str) -> int:
    return int(name[1:])


def travel(static: ModelStatic, origin: str, target: str) -> float:
    """Conveyor travel time in u.t. (0 to the same machine)."""
    return 0.0 if origin == target else float(static.distances[origin][target])


def proc_time(static: ModelStatic, machine: str, operation: str, params: CandidateParams = CandidateParams()) -> float:
    """Expected processing time: Machine.Operations.Time + mean of the exponential part (Stochastic, not M1)."""
    return _op_time(static, params, machine, operation)


def _next_machine(static: ModelStatic, machine: str, operation: str | None) -> tuple[str | None, float]:
    """Machine for the following operation closest to `machine` (0 if `machine` can do it); ties: lowest number."""
    if operation is None:
        return None, 0.0
    options = static.capable_machines.get(operation, [])
    if not options:
        return None, 0.0
    best = min(options, key=lambda m: (travel(static, machine, m), machine_number(m)))
    return best, travel(static, machine, best)


def _stay_operations(q: dict[str, Any], machine: str, counted_next: bool, static: ModelStatic, chain_max: int) -> list[str]:
    """Operations that product q may still do on `machine` beyond what is already counted: the chain
    of consecutive operations `machine` can do, starting at the occupant's next operation (or the one
    after it, if the next one is already counted because q's decision sent it here) or, for the first
    queued product, at the operation after the one it is queued for; up to chain_max operations."""
    ops = [str(o) for o in (q.get("operations") or [])]
    k = int(q["sequence_order"])  # occupant: operation in process; queued: operation it waits for
    k += 2 if counted_next else 1
    chain: list[str] = []
    while k < len(ops) and len(chain) < chain_max and machine in static.capable_machines.get(ops[k], []):
        chain.append(ops[k])
        k += 1
    return chain


def _remaining_at(machine: dict[str, Any], now: float) -> float:
    if machine.get("state") != "Machine.Processing" or machine.get("next_completion") is None:
        return 0.0
    return max(0.0, float(machine["next_completion"]) - now)


def compute_candidates(
    state: dict[str, Any],
    product: int,
    seq: int,
    static: ModelStatic,
    params: CandidateParams = CandidateParams(),
) -> CandidatesResult:
    """Candidates for operation `seq` of `product`, from a platform-state dict (pure function)."""
    tick, now = int(state["tick"]), float(state["time"])
    products = {int(x["id"]): x for x in state["products"]}
    machines = {m["name"]: m for m in state["machines"]}
    p = products.get(product)

    def invalid(reason: str, operation: str | None = None) -> CandidatesResult:
        return CandidatesResult(product, seq, operation, tick, now, valid=False, reason=reason)

    if p is None:
        return invalid("unknown-or-finished-product")
    operations = [str(o) for o in (p.get("operations") or [])]
    if not 0 <= seq < len(operations):
        return invalid("invalid-seq")
    operation = operations[seq]
    if seq != int(p["sequence_order"]) + 1:
        return invalid("seq-mismatch", operation)
    current = next((name for name, m in machines.items() if m.get("product") == product), None)
    if current is None:
        return invalid("not-in-machine", operation)
    own = _remaining_at(machines[current], now)
    next_operation = operations[seq + 1] if seq + 1 < len(operations) else None

    in_process = {name: m.get("product") for name, m in machines.items()}
    processing_at = {pid: name for name, pid in in_process.items() if pid is not None}
    queued = {name: [int(q) for q in (m.get("queue") or [])] for name, m in machines.items()}

    def heading_to(q: dict[str, Any], target: str) -> str | None:
        """Operation q will do at `target` if it is on its way there (not queued nor in process there)."""
        qid = int(q["id"])
        if qid == product or qid in queued.get(target, []):
            return None
        if qid in processing_at:
            # In process (here or elsewhere): only a decision already taken for its next operation counts.
            # In process here and sent here again: it is reprocessed in place, ahead of the queue.
            ops = [str(o) for o in (q.get("operations") or [])]
            k = int(q["sequence_order"]) + 1
            if q.get("ai_next_machine") == target and q.get("ai_decision_seq") == k and k < len(ops):
                return ops[k]
            return None
        if q.get("heading_workstation") == target:  # travelling, or waiting to leave its last station
            return str(q.get("next_operation"))
        return None

    def expected_arrival(q: dict[str, Any], target: str) -> float:
        """Relative arrival of an en-route product (0 if already travelling: its progress is unknown)."""
        where = processing_at.get(int(q["id"]))
        if where is None:
            return 0.0
        return _remaining_at(machines[where], now) + travel(static, where, target)

    built = []
    for name in static.capable_machines.get(operation, []):
        proc = proc_time(static, name, operation, params)
        if name == current:
            trav, cur_rem, qtime, rtime, avail_in, queue_ids, route_ids = 0.0, 0.0, 0.0, 0.0, own, [], []
            stay_ids, stime = [], 0.0
        else:
            trav = travel(static, current, name)
            cur_rem = _remaining_at(machines[name], now)
            queue_ids = [q for q in queued.get(name, []) if q != product and q in products]
            qtime = sum(proc_time(static, name, str(products[q].get("next_operation")), params) for q in queue_ids)
            route_ids, rtime = [], 0.0
            for q in products.values():
                op_q = heading_to(q, name)
                if op_q is None:
                    continue
                if params.en_route_only_earlier and expected_arrival(q, name) > own + trav:
                    continue
                route_ids.append(int(q["id"]))
                rtime += proc_time(static, name, op_q, params)
            stay_ids, stime = [], 0.0
            if params.occupant_may_stay:
                for q in (in_process.get(name), queue_ids[0] if queue_ids else None):  # occupant, first queued
                    if q is None or q == product or q not in products:
                        continue
                    chain = _stay_operations(products[q], name, q in route_ids, static, params.occupant_chain_max)
                    if chain:
                        stay_ids.append(int(q))
                        stime += sum(proc_time(static, name, op, params) for op in chain)
            avail_in = cur_rem + qtime + rtime + stime
        start = now + max(own + trav, avail_in)
        finish = start + proc
        nxt, trav_next = _next_machine(static, name, next_operation)
        built.append(dict(
            machine=name, own_remaining=own, travel=trav, arrival=now + own + trav, queue_time=qtime,
            start=start, finish=finish, current_remaining=cur_rem, en_route_time=rtime, available=True,
            next_machine=nxt, finish_plus_next=finish + trav_next, available_in=avail_in, proc_time=proc,
            travel_next=trav_next, is_current_machine=name == current, queue=queue_ids, en_route=sorted(route_ids),
            stay_time=stime, stay=stay_ids))

    def ranked(key: str) -> list[dict[str, Any]]:
        return sorted(built, key=lambda c: (c[key], machine_number(c["machine"])))

    by_finish, by_next = ranked("finish"), ranked("finish_plus_next")
    best_f, best_n = (by_finish[0]["finish"], by_next[0]["finish_plus_next"]) if built else (0.0, 0.0)
    candidates = [Candidate(**{k: round(v, 4) if isinstance(v, float) else v for k, v in c.items()},
                            delta_finish=round(c["finish"] - best_f, 4),
                            delta_finish_plus_next=round(c["finish_plus_next"] - best_n, 4)) for c in by_finish]
    gap = lambda r, k: round(r[1][k] - r[0][k], 4) if len(r) > 1 else None  # noqa: E731
    return CandidatesResult(
        product, seq, operation, tick, now, valid=True, candidates=candidates,
        current_machine=current, own_remaining=round(own, 4), next_operation=next_operation,
        best_by_finish=by_finish[0]["machine"] if built else None,
        best_by_finish_plus_next=by_next[0]["machine"] if built else None,
        gap_finish=gap(by_finish, "finish"), gap_finish_plus_next=gap(by_next, "finish_plus_next"),
    )


def candidates_for_session(session: Any, product: int, seq: int, static: ModelStatic) -> CandidatesResult:
    """compute_candidates on the session's current state (platform-state: no random numbers)."""
    return compute_candidates(session.state(), product, seq, static)
