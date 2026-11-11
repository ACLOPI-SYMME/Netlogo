# The session and the plant snapshot

[← Index and glossary](README.md)

Three sources about the session **in progress**: its card (`GET /sessions/{id}`), the plant snapshot at this tick (`/state`) and the fixed plant geometry (`/layout`). None of them is stored: they exist while the session exists.

## Session card (`SessionInfo`)

### What it is, when and how to see it

The session's parameters and the state of its run. `POST /sessions` returns it when the session is created, `GET /sessions/{id}` at any time and `GET /sessions` (all of them, also those closed recently); it also travels inside the WebSocket `snapshot`. The page shows parts of it: the id, the seed used and the state.

### Fields

| Field | Meaning | Unit | Values |
|---|---|---|---|
| `session_id` | Identifier | — | 32 hexadecimal characters |
| `status` | Whether the session is still alive | — | `active`, `lost` (its worker crashed), `expired` (closed for inactivity) |
| `lost_reason` | If `lost` or `expired`, why | text | — |
| `parameters` | `seed`, `rule`, `modeling_type`, `horizon_ticks` | — | see [runs.md](runs.md) |
| `seed_source` | `user` or `random` | — | — |
| `strategy` | Rule 4: `agent`, `b1`, `b1b`, `none` | — | `null` with rules 1–3 |
| `ticks` | Last known tick | ticks | — |
| `finished` | Whether the run finished | — | — |
| `run_state` | State of the run | — | `idle`, `running_live`, `running_fast`, `waiting_decision`, `paused`, `finished`, `failed` |
| `run_reason` | Why it ended or failed | — | `horizon`, `all_products_done`, `agent_unavailable`, `null` |
| `mode`, `speed` | Mode and speed of the current or paused run | — | `null` when not running |
| `pending_decisions` | Fast mode: decisions the run is waiting for | count | — |
| `warnings` | Warnings when the session was created | — | for example `agent_unavailable` (the agent does not answer; live runs will use rule 3) |
| `product_set_id`, `products_total`, `products_hash` | Product set used, its length and its fingerprint | — | `null` without a set ("Random") |
| `products` | The session's own copy of the list, in entry order. "Optimize order" → apply changes it (and `products_hash`); the saved set does not change | — | `null` without a set |
| `optimize_status` | Status of the session's last "Optimize order" | — | `running`, `waiting_ai`, `waiting_turn`, `done`, `cancelled`, `failed`, or `null` |
| `optimization` | The order applied by "Optimize order", with its estimate ([optimize-order.md](optimize-order.md)) | — | `null` if none was applied |
| `scenario`, `scenario_summary` | Always S0 and `{applied: 0, skipped: 0}` ([scenarios.md](scenarios.md)) | — | — |
| `last_run_id` | Last saved run of this session | — | — |
| `watchers` | Clients connected through the WebSocket | count | — |
| `worker_slot` | Number of the worker serving it | — | — |
| `created_at`, `last_activity` | Creation and last request | Unix time (s) | — |

### Real example (at the end of the fast run)

```json
{"session_id": "34cf16b45b8745feaedba86430dcc617", "status": "active",
 "parameters": {"seed": 42, "rule": 4, "modeling_type": "Stochastic", "horizon_ticks": 20000},
 "ticks": 10635, "finished": true, "run_state": "finished", "run_reason": "all_products_done",
 "strategy": "agent", "pending_decisions": 0, "warnings": [], "seed_source": "user",
 "product_set_id": "251c64c8e403434daedf9577668305f5", "products_total": 5, "products_hash": "56fbcd4c…",
 "last_run_id": "acfcb7cbb35a43119f472d1fe812f81f", "mode": null, "speed": null, "watchers": 1,
 "worker_slot": 0, "created_at": 1794220312.47, "last_activity": 1794220368.22, "…": "…"}
```

Reading: the session is still alive (`active`) although the run finished (`finished`); its run was saved as `last_run_id`; one client was watching.

### Pitfalls

- **`status` belongs to the session; `run_state` belongs to the run.** An `active` session can have a `finished` run.
- **A session closes by itself** after 30 min without requests (`ACLOPI_SESSION_IDLE_TIMEOUT_S`): it becomes `expired` and its run, if half-way, is saved as `stopped`.

## Plant snapshot (`GET /sessions/{id}/state`)

### What it is, when and how to see it

Where each product is and what each machine is doing at the current tick. It is what the page draws. Requested with `GET /sessions/{id}/state` at any time (during a run, between two blocks) and it travels as `state` in the WebSocket messages. Reading it does not alter the simulation.

### Main fields

| Field | Meaning | Values |
|---|---|---|
| `tick`, `time` | Moment of the snapshot | ticks, u.t. |
| `finished` | Finished products | count |
| `terminado` | Whether the model already ran its closing step (writing its CSV files). The name comes from the model | `"No"`, `"Si"` |
| `products_created` | Products created | count |
| `fixed_product_sequence`, `product_sequence_seed` | Whether products come from a fixed sequence drawn from the seed, and from which seed | — |
| `product_list_active`, `product_list_length`, `product_list_next` | With a set: whether it is active, its length and the position of the next product to enter (from 1) | — |
| `segments` | Products per rail section (W1, W2…) | count |
| `gates` | State of the gates: `node`, `kind` (`merge`, …), `active` | — |
| `machines[]` | Per machine: `id`, `name`, `state` (`Machine.Processing` or `Idle`), `operation` and `product` in progress, `remaining` (u.t. left), `next_completion` (finish time, u.t.; 100000000 if idle), `queue` (products queued), `attractiveness` (internal value of rule 3) | — |
| `products[]` | Per live product: `id`, `type`, `state` (`Waiting`, `Movement`, `Processing.Product`, …), `x`, `y`, `last_node`, `next_node`, `next_operation`, `heading_workstation` (machine it is going to), `sequence_order` (current operation, from 0), `operations` (full list), `created` (u.t.), `ai_next_machine` and `ai_decision_seq` (the agent's last decision and for which operation), `decision_source` (`agent`, `rule3-fallback`, `single-option` or empty) | — |

Real example (live run, tick 642, excerpt):

```json
{"tick": 642, "time": 199.02, "terminado": "No", "finished": 0, "products_created": 1,
 "machines": [{"id": 186, "name": "M1", "state": "Machine.Processing", "operation": "O8", "product": 200,
               "remaining": 14.75, "next_completion": 213.77, "queue": [], "attractiveness": 63492.06},
              {"id": 187, "name": "M2", "state": "Idle", "operation": null, "product": null,
               "remaining": null, "next_completion": 100000000, "queue": [], "attractiveness": 1000000}],
 "products": [{"id": 200, "type": "T", "state": "Waiting", "x": 115, "y": 106, "next_operation": "O8",
               "heading_workstation": "M1", "sequence_order": 0, "operations": ["O8", "O1", "O1", "O2", "O4", "O9"],
               "created": 100.13, "ai_next_machine": "M2", "ai_decision_seq": 1, "decision_source": ""}]}
```

Reading: product 200 (type T) is on M1 doing O8 and has 14.75 u.t. left; the agent has already decided that its operation 1 (O1) will be on M2 (`ai_next_machine`, `ai_decision_seq`).

**Pitfalls:** a product being processed can show `state: "Waiting"` (as in the example); to know whether it is in a machine, look at `machines[].product`. `next_completion: 100000000` means "idle", not a real time.

## Plant geometry (`GET /sessions/{id}/layout`)

Fixed: it does not change during the session. It travels in the `snapshot`. Used to draw the plant.

| Field | What it is |
|---|---|
| `nodes` | The rail nodes: `id`, `x`, `y` (94 in the model) |
| `conveyors` | The sections between nodes: `from`, `to`, `shape`, `default_position`, `active` |
| `curves` | The curves: `turn`, `radius` |
| `machines` | The 7 machines: `id`, `name`, `x`, `y` |
| `sensors` | The sensors: `id`, `sensor_id`, `x`, `y` |
| `switches` | The nodes where the rail splits (`diverge`) or joins (`merge`) |
