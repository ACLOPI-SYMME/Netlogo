"""Facts for the sequencing prompt, read from the model (docs/sequencing.md).

    read_plant(session) -> dict            with NetLogo: machines and their current Machine.Operations.Time,
                                           capable machines, distances (u.t.), operation sequence of each
                                           type (AgregateOperations), the entry rule and the time step
                                           (parsed from Go / Product.Movement), the stochastic extra and the
                                           travel from creation to M1 (measured with one product)
    load_plant() -> dict                   the same, saved in PLANT_FILE (scripts/a4/export_plant_context.py;
                                           a NetLogo test keeps it equal to the model). The agent service has
                                           no NetLogo and uses this one.
    entry_checks(plant, count) -> [times]  simulated times at which Go evaluates the entry rule
    list_figures(plant, products, strategy, mode) -> dict   precomputed figures of a list (pure)
Times in u.t.; ticks = round(time / tick_time).
"""

from __future__ import annotations

import json
import math
import re
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Any, Sequence

PLANT_FILE = Path(__file__).resolve().parent / "data" / "plant_context.json"

# How each strategy routes an operation to a machine (aclopi.agent.strategies, aclopi.sim.candidates; Paper.nlogo).
ROUTING = {
    "b1b": "each operation goes to the capable machine with the lowest finish_plus_next = estimated end of the "
           "operation there (travel, queue and products on their way included) + travel to the closest machine "
           "of the following operation; ties: lowest machine number. Staying on the same machine costs no travel.",
    "b1": "each operation goes to the capable machine with the lowest estimated end of the operation (travel, queue "
          "and products on their way included); ties: lowest machine number.",
    "rule1": "each operation goes to a random capable machine.",
    "rule2": "each operation goes to the nearest capable machine.",
    "rule3": "each operation goes to the capable machine chosen by potential fields (attraction of free machines).",
}

TYPES_REPORTER = "platform-local [ -> json-any map [t -> (list t AgregateOperations t)] PosibleProducts ]"
STARTS_REPORTER = "platform-local [ -> json-any map [p -> [(list ProductCreationTime ProductRealStart)] of p] sort products ]"


def _procedure(text: str, name: str) -> str:
    m = re.search(rf"^to {re.escape(name)}\b(.*?)^end\b", text, re.S | re.M | re.I)
    if not m:
        raise ValueError(f"procedure {name} not found in the model")
    return m.group(1)


def _number(pattern: str, text: str, what: str) -> list[float]:
    m = re.search(pattern, text)
    if not m:
        raise ValueError(f"{what} not found in the model")
    return [float(g) for g in m.groups()]


def parse_model_rules(text: str) -> dict[str, Any]:
    """Entry rule, time step and stochastic extra, from the source of Paper.nlogo."""
    go = _procedure(text, "Go")
    period, window = _number(r"simulated\.time mod (\d+(?:\.\d+)?) <= (\d+(?:\.\d+)?)", go, "entry window")
    (wip_max,) = _number(r'count products with \[Product\.State != "death"\] < (\d+)', go, "WIP limit")
    x0, x1, y0, y1 = _number(r"count products with \[xcor >= ([\d.]+) and xcor <= ([\d.]+) and ycor >= ([\d.]+) "
                             r"and ycor <= ([\d.]+)\]", go, "entry zone")
    step, decimals = _number(r"set simulated\.time precision \(simulated\.time \+ ([\d.]+)\) (\d+)",
                             _procedure(text, "Product.Movement"), "time step")
    stochastic = re.findall(r'if \(Modeling\.Type = "Stochastic"\) \[(.*)\]', text)
    means = sorted({float(m) for line in stochastic for m in re.findall(r"random-exponential (\d+(?:\.\d+)?)", line)})
    if len(means) != 1:
        raise ValueError(f"expected one random-exponential mean in the processing times, found {means}")
    return {"entry": {"period": period, "window": window, "wip_max": int(wip_max),
                      "zone": {"xcor": [x0, x1], "ycor": [y0, y1]}},
            "time_step": {"step": step, "decimals": int(decimals)},
            "stochastic_extra": {"distribution": "exponential", "mean": means[0],
                                 "without_extra": sum("random-exponential" not in line for line in stochastic)}}


def read_plant(session: Any) -> dict[str, Any]:
    """Facts of the plant from a SimulationSession. Sets the session up (its run is lost): one product,
    Deterministic, rule 3, to measure the travel from creation to the start of O8."""
    from aclopi.sim.candidates import read_model_static

    session.setup(1, 3, modeling_type="Deterministic", product_list=[("A", 80)])
    static = read_model_static(session)
    types = {str(t): [str(o) for o in ops] for t, ops in json.loads(str(session._report(TYPES_REPORTER)))}
    while True:  # until the product starts O8 on M1
        session.step(50)
        rows = json.loads(str(session._report(STARTS_REPORTER)))
        if rows and rows[0][1]:
            created, starts = rows[0]
            break
        if session.ticks > 5000:
            raise RuntimeError("the product never reached M1")
    rules = parse_model_rules(Path(session.model_path).read_text(encoding="utf-8"))
    machines = {m: dict(ops) for m, ops in sorted(static.operation_times.items())}
    load = [m for m, ops in machines.items() if set(ops) == {"O8", "O9"}]
    if len(load) != 1 or rules["stochastic_extra"]["without_extra"] != 1:
        raise ValueError("expected one load / unload machine (O8, O9) without stochastic extra")
    rules["stochastic_extra"] = {"distribution": "exponential", "mean": rules["stochastic_extra"]["mean"],
                                 "machines": [m for m in machines if m != load[0]]}
    rules["entry"]["entry_travel"] = round(float(starts[0]) - float(created), 2)
    return {
        "source": "model/Paper.nlogo",
        "tick_time": static.tick_time,
        **rules,
        "load_unload_machine": load[0],
        "machines": machines,
        "capable": {op: list(ms) for op, ms in sorted(static.capable_machines.items())},
        "distances": {a: {b: (0.0 if a == b else d) for b, d in row.items()} for a, row in sorted(static.distances.items())},
        "types": types,
    }


@lru_cache(maxsize=1)
def _load(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def load_plant(path: Path = PLANT_FILE) -> dict[str, Any]:
    return json.loads(_load(str(path)))


# ----- pure figures -----

def entry_checks(plant: dict[str, Any], count: int) -> list[float]:
    """The first `count` simulated times at which Go evaluates the entry rule: Product.Movement adds the
    step and rounds (precision), then Go checks `simulated.time mod period <= window`. Some windows of
    `period` u.t. get no check because no tick lands in them."""
    step, decimals = Decimal(str(plant["time_step"]["step"])), int(plant["time_step"]["decimals"])
    period, window = float(plant["entry"]["period"]), float(plant["entry"]["window"])
    out: list[float] = []
    k = 0
    while len(out) < count:
        k += 1
        t = float(round(step * k, decimals))
        if math.fmod(t, period) <= window:
            out.append(t)
    return out


def op_time(plant: dict[str, Any], machine: str, operation: str, mode: str) -> float:
    extra = plant["stochastic_extra"]
    return float(plant["machines"][machine][operation]) + (
        float(extra["mean"]) if mode == "Stochastic" and machine in extra["machines"] else 0.0)


def _travel(plant: dict[str, Any], a: str, b: str) -> float:
    return 0.0 if a == b else float(plant["distances"][a][b])


def min_route(plant: dict[str, Any], operations: Sequence[str], mode: str) -> tuple[float, list[str]]:
    """Shortest processing + travel through `operations` (from the start of the first one), choosing a
    capable machine per step; no waits."""
    best: dict[str, tuple[float, list[str]]] = {m: (op_time(plant, m, operations[0], mode), [m])
                                                for m in plant["capable"][operations[0]]}
    for op in operations[1:]:
        best = {m: min(((c + _travel(plant, p, m) + op_time(plant, m, op, mode), r + [m]) for p, (c, r) in best.items()),
                       key=lambda x: (x[0], [int(s[1:]) for s in x[1]]))
                for m in plant["capable"][op]}
    return min(best.values(), key=lambda x: (x[0], [int(s[1:]) for s in x[1]]))


def _type(p: Any) -> str:
    t = p.get("type") if isinstance(p, dict) else (p if isinstance(p, str) else p[0])
    return str(t).strip().upper()


def list_figures(plant: dict[str, Any], products: Sequence[Any], strategy: str = "b1b",
                 mode: str = "Deterministic") -> dict[str, Any]:
    """Figures of a list in the given order (u.t.; *_ticks in ticks)."""
    tick = float(plant["tick_time"])
    types = [_type(p) for p in products]
    m1 = plant["load_unload_machine"]
    per_type: dict[str, Any] = {}
    for t in dict.fromkeys(types):
        ops = plant["types"][t]
        route_time, route = min_route(plant, ops, mode)
        per_type[t] = {
            "count": types.count(t), "sequence": ops,
            "work": round(sum(min(op_time(plant, m, o, mode) for m in plant["capable"][o]) for o in ops), 2),
            "machines_per_step": [plant["capable"][o] for o in ops],
            "min_time": round(plant["entry"]["entry_travel"] + route_time, 2), "best_route": route}
    op_work: dict[str, float] = {}
    for t in types:
        for o in plant["types"][t]:
            op_work[o] = op_work.get(o, 0.0) + min(op_time(plant, m, o, mode) for m in plant["capable"][o])
    machine_work = {m: round(sum(w for o, w in op_work.items() if o in ops), 2) for m, ops in plant["machines"].items()}
    m1_load = sum(op_time(plant, m1, o, mode) for t in types for o in plant["types"][t] if o in plant["machines"][m1])
    checks = entry_checks(plant, len(types))
    entry_travel = float(plant["entry"]["entry_travel"])
    m1_bound = checks[0] + entry_travel + m1_load
    finish = [checks[k] + per_type[t]["min_time"] for k, t in enumerate(types)]
    path_bound = max(finish)
    lb = max(m1_bound, path_bound)
    return {
        "types": per_type,
        "work_per_operation": {o: round(w, 2) for o, w in sorted(op_work.items())},
        "work_per_possible_machine": machine_work,
        "m1_load": round(m1_load, 2),
        "earliest_entries": [round(c, 2) for c in checks],
        "lower_bound": {"m1": round(m1_bound, 2), "path": round(path_bound, 2),
                        "path_product": finish.index(path_bound), "value": round(lb, 2),
                        "ticks": round(lb / tick)},
    }
