# Agent decisions

[← Index and glossary](README.md)

## What it is

With rule 4, every time a product has to choose a machine for its next operation, the platform asks the agent. Every answer that arrives is recorded as **one row**: which product, which operation, which machine the agent chose, who decided inside the agent (the code or the LLM), why, how long it took and whether it arrived in time. It is used to understand why a run turned out the way it did and to measure the agent.

## The flow of a decision

```
 1. The product ENTERS a machine (tick = request_tick)
      │   can several machines do its next operation?
      ├── no  → the model assigns the only possible one ("single-option"). NO row.
      └── yes → the model leaves a pending request
 2. The platform reads it at the end of the block and sends POST /decide to the agent  ← latency_ms starts
 3. The agent decides (decision_level):
      ├── code-obvious : the code sees a clearly better machine
      ├── llm          : doubtful case; the LLM decides
      ├── llm-what-if  : very close case; the LLM asked for a what-if and decided with it
      ├── code-fallback: the LLM failed or answered something invalid; the code decides
      └── heuristic    : strategies b1 / b1b (no LLM; experiments only)
 4. The agent sends POST /sessions/{id}/next-machine                                  ← latency_ms ends (tick)
 5. The platform passes it to the model:
      ├── result "ok"  → applied: the product will go to that machine      (late: false)
      └── the product has already moved on → NOT applied                    (late: true)
              in that case, when the product finished its operation,
              the model chose with rule 3 ("rule3-fallback")
```

**The deadline.** The decision has to arrive before the product finishes the operation it is doing (step 1), because at that moment it leaves the machine and needs a destination:

| Machine where the product is | Deadline in ticks | At 1× (32 ticks/s) | At 4× |
|---|---|---|---|
| M1 (O8, O9: 100 u.t.) | ≈ 323 | ≈ 10 s | ≈ 2.5 s |
| M2–M7 (O1–O7: 200 u.t. + random extra, 10 u.t. on average) | ≈ 645 + extra (≈ 32 on average) | ≈ 20 s or a little more | ≈ 5 s |

**Live runs can have late decisions; fast runs cannot.** In fast mode the run **stops** at each request and waits for the agent (state `waiting_decision`), so the answer always arrives in time. If the agent does not answer within 90 s, the run fails with `agent_unavailable` and there is no row.

**What does not leave a row:**
- `single-option` assignments (only one possible machine): counted in the metrics (`single_option`), not here;
- a real agent that, in a live run, sees it has no time left and does not answer: the model uses rule 3 and the request stays "unanswered" in the metrics;
- an invalid answer (a machine that does not exist or cannot do the operation): the platform rejects it with error 422 and does not store it.

## How it is produced and when it is available

- **During the run**, in the session's memory, every time an applied or late `next-machine` arrives. They are seen live through the WebSocket (`decision` message) and in `GET /sessions/{id}/metrics` (list `log`).
- **When the run ends**, they are all saved together with the run (table **`aclopi_decisions`**, key `run_id` + `seq`; or in memory without DynamoDB). From then on, `GET /runs/{id}/decisions`.

## How to see it

| Where | What it shows |
|---|---|
| `GET /runs/{run_id}/decisions` | Every decision of a saved run, in order |
| Page, **Visualization** tab, **"Latest decisions"** panel | The 50 newest of the run in progress, newest on top, with a level filter |
| Page, **History Logs** tab, **"Decisions"** button | All the decisions of a saved run, 50 per page, with a level filter and "Download CSV" |
| DynamoDB | Table `aclopi_decisions` |

Both tables of the page have the columns: Tick, Product (type), Operation, Chosen machine, Level, Reason (short; the full one on hover), Latency, Late.

## Fields (`GET /runs/{id}/decisions`, table `aclopi_decisions`)

| Field | Meaning | Unit | Possible values |
|---|---|---|---|
| `seq` | **Row number** inside the run (0, 1, 2…), in the order they arrived. **Not the operation** | count | 0… |
| `run_id` | Run it belongs to (only in DynamoDB, which uses it as key) | — | — |
| `tick` | Tick at which the platform received the agent's decision | ticks | — |
| `request_tick` | Tick at which the product entered the machine and the request was produced | ticks | — |
| `product` | Product (`who`) | — | 200… |
| `product_type` | Product type | — | A, I, P, B, E, L, T; `null` in decisions saved before 9 Nov 2026 |
| `operation` | Operation decided (the product's next one) | — | O1…O9; `null` in decisions saved before 9 Nov 2026 |
| `seq_op` | Position of that operation in the product's list | — | 0… |
| `strategy` | Strategy of the session | — | `agent`, `b1`, `b1b` |
| `decision_level` | Who decided inside the agent | — | `code-obvious`, `llm`, `llm-what-if`, `code-fallback`, `heuristic` (see the flow) |
| `machine` | Machine chosen by the agent | — | M1…M7 |
| `reason` | The agent's explanation, up to 500 characters | text | From the mock agent: "mock …". From the real agent: for example "Obvious: M3 finishes 230 u.t. earlier" or the LLM's text |
| `latency_ms` | From the moment the platform sent `/decide` until it received `next-machine` | real ms | — |
| `agent_latencies` | Times reported by the agent itself: `total_ms` (its total time), `llm_ms` (list, one per LLM call), `what_if_ms` (if it asked for a what-if). It may have other fields | real ms | or `null` |
| `late` | Whether it arrived late | — | `true`, `false` |
| `result` | The model's answer when applying it | — | `ok` (applied). Late ones: `product-finished` (the product has finished), `stale-seq` (the operation is already past), `not-in-machine` (the product already left the machine), `seq-mismatch` (the product is on another operation) |

## Real example

Fast run (rule 4, mock agent, 5 products): 31 decisions. The first two and one by the LLM:

```json
[{"seq": 0, "tick": 367, "request_tick": 366, "product": 200, "product_type": "A", "operation": "O1", "seq_op": 1,
  "strategy": "agent", "decision_level": "code-obvious", "machine": "M2",
  "reason": "mock code-obvious: best finish", "latency_ms": 453.0,
  "agent_latencies": {"total_ms": 367.1, "llm_ms": null, "what_if_ms": null}, "late": false, "result": "ok"},
 {"seq": 1, "tick": 1012, "request_tick": 1011, "product": 201, "product_type": "E", "operation": "O1", "seq_op": 1,
  "decision_level": "code-obvious", "machine": "M5", "latency_ms": 438.0, "late": false, "result": "ok", "…": "…"},
 {"seq": 2, "tick": 1050, "request_tick": 1049, "product": 200, "product_type": "A", "operation": "O1", "seq_op": 2,
  "decision_level": "llm", "machine": "M2", "reason": "mock llm: best finish", "latency_ms": 984.0,
  "agent_latencies": {"total_ms": 955.6, "llm_ms": [572.4], "what_if_ms": null}, "late": false, "result": "ok"}]
```

Live run (1×), its only decision:

```json
{"seq": 0, "tick": 411, "request_tick": 366, "product": 200, "product_type": "T", "operation": "O1", "seq_op": 1,
 "decision_level": "llm", "machine": "M2", "latency_ms": 1282.0, "late": false, "result": "ok", "…": "…"}
```

**Line-by-line reading of the third row of the fast run (`seq: 2`):**
- `seq: 2`: it is the third decision of the run.
- `request_tick: 1049`: at that tick product 200 entered a machine (here M2, for its first O1) and asked for a destination for the following operation.
- `operation: O1`, `seq_op: 2`: its second O1 was being decided, which is operation number 2 of its list (`O8, O1, O1, …`).
- `decision_level: llm`, `reason`: the case was not obvious; the (mock) LLM decided.
- `agent_latencies.llm_ms: [572.4]`: one LLM call of 572 ms; the agent took 956 ms in total.
- `latency_ms: 984`: for the platform, 984 ms. The difference with the agent's 956 ms is the network trip.
- `tick: 1050`: the decision was recorded one tick after the request: in fast mode the run was stopped, waiting.
- `machine: M2`, `result: ok`, `late: false`: it was applied; the product stays on M2 for that operation.

## Useful calculations

- **Response ticks** = `tick − request_tick`. How far the plant advanced while the agent was thinking.
  - Live, the example: 411 − 366 = **45 ticks**.
  - In fast mode it is always 1 (the run waits), so it says nothing about the agent.
- **Margin against the deadline** = deadline − response ticks. In the live example the product was on M1 (deadline ≈ 323): it had ≈ 278 ticks to spare.
- **Estimated speed** = `(tick − request_tick) / (latency_ms / 1000)`, in ticks per second. It tells at what speed the run was going (1× = 32 ticks/s).
  - In the example: 45 / 1.282 = **35 ticks/s ≈ 1×**. It is not exact because the request is read at the end of a block of ~3 ticks and the decision is applied between blocks.
  - In fast mode it is meaningless (it gives 1 / 0.45 s ≈ 2 ticks/s).
- **Network time** ≈ `latency_ms − agent_latencies.total_ms`.
- **By level:** count rows by `decision_level` (the page has the filter). In the example run: code-obvious 19, llm 8, llm-what-if 3, code-fallback 1.
- **Late ones:** rows with `late: true`. `result` says why.

## Pitfalls

- **`seq` changes meaning depending on where you look.** It is the most common mistake:

  | Where | `seq` is | The operation is in |
  |---|---|---|
  | `GET /runs/{id}/decisions`, table `aclopi_decisions`, CSV of the run | row number | `seq_op` |
  | WebSocket `decision` message | WebSocket message number | `seq_op` |
  | `POST /decide` (platform → agent) and `POST /next-machine` (agent → platform) | the operation | `seq` |
  | `GET /sessions/{id}/metrics`, list `decisions.log` | the operation | `seq` |
  | The real agent's log (`decisions.jsonl`) | the operation | `seq` |

- **`tick` is not when the agent decided**, but when the platform received it.
- **`late: true` is not a recording error**: the decision arrived, but the product had already left. That product followed rule 3 for that operation.
- **A late decision is not the same as an unanswered one.** Unanswered ones have no row; they only appear in the metrics (`unanswered`).
- **`single-option` has no row.** If a product goes through 6 operations and only 2 had several possible machines, you will see 2 rows.
- **With the mock agent**, the levels are drawn at random (the machine is always the one that finishes first) and the reasons start with "mock". They are no use for evaluating the agent.

## Decisions CSV

"Decisions" → **"Download CSV"** produces `decisions-<first 8 characters of run_id>.csv`, with **all** the decisions of the run in chronological order, whatever the level filter:

| Column | Field |
|---|---|
| `tick` | `tick` |
| `product` | `product` |
| `product_type` | `product_type` |
| `operation` | `operation` |
| `machine` | `machine` |
| `level` | `decision_level` |
| `reason` | `reason` (quoted if it contains commas) |
| `latency_ms` | `latency_ms` |
| `late` | `late` (`true` / `false`) |

The CSV of the run ("CSV" button) has another decisions block, with `seq`, `request_tick` and `seq_op` but without type or operation: see [runs.md](runs.md#csv-of-a-run-csv-button-in-the-history-logs-tab).

## The real agent's own log (`decisions.jsonl`)

The real agent (`aclopi.agent`, service `agent` in Docker Compose) keeps its own version of every decision, with what it saw when deciding. **The mock agent does not write it.**

- **Where:** `results/agent/decisions.jsonl` (variable `ACLOPI_AGENT_LOG`), one JSON line per decision; and `GET {agent}/decisions?session_id=…` (the last 5,000, only inside the internal network).
- **When:** at the end of each decision, whether it could be sent or not.
- **No real example:** only the mock agent was run for this document.

| Field | Meaning | Values |
|---|---|---|
| `session_id`, `product`, `seq`, `strategy`, `mode`, `tick` | From the `/decide` request. Here `seq` **is the operation** and `tick` is the `request_tick` | — |
| `level` | Same as `decision_level` | see above; `null` if it did not decide |
| `triage` | How the code classified the case | `obvious` (the code decides), `uncertain` (LLM without what-if), `very_close` (LLM, which may ask for a what-if) |
| `context_source` | Where it got the context from | `decide` (from the request), `state` (it asked for the plant state) |
| `operation`, `current_machine`, `now` | Operation to decide, machine where the product is, `Simulated.Time` (u.t.) | — |
| `candidates` | Per possible machine: `machine`, `finish`, `finish_plus_next`, `delta_finish`, `delta_finish_plus_next`, `available_in`, `travel` (u.t.; see [candidates-and-whatif.md](candidates-and-whatif.md)) | — |
| `gap_finish`, `gap_finish_plus_next` | Difference between the best and the second machine (u.t.) | — |
| `discarded` | Machines discarded for being far behind | list |
| `what_if_offered`, `what_if_requested`, `what_if_options`, `what_if_reason` | Whether the LLM was offered a what-if, whether it asked for one, with which two machines and why | — |
| `what_if` | Summary of the what-if response: `status`, `skipped_reason`, and per option `machine`, `op_end_time`, `op_end_estimated`, `others`, `skipped` | or `null` |
| `machine`, `reason` | Decision | — |
| `estimated_start`, `estimated_finish` | Estimated start and finish on the chosen machine (u.t.) | — |
| `latencies` | Internal times (ms) | — |
| `response` | HTTP code the platform answered the `next-machine` with | 200, 409 (late), 422 (invalid) |
| `rejected` | If 409 or 422: the error code | — |
| `error` | If something failed | text |
| `total_ms` | Total duration of the decision in the agent | ms |
