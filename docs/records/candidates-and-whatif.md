# Candidates and what-if responses

[← Index and glossary](README.md)

Both are tools the agent uses to decide. They can be queried by hand to understand a decision. The design is in `docs/whatif.md` and `docs/agent-api.md`; this page explains how to read the responses. Both require `Authorization: Bearer <ACLOPI_AGENT_TOKEN>` if the token is configured.

## Candidates

### What it is

For a product that is in a machine and a pending operation, it computes **every machine that could do it**: when the product would arrive, when it would start, when it would finish and what is ahead of it. It is a calculation on the current snapshot of the plant; it **does not simulate** nor change anything.

### How it is produced, when, and how to see it

- On request: `GET /sessions/{id}/candidates?product=<who>&seq=<operation>`. During a run, the worker serves it between two blocks.
- It only makes sense while the product is **inside** a machine and `seq` is its next operation. Otherwise it still answers (200) but with `valid: false` and the reason.
- It is not stored. The real agent copies a summary into its `decisions.jsonl` ([decisions.md](decisions.md#the-real-agents-own-log-decisionsjsonl)).

### General fields

| Field | Meaning | Unit | Values |
|---|---|---|---|
| `product`, `seq` | Product and operation queried | — | — |
| `operation` | Operation to decide | — | O1…O9 |
| `tick`, `time` | Moment of the snapshot | ticks, u.t. | — |
| `valid` | Whether the query makes sense now | — | `true`, `false` |
| `reason` | If it is not valid, why | — | for example `unknown-or-finished-product`, `seq-mismatch`, `not-in-machine` |
| `current_machine` | Machine where the product is | — | M1…M7 |
| `own_remaining` | What is left of its current operation | u.t. | — |
| `next_operation` | The operation after the one being decided | — | O1…O9, or `null` if it is the last |
| `best_by_finish` | Machine that finishes first | — | — |
| `best_by_finish_plus_next` | Machine that finishes first counting the trip to the following operation | — | — |
| `gap_finish`, `gap_finish_plus_next` | Difference between the best and the second in each criterion | u.t. | `null` with only one machine |
| `travel_source` | Where travel times come from | — | `distances` (the model's distances) |
| `candidates` | List of machines, from the one that finishes first to the one that finishes last | — | see below |

### Fields of each machine (`candidates[]`)

**The times (`arrival`, `start`, `finish`, `finish_plus_next`) are absolute**, in u.t. of the simulation clock (comparable with `time`). The others are durations in u.t.

| Field | Meaning |
|---|---|
| `machine` | The machine |
| `own_remaining` | What is left for the product on its current machine |
| `travel` | Trip from its current machine to this one (0 if it is the same) |
| `arrival` | Arrival time: `time + own_remaining + travel` |
| `current_remaining` | What is left of the job this machine has in progress (0 if it is idle or is the current machine) |
| `queue_time`, `queue` | Processing time of the products waiting in its queue, and which they are |
| `en_route_time`, `en_route` | Processing time of the products on their way to it, and which they are |
| `stay_time`, `stay` | Time of the products likely to stay on that machine for another operation, and which they are |
| `available_in` | When it becomes free, counted from now: `current_remaining + queue_time + en_route_time + stay_time` |
| `start` | Start time: `time + max(own_remaining + travel, available_in)` |
| `proc_time` | Duration of the operation on that machine (model time + 10 u.t. of average extra, except on M1) |
| `finish` | Finish time: `start + proc_time` |
| `delta_finish` | `finish` minus the best `finish` (0 for the best) |
| `next_machine`, `travel_next` | For the following operation: the capable machine closest to this one, and the trip |
| `finish_plus_next`, `delta_finish_plus_next` | `finish + travel_next`, and its difference with the best |
| `is_current_machine` | Whether it is the machine where it already is (reprocessed without travelling and ahead of the queue) |
| `available` | Whether the machine is available. Today always `true` |

### Real example

In the live run, paused at tick 642 (one of the four possible machines, excerpt):

```json
{"product": 200, "seq": 1, "operation": "O1", "tick": 642, "time": 199.02, "valid": true, "reason": null,
 "current_machine": "M1", "own_remaining": 14.75, "next_operation": "O1",
 "best_by_finish": "M2", "best_by_finish_plus_next": "M2", "gap_finish": 14.2, "gap_finish_plus_next": 14.2,
 "candidates": [{"machine": "M2", "own_remaining": 14.75, "travel": 111.3, "arrival": 325.07,
                 "current_remaining": 0.0, "queue_time": 0.0, "en_route_time": 0.0, "stay_time": 0.0,
                 "available_in": 0.0, "start": 325.07, "proc_time": 210.0, "finish": 535.07,
                 "delta_finish": 0.0, "next_machine": "M2", "travel_next": 0.0, "finish_plus_next": 535.07,
                 "is_current_machine": false, "available": true, "queue": [], "en_route": [], "stay": []},
                {"machine": "M5", "travel": 125.5, "arrival": 339.27, "start": 339.27, "finish": 549.27,
                 "delta_finish": 14.2, "…": "…"}],
 "travel_source": "distances"}
```

**Reading of machine M2:**
- Product 200 is on M1 (`current_machine`) doing O8; it has 14.75 u.t. left (`own_remaining`). It is now 199.02 u.t.
- The trip to M2 takes 111.3 u.t.: it would arrive at 199.02 + 14.75 + 111.3 = **325.07** (`arrival`).
- M2 is idle and nobody is heading to it (`available_in: 0`): it would start on arrival (`start` = 325.07).
- O1 takes 210 u.t. on M2 (200 + 10 of average extra): it would finish at **535.07** (`finish`).
- M5 would finish 14.2 u.t. later (`delta_finish`), so M2 is the best (`best_by_finish`).
- The following operation is O1 too and M2 can do it: it would stay there (`next_machine: M2`, `travel_next: 0`).

### Pitfalls

- **Absolute times, not durations:** `finish: 535.07` means "at 535.07", not "in 535.07". For durations from now, subtract `time`.
- **It is an estimate:** it does not know the real random extra (it uses the average) nor what the other products will decide.
- **`seq` is the operation** (as in `/decide`), not a row number.

## What-if

### What it is

For a pending decision and **two** possible machines, the platform takes a snapshot of the plant, loads it in two copies and simulates each option separately until the product enters the machine (or until a cap). This compares what would **really** happen, instead of estimating it. The agent only asks for one in very close cases.

### How it is produced, when, and how to see it

- On request: `POST /sessions/{id}/what-if` with `{"product", "seq", "options": [machine A, machine B], "max_ticks" (cap, 3,000 by default), "budget_ms" (budget, 10,000 by default)}`.
- Only with rule-4 sessions and with the decision pending. One per decision.
- The response is not stored; the counters go to the metrics ([metrics.md](metrics.md)). The real agent copies a summary into its `decisions.jsonl`.

### General fields

| Field | Meaning | Unit | Values |
|---|---|---|---|
| `status` | How it ended | — | `ok`, `timeout` (the budget ran out), `skipped` (not run), `error` |
| `skipped_reason` | If it was not run, why | — | `no-free-worker`, `already-used`, `entry-beyond-cap`, or `null` |
| `snapshot_tick`, `snapshot_time` | Moment of the snapshot | ticks, u.t. | — |
| `operation` | Operation being decided | — | O1…O9 |
| `run_order` | Order in which the options were simulated (first the one expected to enter first) | — | — |
| `window_tick` | Tick at which the first copy stopped; the second is compared at that same tick | ticks | — |
| `timings_ms` | `export` (take the snapshot), `import` (load it, sum of both copies), `advance` (simulate, sum), `total` | real ms | — |
| `loads` | Products queued at or heading to each machine | count | — |
| `estimated_entry_ticks` | Estimated ticks, from the snapshot, until the product would enter each machine | ticks | — |
| `would_skip_entry_beyond_cap` | Whether both estimated entries exceed the cap (`max_ticks`) | — | `true`, `false` |
| `options` | Result of each copy, in the order requested | — | see below |

### Fields of each option (`options[]`)

| Field | Meaning | Unit |
|---|---|---|
| `machine` | Machine tested | — |
| `entered` | Whether the product did enter in the copy | — |
| `stop_reason` | Why the copy stopped: `entered` (it entered), `cap` (tick cap), `stalled` (the plant got stuck), `pruned` (it reached the other one's window without entering), `timeout` (no time left), `horizon` (end of the run), `error` | — |
| `entry_tick`, `entry_time` | When it entered (or when it is estimated it would enter) | ticks, u.t. |
| `op_end_time` | When the operation on that machine would end, with the copy's real random extra | u.t. |
| `entry_estimated`, `op_end_estimated` | Whether those values are estimates (the copy stopped before it entered) | — |
| `others` | How **the other products** did in the window: `window_tick`, `work` (nominal work done, u.t.), `wait` (time in the plant without processing, u.t.), `presence` (time in the plant, u.t.), `finished` (how many finished) | — |
| `ticks_simulated`, `stop_tick` | Ticks simulated and stop tick | ticks |
| `cap_reached`, `stalled`, `pruned`, `timed_out`, `skipped` | Flags of the stop reason | — |
| `duration_ms`, `import_ms`, `advance_ms` | Time of the copy: total, loading and simulating | real ms |
| `diagnostic_file` | If the copy got stuck: diagnostic file saved (see below) | — |
| `error` | Error text, if any | — |
| `timings` | Extra field that today comes empty (`{}`) | — |

### Real example

In the same live session, for product 200 between M2 and M5:

```json
{"status": "ok", "skipped_reason": null, "snapshot_tick": 642, "snapshot_time": 199.02, "operation": "O1",
 "window_tick": 1050, "run_order": ["M2", "M5"],
 "timings_ms": {"export": 114.9, "import": 1212.6, "advance": 754.2, "total": 2104.4},
 "loads": {"M2": 0, "M5": 0}, "estimated_entry_ticks": {"M2": 407, "M5": 452}, "would_skip_entry_beyond_cap": false,
 "options": [
  {"machine": "M2", "entered": true, "stop_reason": "entered", "entry_tick": 1050, "entry_time": 325.5,
   "entry_estimated": false, "op_end_time": 548.34, "op_end_estimated": false,
   "others": {"window_tick": 1050, "work": 11.78, "wait": 13.64, "presence": 25.42, "finished": 0},
   "ticks_simulated": 408, "stop_tick": 1050, "pruned": false, "duration_ms": 932.2, "…": "…"},
  {"machine": "M5", "entered": false, "stop_reason": "pruned", "entry_tick": 1095, "entry_time": 339.4,
   "entry_estimated": true, "op_end_time": 549.4, "op_end_estimated": true,
   "others": {"window_tick": 1050, "work": 11.78, "wait": 13.64, "presence": 25.42, "finished": 0},
   "ticks_simulated": 408, "stop_tick": 1050, "pruned": true, "duration_ms": 1034.6, "…": "…"}]}
```

**Line-by-line reading:**
- `status: ok`: both copies ran.
- `snapshot_tick: 642`: the snapshot is from tick 642.
- `estimated_entry_ticks`: it was estimated that it would enter M2 in 407 ticks and M5 in 452, so `run_order` simulated M2 first.
- Option M2: the product really entered (`entered: true`) at tick 1,050, at 325.5 u.t., and its operation would end at **548.34**. That copy stopped there: `window_tick: 1050`.
- Option M5: it was simulated up to the same tick 1,050 and the product had not entered yet: it was cut (`pruned`). Its entry (339.4) and its end (**549.4**) are **estimated**.
- `others` is the same in both: in this window the choice did not change what the other products did.
- Conclusion: M2 finishes ~1 u.t. before M5 and does not harm the others.
- `timings_ms.total: 2104`: the whole what-if took 2.1 real seconds.

Compared with candidates (estimated finish M2 535.07, M5 549.27), the what-if gave M2 an end 13 u.t. later: that is the real random extra of that operation.

### Useful calculations

- **Difference between options** = `op_end_time` of one − `op_end_time` of the other (u.t.). Lower is better.
- **Effect on the others** = compare `others.work` (higher is better) and `others.wait` (lower is better) between options. Only fair if both `others.window_tick` are equal.
- **Real time of each copy** = `import_ms + advance_ms`.

### Pitfalls

- **Estimated values mixed with real ones:** always check `entry_estimated` and `op_end_estimated` before comparing.
- **`others` is only comparable in the same window** (`others.window_tick`); if a copy ran out of time, it may be measured at another tick.
- **`skipped` with `already-used`:** a what-if was already done for that decision; it is not repeated.
- **`timings` inside each option** comes empty; the useful times are in `duration_ms`, `import_ms` and `advance_ms`.

### Diagnostic files (stuck copies)

If a copy gets stuck (`stop_reason: stalled`: the plant stopped moving), the platform saves in `results/whatif_diagnostics/` (variable `ACLOPI_WHATIF_DIAG_DIR`) two files with the same name, `stall_<session_id>_<snapshot_tick>_<machine>_<time>`:
- `.csv`: the snapshot of the plant the copy started from (it can be loaded in NetLogo);
- `.json`: `session_id`, `snapshot_tick`, `product`, `seq`, `options`, `max_ticks`, `budget_ms`, plus `machine`, `stall_tick` (tick at which it was detected), `quiet_ticks` (ticks without changes) and `machines_processing`.

No copy got stuck in this example run, so there is no real example.
