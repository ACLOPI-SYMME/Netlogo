# What-if and candidates (L5.4)

These two endpoints let the agent's code (Línea A) evaluate a pending rule-4 decision before taking it. The decision hook is described in `docs/rule4-decision-hook.md`. How to read the responses: `docs/records/candidates-and-whatif.md`.

## Context and deadlines

- **When the agent decides.** While the product is being processed in a machine: the request is created when it **enters** the machine and the answer is used when the operation ends.
- **Live decision deadline.** It is what the product has left on its current machine minus ~2 s of margin: **~8 s from M1** and **~18 s from M2–M7**.
- **Duration of the what-if.** The agent sets it with `budget_ms` in each request (10 s by default, 2 to 15 s), from its decision deadline and the time its LLM calls need:
  - **from M2–M7** (~18 s) a what-if of ~10 s fits;
  - **from M1** (~8 s) the what-if **does not fit** together with the LLM calls, so the agent should not ask for one.
- **Concurrency target.** **5 simultaneous sessions**, with 2 shared what-if workers.
- **Valid sessions.** Only **rule 4** ones. Rule 4 without a decider is exactly rule 3.

## `GET /sessions/{id}/candidates?product=&seq=`

Returns the candidate machines for operation `seq` of product `product`, with their load and their estimated start and finish.

- **Parameters:** both are required. `seq` is the pending operation, `CurrentSequenceOrder + 1`.
- **Computation:** done by `aclopi.sim.candidates.compute_candidates` (Línea A) on `platform-state`, inside the session's worker. It consumes no randomness and does not alter the simulation, and while the session runs it is served between blocks.
- **Invalid request:** answers 200 with `valid: false` and `reason` (`unknown-or-finished-product`, `invalid-seq`, `seq-mismatch` or `not-in-machine`).
- **Schema:** the response is directly the `CandidatesResult` of `aclopi/contracts/candidates.py` (Línea A), with no copy in the API. That way its fields appear in `contracts/openapi.json`. The meaning of each field is in `docs/agent-status.md` ("Fields of `CandidatesResult`").

Main fields: `candidates` (sorted by `finish`), `current_machine`, `own_remaining`, `next_operation`, `best_by_finish`, `best_by_finish_plus_next`, `gap_*`, `travel_source`. Per candidate: `travel` = `distances[current][m]` in u.t., `available` (bool) and the time until the machine is free in `available_in`, `arrival`, `start`, `finish` (absolute u.t.), `proc_time`, `next_machine`, `travel_next`, `is_current_machine`, `queue`, `en_route`, `stay_time` and `stay`.

## `POST /sessions/{id}/what-if`

```json
{"product": 201, "seq": 1, "options": ["M2", "M3"], "max_ticks": 3000, "budget_ms": 10000}
```

- **`options`:** exactly **2 different machines**, chosen by the agent's code. If they are equal, or if they are not exactly two, the API answers 422.
- **`max_ticks`:** tick cap per copy, 1 to 5000 (3000 by default).
- **`budget_ms`:** maximum time of the whole request (the two copies, in series on a single worker), 2000 to 15000 ms (10000 by default). Out of range → 422. When it runs out, the API returns whatever it has with `status: "timeout"`.

### What it does

1. **Already tested?** If this session already had a what-if for the same (`product`, `seq`), it answers `skipped` with `already-used`.
2. **Free worker.** It borrows a what-if worker **without a queue**: if none is free, it answers `skipped` with `no-free-worker` within a few milliseconds.
3. **Snapshot and validation.** The session's worker, between two blocks, validates both options with `platform-check-next-machine`, measures the load of both machines and takes **a single snapshot** (export) of the world. The real session does not stop: live, it keeps running.
4. **Copies, one after the other.** Each copy runs on the borrowed worker: it imports the snapshot, forces the option with `platform-set-next-machine` and advances.
   - The option with the **lowest estimated entry** (with travel; see "Entry estimate") runs first.
   - Inside the copy the agent is never called: the other decisions are taken by the rule-3 code, and the copy's requests never leave the worker.
   - The copy **does not apply scenario events**: the agent must not know the future. (Scenarios are not available on the platform; this only matters in the experiments that use the worker mechanism, `docs/scenarios.md`.)
5. **Stop of each copy:**

   | `stop_reason` | When |
   |---|---|
   | `entered` | The product **enters** the tested machine. The tick, the entry time and the end of the operation (`Next.Completion`) are read; the end is fixed on entry, random part included |
   | `cap` | It reached `max_ticks` without entering |
   | `stalled` | Deadlock: for `ACLOPI_WHATIF_STALL_TICKS` ticks (300) no product changed position **and** no operation started or ended (the total number of elements of `ProductRealStart` and `ProductRealCompletion` of every product did not change). It is checked every `min(150, stall_ticks)` ticks. An operation on M2–M7 lasts ~645 ticks: everybody waiting in a machine or in a queue is not a deadlock |
   | `pruned` | Second copy only: it reached the common window without entering, so it is already worse than the first |
   | `timeout` | `budget_ms` ran out |
   | `horizon` | The run ended |

   If the product did not enter, the entry and the end are **estimated** (`entry_estimated`) on the state of the copy at the stop, with the formula of "Entry estimate", and the copy is flagged.

   The diagnostic JSON of a deadlock includes the request, the machine, the tick, `quiet_ticks` and how many machines were processing.

### Entry estimate (with travel)

The product can enter the tested machine when it has **arrived** and the machine is **free**:

```
arrival = now + what is left of its current operation (if it is in a machine)
              + trip from its machine to the tested one − trip already made (if it already left)
free    = now + what is left of the job in progress on the tested machine
              + processing times of the products in its queue or on their way (+10 on M2–M7 in Stochastic)
entry   = max(arrival, free)        end = entry + time of the operation on that machine
```

**Which estimate is used.** To order the copies (and for `entry-beyond-cap`), the snapshot uses Línea A's `candidates` `start` for each option, because it counts the queue, the products on their way and the occupant that stays. If `candidates` does not give the machine (for example, the product is no longer in a machine), the formula above is used as a fallback. The snapshot's response says which one was used (`estimate_source`: `candidates` or `fallback`). When a copy did not enter, the estimated entry at the stop always comes from the formula above, because at that moment the product is usually travelling.

**Travel.** `distances[origin][destination]` (global `distances`, `Set.distances.Machines`; the row is the origin machine) **is already in u.t.**: it is the minimum trip measured on each route (`data/a0/travel_times.csv`, Línea A).

```
travel (u.t.) = distances[origin][destination]        travel (ticks) = travel / 0.31
```

It used to be divided by the conveyor speed (0.3 per tick) and multiplied by 0.31, which overestimated the trip by 3.3 %. Fixed in `aclopi.sim.candidates.travel_time`.

- **Origin:** the machine the product is in (`product` of the machine in `platform-state`) or, if it already left, the last one of `Machine.Used`. In that case the trip already made comes from `now − last ProductRealCompletion`.
- **What it does not include:** the waits at gates or being blocked behind other products. That is why it can fall short.

   With a deadlock, the snapshot and the request are saved in `results/whatif_diagnostics/` (`ACLOPI_WHATIF_DIAG_DIR`) and the path comes in `diagnostic_file`.

**Why the prediction is exact.** The copy starts from the same snapshot, with the same state of the random generator, and rule 3 decides the same in the copy and in the real session. That is why a real entry (`entered`) predicts exactly what will happen if the agent assigns that machine at that moment. Verified by `tests/test_whatif.py` (test a).

### Common window and metric of the other products

**Window.** It is the tick at which the **first** copy stopped, by entry, cap or deadlock.
- **If the second did not enter before the window:** it is pruned there, because it enters later.
- **If it entered before:** it goes on until the window.

That way both metrics are measured at the same tick, and the pruning matches the window.

**Metric `others`**, over `[snapshot, window]`, for every product except the one being decided:

| Field | Meaning |
|---|---|
| `work` | **Nominal** processing work done in the window: a completed operation adds its `OperationDuration` and the one in progress, the fraction processed (same as the KPI `work_completed`) |
| `wait` | Time in the plant within the window minus the processing time received: travelling or queuing |
| `presence` | Time the other products spent in the plant within the window (`wait` = `presence` − processing received) |
| `finished` | Products finished within the window |

The platform neither combines these quantities nor ranks the options: the agent decides that.

### Definition of the fields

Every value is in **units of simulated time (u.t.)**, except ticks and counts. 1 tick = 0.31 u.t. (`set simulated.time precision (simulated.time + 0.31) 2`, line 1020).

Notation:

| Symbol | Meaning |
|---|---|
| `T0` | `Simulated.Time` of the snapshot, which is the moment of the request |
| `T` | `Simulated.Time` at the stop of the copy, which is the common window for comparing |
| `W` | The product being decided |
| "the others" | Every product of the copy except `W`: also those created within the window and those finishing within it. Those that finished before `T0` add 0 |

**Entry and end of `W`'s operation**

| Field | Definition |
|---|---|
| `entry_tick` | Tick of the `go` in which `W` enters the tested machine, that is, in which `length ProductRealStart` goes from `seq` to `seq + 1` |
| `entry_time` | `item seq ProductRealStart` of `W`, in u.t. |
| `op_end_time` | `Next.Completion` of the tested machine read at that tick. It is fixed on entry and includes the random part `random-exponential 10` on M2–M7 (lines 1310–1317 for M1, without a random term, and 1455–1462 and their copies for M2–M7) |
| Estimated values (`*_estimated: true`) | When `W` does not enter, they come from "Entry estimate" on the state of the copy at the stop |

**Window**

| Field | Definition |
|---|---|
| `window_tick` | The tick at which the **first** copy stopped, the one with the lowest estimated entry, by entry, cap, deadlock or deadline |
| How the second copy runs | It runs until its entry or until `window_tick`, whichever comes first. If it enters before, it goes on until `window_tick`. If it had not entered when reaching the window, it is pruned (`pruned`). Either way, its `others` is measured at `window_tick` |
| Exception | If the second copy runs out of time before the window, `others.window_tick` says where it was measured |

**Metric `others`** (the sums are over the others)

| Field | Formula |
|---|---|
| `work` | `Σ nominal_work(T) − Σ nominal_work(T0)`. `nominal_work` is the one of `work_completed` (`aclopi/sim/kpis.py`): each completed operation adds its `OperationDuration` (200 for O1–O7, 100 for O8–O9; `Set.operations`, line 2633). The one in progress adds `OperationDuration × fraction processed`, where the fraction is `(Simulated.Time − last ProductRealStart) / (Next.Completion − last ProductRealStart)`, clipped to [0, 1]. It uses the **nominal time**, not the real one. An operation falling only partly within the window adds the part of its nominal it advanced in it |
| `presence` | `Σ overlap([max(ProductCreationTime, T0), end], [T0, T])`, with `end` = `last ProductRealCompletion` if it finished (state `death`), or `T` if it is still in the plant. It is **real** time in the plant |
| `wait` | `presence − Σ real_processing`, with `real_processing` = `Σ overlap([ProductRealStart_i, ProductRealCompletion_i or T], [T0, T])`. It is **real** time without processing, that is, travelling or queuing. **It does not use `work`**: since `presence` and `real_processing` are real, `wait` does not carry the random term. The extra time of a long operation due to `random-exponential` counts as processing, not as waiting |
| `finished` | Number of the others with state `death` and `last ProductRealCompletion > T0`, that is, that finished within the window |

**Example.** With `T0` = 300 and `T` = 500 u.t. there are two other products:

| Product | What happens in the window | `presence` | `real_processing` | `work` |
|---|---|---|---|---|
| A | In the plant since before. Processes O1 between 350 and 560 (real 210: nominal 200 + 10 random) | 200 | 150 | `200 × (150 / 210) ≈ 142.9` |
| B | Created at 420 and travels | 80 | 0 | 0 |

Totals: `presence` = 280, `wait` = 280 − 150 = 130, `work` ≈ 142.9 and `finished` = 0.

### Response (always 200, except validation)

```jsonc
{"status": "ok",                     // ok | timeout | skipped | error
 "skipped_reason": null,             // no-free-worker | already-used | entry-beyond-cap
 "snapshot_tick": 1012, "snapshot_time": 313.72, "operation": "O1",
 "window_tick": 1987, "run_order": ["M3", "M2"],
 "timings_ms": {"export": 98, "import": 1010, "advance": 1630, "total": 2850},
 "would_skip_entry_beyond_cap": false, "loads": {"M2": 1, "M3": 0}, "estimated_entry_ticks": {"M2": 995, "M3": 694},
 "options": [                        // in the order of the request
   {"machine": "M2", "entered": true, "stop_reason": "entered",
    "entry_tick": 1987, "entry_time": 615.97, "entry_estimated": false,
    "op_end_time": 829.1, "op_end_estimated": false,
    "others": {"window_tick": 1987, "work": 431.2, "wait": 38.4, "presence": 612.3, "finished": 0},
    "ticks_simulated": 975, "stop_tick": 1987, "cap_reached": false, "stalled": false,
    "pruned": false, "timed_out": false, "skipped": false,
    "duration_ms": 1350, "import_ms": 505, "advance_ms": 845, "diagnostic_file": null, "error": null},
   {"machine": "M3", ...}]}
```

- **`skipped`:** it is a normal response; `options` comes empty.
- **`timeout`:** it carries whatever was reached. An option that did not get to run comes with `skipped: true`.

### Validation errors

| HTTP | `code` | When |
|---|---|---|
| 422 | `invalid_option` | Product that does not exist, unknown machine or one not capable of the operation, `seq` out of range. `detail` gives the reason for each option |
| 409 | `decision_not_pending` | Product finished (`product-finished`), outside a machine (`not-in-machine`) or `seq` that is not the pending one (`seq-mismatch`, `stale-seq`) |
| 409 | `rule4_required` | The session is not rule 4 |
| 422 | – | Invalid format (not 2 options, equal options, `max_ticks` or `budget_ms` out of range) |

### Entry beyond the cap: `entry-beyond-cap` (TO BE CONFIRMED, only recorded)

- **Criterion:** the estimated entry **with travel** (see "Entry estimate") of **both** options falls beyond `max_ticks`. In that case no copy would get to see the entry and the what-if would only return estimates.
- **Current behaviour:** the what-if is **not** skipped. `would_skip_entry_beyond_cap: true` is recorded in the response and in the metrics. To skip it (`skipped` with `entry-beyond-cap`), set `ACLOPI_WHATIF_SKIP_BEYOND_CAP=1` (off by default).
- **Data in the response:** `estimated_entry_ticks` (per option, from the snapshot) and `loads`.
- The quality of the estimate and how often the criterion holds are measured with `scripts/l5/whatif_estimation.py`.

## `GET /sessions/{id}/metrics`

`{"whatif": {...}}`, for section 3.4 of the plan:

| Group | Fields |
|---|---|
| Requests | `requests`, `ok`, `timeout`, `error`, `invalid` |
| Skipped | `skipped` by reason (`no-free-worker`, `already-used`, `entry-beyond-cap`), `would_skip_entry_beyond_cap` |
| Options | `options_run`, `entered`, `cap_reached`, `stalled`, `pruned`, `options_timed_out` |
| Times (mean, p95, max, n) | `duration_ms`, `export_ms`, `import_ms`, `advance_ms` |
| Ticks (mean, p95, max, n) | `ticks_to_entry`, `ticks_simulated` |

## Configuration

| Variable | Default | |
|---|---|---|
| `ACLOPI_WHATIF_STALL_TICKS` | 300 | Ticks without movement or processing to declare a deadlock |
| `ACLOPI_WHATIF_CHUNK_TICKS` | 150 | Ticks between control reads of the copy |
| `ACLOPI_WHATIF_SKIP_BEYOND_CAP` | 0 | 1 = skip the what-if when the estimated entry of both options exceeds `max_ticks` |
| `ACLOPI_WHATIF_DIAG_DIR` | `results/whatif_diagnostics` | Snapshots of the deadlocks |

## Design planned for L5.5 (now implemented, see `docs/agent-api.md`)

- **Heartbeats in fast mode.** While a decision is awaited, the worker sends heartbeats so that the 15 s watchdog does not kill it.
- **Agent not answering in fast mode.** If ~90 s go by without an answer, the run is marked as **failed**: it does not continue with rule 3. If a user launched it from `/ui`, they see "Agent not available".
- **Agent not answering live.** The model applies rule 3 on its own and the platform shows the % of `rule3-fallback`.
