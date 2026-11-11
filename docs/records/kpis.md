# KPIs (plant indicators)

[← Index and glossary](README.md)

## What it is

The indicators of how the plant is doing: how many products finished, how long they took, how much each machine worked and, with a product set, how long it took to finish the whole set (*makespan*). They are computed by reading the model **without altering it**: reading them does not change the simulation.

## How it is produced and when it is available

- **Always**, for the session's current tick: `GET /sessions/{id}/kpis` computes them on the spot, also during a run (the worker serves the request between two blocks).
- **During a run**, about once per second, inside the WebSocket `tick` and `progress` messages, and always in the last block and in `finished`.
- **When the run ends**, the saved run keeps the last ones: field `kpis` (without `simulated_time`) plus `utilization` separately ([runs.md](runs.md)).

## How to see it

- `GET /sessions/{id}/kpis`.
- Page, Visualization tab, **Indicators** panel; and in the History Logs tab, columns Ticks, Makespan, Mean flow, Work, Finished and Created, and the comparison.

## Fields

| Field | What it measures | Unit | Values |
|---|---|---|---|
| `ticks` | Tick at which they were computed | ticks | — |
| `simulated_time` | Simulated time at that tick (`ticks × 0.31`) | u.t. | — |
| `created` | Products that have entered the plant so far (`finished + wip`) | count | — |
| `finished` | Finished products | count | — |
| `wip` | Products in the plant, not finished | count | — |
| `throughput` | Finished products per unit of time: `finished / simulated_time` | products per u.t. | 0 at the start |
| `mean_flow_time` | Mean time of a finished product, **from the start of its first operation** (not from when it entered the plant) until the end of the last one | u.t. | `null` if none finished |
| `utilization` | Per machine: fraction of the time it was processing. An operation in progress counts up to the moment of the computation | 0 to 1 | `{"M1": …, …, "M7": …}` |
| `work_completed` | Work done, measured in **nominal time** of the operations: 200 u.t. for each completed O1–O7 and 100 for each O8–O9; an operation in progress adds the fraction done. It uses the nominal time, not the real one, so that the randomness of processing times neither rewards nor penalises a rule | u.t. of nominal work | — |
| `products_total` | With a set: how many products it has | count | `null` without a set |
| `all_done` | With a set: whether every product entered and finished | — | `true`, `false` (always `false` without a set) |
| `makespan_time` | With a set and `all_done`: when the last product finished, from the start | u.t. | `null` otherwise |
| `makespan_ticks` | The same in ticks: `makespan_time / 0.31`, rounded | ticks | `null` otherwise |

## Real example

At the end of the fast run with 5 products (`GET /sessions/{id}/kpis`):

```json
{"ticks": 10635, "simulated_time": 3296.85, "finished": 5, "wip": 0, "created": 5,
 "throughput": 0.0015165991780032456, "mean_flow_time": 2005.824,
 "utilization": {"M1": 0.304, "M2": 0.324, "M3": 0.446, "M4": 0.376, "M5": 0.643, "M6": 0.196, "M7": 0.0},
 "work_completed": 7200.0, "products_total": 5, "all_done": true,
 "makespan_ticks": 10018, "makespan_time": 3105.58}
```

And after 20 s of the live run (no set):

```json
{"ticks": 642, "simulated_time": 199.02, "finished": 0, "wip": 1, "created": 1, "throughput": 0.0,
 "mean_flow_time": null, "utilization": {"M1": 0.428, "M2": 0.0, "…": "…"}, "work_completed": 85.25,
 "products_total": null, "all_done": false, "makespan_ticks": null, "makespan_time": null}
```

**Line-by-line reading of the first one:**
- `ticks: 10635`, `simulated_time: 3296.85`: 10,635 × 0.31 = 3,296.85 u.t.
- `created: 5`, `finished: 5`, `wip: 0`: the 5 products of the set entered and finished.
- `throughput: 0.0015`: 5 / 3,296.85. It means one product every ~659 u.t.
- `mean_flow_time: 2005.8`: on average, a product took ~2,006 u.t. (~6,470 ticks) between its first operation and its last.
- `utilization.M5: 0.643`: M5 processed 64 % of the time; `M7: 0.0`: never used.
- `work_completed: 7200`: the 5 products did nominal work worth 7,200 u.t. (for example, a product with O8, four O1–O7 operations and O9 adds 100 + 4 × 200 + 100 = 1,000).
- `all_done: true`, `makespan_ticks: 10018`: the last product finished at tick 10,018. The run went on until 10,635 because it ends at the `go` in which the last product **leaves** the plant, a little after its last operation.

## Useful calculations

- **Mean time per product in ticks** = `mean_flow_time / 0.31`.
- **Busiest machine** = the one with the highest `utilization`.
- **Work rate** = `work_completed / simulated_time` (u.t. of nominal work per simulated u.t.; how many machines worked on average, counting work at nominal time).
- **Comparing rules with a set:** `makespan_ticks` (lower is better) and, if it did not finish (`all_done: false`), `finished` and `work_completed`.

## Pitfalls

- **`mean_flow_time` does not count the wait before the first operation** (the trip from the entrance to M1). It is not "time in the plant".
- **`makespan_*` is `null` until the whole set is finished.** The runs table shows "not finished".
- **`makespan_ticks` can be lower than the run's `ticks`**: the makespan is the last operation, and the run ends when the product leaves.
- **`throughput` is per u.t., not per tick nor per real second.** Per tick: multiply by 0.31.
- **With the normal product arrival (no set) few products enter** in 10,000 ticks (see item 2 of `docs/known-issues.md`). Low `throughput` values are normal.
- **In a run stopped half-way**, the saved `kpis` can be a few ticks old ([runs.md](runs.md#pitfalls)).
