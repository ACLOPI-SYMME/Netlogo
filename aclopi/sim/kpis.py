"""KPIs of a Paper.nlogo run, computed from the model state through pynetlogo.

Definitions (agreed for the headless validation):
- finished: products with Product.State = "death"; wip: all other products.
- throughput: finished / Simulated.Time.
- mean_flow_time: mean of (last ProductRealCompletion - first ProductRealStart) over finished
  products (time from the first operation start, not from creation).
- utilization per machine: busy time / Simulated.Time. Busy time pairs ProductRealStart[i],
  ProductRealCompletion[i] and Machine.Used[i]; an operation still in progress counts until
  Simulated.Time on the product's Heading.Workstation.
- created: products created so far (finished + wip).
- work_completed: processing work done, in time units of NOMINAL processing time
  (OperationDuration: 200 for O1-O7, 100 for O8 and O9). Each completed operation adds its nominal
  time; an operation in progress adds the processed fraction of it,
  (Simulated.Time - start) / (Next.Completion - start) x nominal, clipped to [0, 1]. The nominal
  time is used instead of the drawn one so that the random part of processing times neither
  rewards nor penalizes a strategy.
- product list (docs/product-sets.md): products_total (length of the list, None without a list),
  all_done (every product of the list created and finished), makespan_time (last
  ProductRealCompletion of the finished products, from the start of the run; None unless all_done)
  and makespan_ticks (makespan_time / 0.31, rounded).

The reporters iterate agentsets with `of`, which shuffles agents with the model's RNG. They are
evaluated in a single platform-local call, so the RNG is restored afterwards (KPIs can be read
mid-run without altering the simulation) and the agent order, hence every floating-point sum,
is exactly the one of an unwrapped evaluation.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Any

FLOW_TIME_REPORTER = """
ifelse-value any? products with [Product.State = "death"]
  [mean [last ProductRealCompletion - first ProductRealStart] of products with [Product.State = "death"]]
  [-1]
"""

MACHINE_NAMES_REPORTER = "sort [Machine.Name] of machines"

BUSY_TIME_REPORTER = """
map [m -> sum [
    sum (map [[s c u] -> ifelse-value (u = m) [c - s] [0]]
             (sublist ProductRealStart 0 (length ProductRealCompletion))
             ProductRealCompletion
             Machine.Used)
    + ifelse-value (length ProductRealStart > length ProductRealCompletion and Heading.Workstation = m)
        [Simulated.Time - last ProductRealStart] [0]
  ] of products]
  (sort [Machine.Name] of machines)
"""

# Nominal time of the operation at index #i of a product's ProductOperations ("O1".."O9").
_NOMINAL = "item ((read-from-string (last item {i} ProductOperations)) - 1) OperationDuration"

# Iterates products with `sort` (no random numbers). The machine of an operation in progress is
# the product's Heading.Workstation (it changes only when the operation completes).
WORK_COMPLETED_REPORTER = f"""
sum map [p -> [
    sum map [i -> {_NOMINAL.format(i="i")}] (range length ProductRealCompletion)
    + ifelse-value (length ProductRealStart > length ProductRealCompletion) [
        {_NOMINAL.format(i="(length ProductRealCompletion)")}
        * max (list 0 min (list 1
            ((Simulated.Time - last ProductRealStart)
             / ([Next.Completion] of first sort machines with [Machine.Name = [Heading.Workstation] of myself] - last ProductRealStart))))
      ] [0]
  ] of p] sort products
"""

# Product-list KPIs, in their own platform-local call (no random numbers).
LIST_REPORTER = (
    "platform-local [ -> json-any (list (ifelse-value product-list? [1] [0]) (length product-list) products-created "
    '(count products with [Product.State != "death"]) '
    '(ifelse-value any? products with [Product.State = "death"] '
    '[max [last ProductRealCompletion] of products with [Product.State = "death"]] [-1])) ]'
)
TICK_TIME = 0.31

# One evaluation, in this order, inside with-local-randomness. Encoded as JSON because
# pynetlogo cannot convert lists that mix numbers and strings. The work reporter goes last and
# uses no random numbers, so the first three values are exactly as before it was added.
KPI_REPORTER = (
    "platform-local [ -> json-any (list "
    f"({FLOW_TIME_REPORTER}) ({MACHINE_NAMES_REPORTER}) ({BUSY_TIME_REPORTER}) ({WORK_COMPLETED_REPORTER})"
    ") ]"
)


@dataclass(frozen=True)
class Kpis:
    ticks: int
    simulated_time: float
    finished: int
    wip: int
    throughput: float
    mean_flow_time: float | None
    utilization: dict[str, float]
    created: int
    work_completed: float  # time units of nominal processing time (see module docstring)
    products_total: int | None = None  # product list only
    all_done: bool = False
    makespan_ticks: int | None = None
    makespan_time: float | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def compute_kpis(netlogo: Any) -> Kpis:
    """Compute the KPIs of the current state of a pynetlogo NetLogoLink with Paper.nlogo loaded."""
    ticks = int(netlogo.report("ticks"))
    simulated_time = float(netlogo.report("Simulated.Time"))
    finished = int(netlogo.report('count products with [Product.State = "death"]'))
    wip = int(netlogo.report('count products with [Product.State != "death"]'))
    flow, machine_names, busy, work = json.loads(str(netlogo.report(KPI_REPORTER)))

    if simulated_time > 0:
        throughput = finished / simulated_time
        utilization = {str(m): float(b) / simulated_time for m, b in zip(machine_names, busy)}
    else:
        throughput = 0.0
        utilization = {str(m): 0.0 for m in machine_names}

    return Kpis(
        ticks=ticks,
        simulated_time=simulated_time,
        finished=finished,
        wip=wip,
        throughput=throughput,
        mean_flow_time=None if flow < 0 else float(flow),
        utilization=utilization,
        created=finished + wip,
        work_completed=float(work),
        **list_kpis(netlogo),
    )


def list_kpis(netlogo: Any) -> dict[str, Any]:
    """products_total, all_done and makespan of a run with a product list (docs/product-sets.md)."""
    active, length, created, alive, last_completion = json.loads(str(netlogo.report(LIST_REPORTER)))
    if not active:
        return {}
    all_done = created >= length and alive == 0
    makespan = float(last_completion) if all_done and last_completion >= 0 else None
    return {"products_total": int(length), "all_done": bool(all_done), "makespan_time": makespan,
            "makespan_ticks": int(round(makespan / TICK_TIME)) if makespan is not None else None}
