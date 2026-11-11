# Optimize order

[← Index and glossary](README.md)

## What it is

The result of the **"Optimize order"** button: several entry orders of the session's product list, each simulated in full, with its estimated makespan and its saving against the user's order. The user can apply one before running. How it works: `docs/optimize-order.md`.

## How it is produced and when it is available

- **Start.** It is produced on request: `POST /sessions/{id}/optimize-order`, or the button on the Visualization tab. Only with a session that has a list, idle at tick 0.
- **Lifetime.** Available **while the session exists**, from the moment it starts:
  - each order appears in it as soon as its simulation ends;
  - the session keeps only its **last** optimization;
  - it is not stored in DynamoDB.
- **When an order is applied**, a short summary (`optimization`) stays in the session and goes into every run saved afterwards ([runs.md](runs.md)).

## How to see it

| Where | What it shows |
|---|---|
| `GET /sessions/{id}/optimize-order` | The whole record (below) |
| WebSocket `optimize_progress`, `optimize_best`, `optimize_result`, `optimize_failed` | Progress and results as they happen ([websocket.md](websocket.md)) |
| Page, **Visualization** tab, panel "§1b Optimize order" | Progress, "Best order found so far", the table of orders, the reason of the winner and the notice |
| `GET /sessions/{id}` → `optimize_status`, `optimization` | The outcome and the applied order ([sessions-and-state.md](sessions-and-state.md)) |
| `GET /runs/{id}` → `optimization` | The estimate next to the real run ([runs.md](runs.md)) |

## Fields

| Field | Meaning | Unit | Values |
|---|---|---|---|
| `optimization_id` | Identifier | — | 32 hexadecimal characters |
| `status` | State | — | `running`, `waiting_ai`, `waiting_turn`, `done`, `cancelled`, `failed` |
| `mode`, `reasoning_effort` | Mode asked for, and the reasoning sent to the AI | — | `quick` / `none`; `full` / `medium` |
| `round`, `rounds` | Round in progress (or the last one), and rounds with the AI planned | — | 0 = original and heuristic |
| `progress_pct` | Progress | % | 0–100 (100 at the end) |
| `current` | Simulation in progress: `label`, `ticks`, `done` (products finished), `total` | — | `null` when not simulating |
| `ai_elapsed_s` | Seconds the AI has been thinking | s | only in `waiting_ai` |
| `waited_s` | Seconds waited for a turn at the AI (429), in total | s | — |
| `strategy`, `simulation_mode`, `seed`, `max_ticks` | How every order was simulated | — | e.g. `b1b`, `Deterministic`, the session's seed, the session's horizon |
| `products` | The session's list **at the start**. Every `order` indexes it | — | see [product-sets.md](product-sets.md) |
| `evaluated[]` | The orders simulated (table below) | — | in the order they were simulated |
| `discarded[]` | Orders not simulated: `label`, `origin`, `round`, `order`, `reason` (`invalid`: not a complete order; `same_as`: equal to the order named in `same_as`), `reasoning` | — | — |
| `rounds_info[]` | Per AI round: `round`, `analysis` (the AI's reading of the best order so far), `latency_ms`, `error` | — | — |
| `best` | `index` of the order with the lowest makespan | — | `null` if none finished |
| `warning` | Why the rounds ended early without an error | — | e.g. "the AI is not available; only the original and the heuristic were compared" |
| `error` | Why it failed | — | e.g. "optimization busy: the AI had no free turn in time" |
| `applied` | `index` of the order applied | — | `null` if none |
| `stopped_early` | An order was applied before the rounds ended | — | `true` / `false` |
| `started_at`, `finished_at` | Start and end | Unix time (s) | — |

Each element of `evaluated`:

| Field | Meaning | Unit |
|---|---|---|
| `index` | Position in `evaluated` (what `apply-order` takes) | — |
| `origin`, `label`, `round` | `original` ("Original", round 0), `heuristic` ("Heuristic", round 0) or `ai` ("AI round k · 1" or "· 2") | — |
| `order` | Permutation of the positions of `products` (0-based): `order[0]` is the product that enters first | — |
| `types` | The types in that order, e.g. `ABAEI` | — |
| `makespan_ticks`, `makespan_time` | When the last product finishes, from `simulate_list`. `null` if the list did not finish by `max_ticks` (`all_done: false`) | ticks; u.t. |
| `saving_time`, `saving_pct` | Saving against the original: original − this. **Negative = worse** | u.t.; % |
| `reasoning` | Why this order: the AI's, or "Longest first" for the heuristic | — |
| `analysis` | The AI's analysis of the round that proposed it | — |
| `wall_s` | Real time the simulation took | s |

## Real example

Session with rule 4 (agent), seed 42, horizon 20,000 and 5 products (types I, A, E, B, A). Mode `quick`, with the mock agent (`aclopi.agent_mock`, 4 s per answer). It took 61 s. Excerpt of `GET /sessions/{id}/optimize-order` at the end:

```json
{"optimization_id": "d0b7acc159ef49d2b9ea7ee07d4053db", "status": "done", "mode": "quick", "reasoning_effort": "none",
 "round": 1, "rounds": 1, "progress_pct": 100.0, "strategy": "b1b", "simulation_mode": "Deterministic",
 "seed": 42, "max_ticks": 20000, "best": 0, "warning": null, "applied": null, "stopped_early": false,
 "evaluated": [
  {"index": 0, "origin": "original", "label": "Original", "order": [0, 1, 2, 3, 4], "types": "IAEBA",
   "makespan_ticks": 10005, "makespan_time": 3101.55, "saving_time": 0.0, "saving_pct": 0.0, "wall_s": 18.98},
  {"index": 1, "origin": "heuristic", "label": "Heuristic", "order": [1, 3, 4, 2, 0], "types": "ABAEI",
   "makespan_ticks": 10366, "makespan_time": 3213.46, "saving_time": -111.91, "saving_pct": -3.6,
   "reasoning": "Longest first", "wall_s": 14.09},
  {"index": 2, "origin": "ai", "label": "AI round 1 · 1", "order": [4, 3, 2, 1, 0], "types": "ABEAI",
   "makespan_ticks": 11660, "makespan_time": 3614.6, "saving_time": -513.05, "saving_pct": -16.5,
   "reasoning": "mock: variation 1 of the best order so far", "wall_s": 11.38},
  "…1 more"],
 "discarded": [],
 "rounds_info": [{"round": 1, "analysis": "mock analysis (reasoning none): best so far 10005 ticks",
                  "latency_ms": 4020.6, "error": null}]}
```

**Reading:**
- `best: 0`: the user's own order (Original) finished first, at tick 10,005 (3,101.55 u.t.). Nothing beat it, so there is nothing to save. The page says "Your order was already the fastest of the orders tested".
- The heuristic (`ABAEI`) is 111.91 u.t. **slower** (`saving_pct: -3.6`).
- The two orders of the AI are 16.5 % slower. The mock agent only varies the best order; the real AI reads the `details` of each simulation (docs/sequencing.md).
- `wall_s`: the first simulation of a worker is slower (19 s); the next ones took 11–14 s.

After applying the best order (`apply-order {"candidate": 0}`) and running fast, the session and the saved run carry:

```json
"optimization": {"optimized": true, "mode": "quick", "order": [0, 1, 2, 3, 4], "origin": "original", "label": "Original",
                 "round": 0, "estimated_makespan_ticks": 10005, "estimated_makespan_time": 3101.55,
                 "estimated_saving_time": 0.0, "estimated_saving_pct": 0.0, "estimate_strategy": "b1b",
                 "estimate_mode": "Deterministic", "optimization_id": "d0b7acc159ef49d2b9ea7ee07d4053db"}
```

The real run had `kpis.makespan_ticks: 10276` (3,185.56 u.t.): 2.7 % above the estimate, because the run was stochastic and was decided by the agent, not by b1b.

## Useful calculations

- **Saving of an order, in u.t.:** `evaluated[0].makespan_time − makespan_time`. The page shows it as "−X u.t. (−Y %)" when it is faster.
- **Estimate against reality** (in a saved run): `kpis.makespan_ticks − optimization.estimated_makespan_ticks`.
- **Products in the order of an option:** `[products[i] for i in order]`.

## Pitfalls

- **`order` indexes the list as it was at the start.** After applying, the session's list is the reordered one. A new optimization takes the new list as its "Original".
- **The estimate is not the real run.** It uses mode Deterministic, one seed and, with rule 4, the b1b rule in place of the agent. The real saving may vary (the page says so under the results).
- **Not done by the horizon.** With a short horizon, `all_done: false` and `makespan_*: null`. There is no saving and no best order. Raise the horizon.
- **The saving can be negative**: the order is worse than the original.
- **`optimization` in a run is only there if an order was applied** before that run. Optimizing without applying leaves `null`.
- **It lives in memory:** the evaluated orders are lost when the session is closed or the API restarts. Only the applied summary is saved, in the runs.
