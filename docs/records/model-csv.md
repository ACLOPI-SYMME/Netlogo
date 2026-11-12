# CSV written by the model itself (`Results/Data` and `Results/Events`)

[← Index and glossary](README.md)

## What it is

The NetLogo model, on its own, writes two CSV files at the **end** of a run: one with periodic plant **data** (`Data`) and one with **events** (`Events`). They come from the original model, from before the platform. **The platform does not use them to show anything**: the page, the API and the saved runs are fed by the KPIs, events and decisions the platform reads directly from the model. They are kept to compare with the original model (the regression baseline, `scripts/compare_baseline.py`).

## How it is produced and when it is available

- The model's `ExportData` procedure writes them **only when the run reaches the horizon** (`horizon_ticks`). During the run the model accumulates the rows in memory.
- They are **not written** if the run ends earlier: a finished product set (`all_products_done`), a stopped, failed or deleted run.
- They are available when that run ends.

## How to see it

In the working folder of the worker that ran the session:

```
<ACLOPI_WORK_DIR>/pool_<id>/sessions/session<N>_g<G>/Results/Data/Data_100_Sto_R 3_0.csv
<ACLOPI_WORK_DIR>/pool_<id>/sessions/session<N>_g<G>/Results/Events/Event_100_Sto_R 3_0.csv
```

`100` is the logging interval (`Interval.Logs`), `Sto` the mode (Stochastic), `R 3` the rule (characters 4–6 of the rule's name, with a space) and `0` the BehaviorSpace run number, which with the platform is always 0. By default `ACLOPI_WORK_DIR` is `results/workers/` (in Docker Compose, the machine's `results/` folder).

**Neither has a header.**

## `Events` (9 columns)

| Column | What it is | Unit / values |
|---|---|---|
| 1 | Simulated time of the event | u.t. |
| 2 | Product (`who`) | — |
| 3 | Product type | A, I, P, B, E, L, T |
| 4 | Event | `ProductEntersMachine`, `ProductExitsMachine`, `PassingBy` |
| 5 | Place | `M1`…`M7` or `Node <n>` |
| 6 | Position of the current operation in the product's list (from 0) | On exits: the fixed text **`XXX`** |
| 7 | Current operation | O1…O9. On exits: the fixed text **`YYY`** |
| 8 | Next operation | O1…O9 |
| 9 | Machine it is heading to | M1…M7 |

Real example (from an earlier test run of rule 3):

```
113.77,200,A,ProductEntersMachine,M1,0,O8,O8,M1
213.9,200,A,ProductExitsMachine,M1,XXX,YYY,O1,M2
312.48,200,A,PassingBy,Node 12,1,O1,O1,M2
```

Reading of the second row: at 213.9 u.t. product 200 (type A) left M1; the CSV does not say which operation finished (`XXX`, `YYY`); the next one is O1 and it goes to M2.

**Differences with the platform's events** ([events.md](events.md)): the platform adds the tick, uses field names, and on exits it does say which operation finished.

## `Data` (84 columns)

One row every `Interval.Logs` = 100 u.t. of simulated time. The columns, grouped (the detail is in the model's `PrintData` procedure):

| Columns | Content |
|---|---|
| 1–3 | Simulated time (rounded), rule, mode |
| 4–7 | Live products, live products / 10, machines processing, live products without a machine |
| 8–11 | Mean position (x, y) of the live products and its deviation |
| 12–19 | Total and completed operations of the live products, products waiting, pending operations, total nominal work, real processing time, **waiting time (column 18)**, pending nominal work |
| 20–21 | Machines processing and not processing |
| 22–28 | Live products per type (B, E, L, T, A, I, P) |
| 29–33 | Entropy of the mix of types, fraction of types present, mean progress of the products and related values |
| 34–54 | Per machine M1…M7, three columns: state (`Machine.Busy` / `Machine.Idle`), time it has left (u.t., `NaN` if idle), nearby products heading to it (`NaN` if idle) |
| 55–84 | Products per zone of the plant (one per machine), busy and idle machines and their fraction, and repetitions of earlier indicators (a "KPI" block of the original model) |

## Known problems (not fixed, so as not to change the baseline)

- **Column 18 of `Data` is always 0**: it compares the state with `"waiting"` in lower case and the real one is `"Waiting"` (item 1 of `docs/known-issues.md`).
- **`XXX` / `YYY` on the exits of `Events`**: the CSV does not record the operation that finished (item 3). The platform does record it in its events.
- **Several columns of `Data` are 0 when no product is alive** (only at the end of a run with a set; item 7).

## Pitfalls

- **The folder is per worker, not per session:** the next session that reaches the horizon on the same worker **overwrites** the files. Copy them first if they are needed.
- **No header:** you have to know what each column is (this page or `PrintData`).
- **They do not match what the page shows:** the page uses the platform's KPIs ([kpis.md](kpis.md)), which are computed differently.
