"""KPIs of a Paper.nlogo run, computed from the model state through pynetlogo.

Definitions (agreed for the headless validation):
- finished: products with Product.State = "death"; wip: all other products.
- throughput: finished / Simulated.Time.
- mean_flow_time: mean of (last ProductRealCompletion - first ProductRealStart) over finished
  products (time from the first operation start, not from creation).
- utilization per machine: busy time / Simulated.Time. Busy time pairs ProductRealStart[i],
  ProductRealCompletion[i] and Machine.Used[i]; an operation still in progress counts until
  Simulated.Time on the product's Heading.Workstation.

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

# One evaluation, in this order, inside with-local-randomness. Encoded as JSON because
# pynetlogo cannot convert lists that mix numbers and strings.
KPI_REPORTER = (
    "platform-local [ -> json-any (list "
    f"({FLOW_TIME_REPORTER}) ({MACHINE_NAMES_REPORTER}) ({BUSY_TIME_REPORTER})"
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

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def compute_kpis(netlogo: Any) -> Kpis:
    """Compute the KPIs of the current state of a pynetlogo NetLogoLink with Paper.nlogo loaded."""
    ticks = int(netlogo.report("ticks"))
    simulated_time = float(netlogo.report("Simulated.Time"))
    finished = int(netlogo.report('count products with [Product.State = "death"]'))
    wip = int(netlogo.report('count products with [Product.State != "death"]'))
    flow, machine_names, busy = json.loads(str(netlogo.report(KPI_REPORTER)))

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
    )
