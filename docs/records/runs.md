# Saved runs

[← Index and glossary](README.md)

## What it is

Every run that finishes, fails or is stopped leaves **one record** with its parameters, its outcome and summaries of what happened. It is used to compare runs (for example, rule 3 against the agent with the same seed and the same set) and to repeat them.

## How it is produced and when it is available

- It is written **once per run**, at the moment the run:
  - **finishes** (`status: "finished"`): it reaches the horizon or every product of the set is finished;
  - **fails** (`status: "failed"`): for example, the agent did not answer in fast mode;
  - **is stopped** (`status: "stopped"`): the session was deleted or reset, or the session was lost or expired.
- A session that is created and never runs leaves no record.
- Available **when the run ends**, a moment later (it is saved in the background). Never during the run.
- Where it is stored:
  - with DynamoDB (Docker Compose and the cloud): table **`aclopi_runs`**, key `run_id`. It survives restarts;
  - without DynamoDB (local development): in memory. **It is lost when the API restarts.**

## How to see it

| Where | What it shows |
|---|---|
| `GET /runs` | List, newest first. Filters: `seed`, `strategy`, `rule`, `product_set_id`, `scenario`; paging: `limit` (1–500, 50 by default) and `cursor` |
| `GET /runs/{run_id}` | One full record |
| Page `/ui`, **History Logs** tab | Table with filters, "Compare selected", "Decisions", "Repeat" and "CSV" |
| DynamoDB | Table `aclopi_runs` (see `docs/deploy-local.md`) |

`GET /runs` answers `{"runs": [...], "next_cursor": "..."}`. If `next_cursor` is not `null`, there are more: ask again with `cursor=<that value>`.

## Fields

| Field | Meaning | Unit | Possible values |
|---|---|---|---|
| `run_id` | Run identifier | — | 32 hexadecimal characters |
| `session_id` | Session that made the run. A session can have several runs (after a reset) | — | 32 hexadecimal characters |
| `created_at` | When the run started | Unix time (s) | — |
| `finished_at` | When the record was saved | Unix time (s) | — |
| `status` | How it ended | — | `finished`, `failed`, `stopped` |
| `reason` | Why it ended | — | With `finished`: `horizon` (reached the horizon), `all_products_done` (every product of the set finished). With `failed`: `agent_unavailable` (in fast mode the agent did not answer in time). With `stopped`: `deleted` (the session was deleted), `reset` (it was reset), `lost: <reason>` (the worker crashed), `expired: <reason>` (the session was closed for inactivity) |
| `ticks` | Tick the run ended at | ticks | — |
| `rule` | Rule used | — | 1, 2, 3, 4 |
| `strategy` | Rule 4 only: who decided | — | `agent` (the agent; what the page creates), `b1`, `b1b` (baselines of the experiments), `none` (no decider, tests only); `null` with rules 1–3 |
| `seed` | Seed used | — | integer from −2,147,483,648 to 2,147,483,647 |
| `seed_source` | Where the seed came from | — | `user` (given by whoever created the session), `random` (drawn by the platform) |
| `modeling_type` | Model mode | — | `Stochastic` (the only one the page uses) or `Deterministic` |
| `horizon_ticks` | Horizon requested | ticks | 1 to 1,000,000 |
| `mode` | Run mode | — | `live`, `fast` |
| `product_set_id` | Saved set used, if one was chosen | — | id of a set, or `null` |
| `products_hash` | Fingerprint (SHA-256) of the product list. Two runs with the same value used exactly the same list | — | 64 hexadecimal characters, or `null` without a list ("Random" on the page) |
| `products` | Copy of the product list used, in entry order (`po`, `item_id`, `number`, `id`, `type`, `priority`, `due_date`; see [product-sets.md](product-sets.md)) | — | list, or `null` without a list |
| `kpis` | Final indicators: `ticks`, `finished`, `created`, `wip`, `work_completed`, `mean_flow_time`, `throughput`, `products_total`, `all_done`, `makespan_ticks`, `makespan_time` | see [kpis.md](kpis.md) | — |
| `utilization` | Fraction of the time each machine was processing | 0 to 1 | `{"M1": …, …, "M7": …}` |
| `decisions_summary` | Summary of the agent's decisions. Same fields as `decisions` in [metrics.md](metrics.md), without the `log` list | — | — |
| `whatif_summary` | Summary of the what-ifs. Same fields as `whatif` in [metrics.md](metrics.md) | — | — |
| `scenario_id`, `scenario`, `scenario_events`, `scenario_summary` | Scenario of the run. Today always `S0`, `{}` and empty | — | see [scenarios.md](scenarios.md) |

## Real example

The fast rule-4 run with 5 products (excerpt):

```json
{"run_id": "acfcb7cbb35a43119f472d1fe812f81f",
 "session_id": "34cf16b45b8745feaedba86430dcc617",
 "created_at": 1794220312.815675, "finished_at": 1794220367.9808335,
 "status": "finished", "reason": "all_products_done", "ticks": 10635,
 "rule": 4, "strategy": "agent", "seed": 42, "seed_source": "user",
 "modeling_type": "Stochastic", "horizon_ticks": 20000, "mode": "fast",
 "product_set_id": "251c64c8e403434daedf9577668305f5",
 "products": [{"type": "A", "priority": 70}, {"type": "E", "priority": 90}, "…3 more"],
 "kpis": {"ticks": 10635, "finished": 5, "created": 5, "wip": 0, "work_completed": 7200.0,
          "mean_flow_time": 2005.82, "throughput": 0.0015166, "products_total": 5,
          "all_done": true, "makespan_ticks": 10018, "makespan_time": 3105.58},
 "utilization": {"M1": 0.304, "M2": 0.324, "M3": 0.446, "M4": 0.376, "M5": 0.643, "M6": 0.196, "M7": 0.0},
 "decisions_summary": {"applied": 31, "late": 0, "by_level": {"code-obvious": 19, "llm": 8, "llm-what-if": 3, "code-fallback": 1}, "…": "…"},
 "whatif_summary": {"requests": 3, "ok": 3, "…": "…"}}
```

And the live run, stopped when its session was deleted:

```json
{"status": "stopped", "reason": "deleted", "ticks": 642, "mode": "live", "seed": 7,
 "products": null, "kpis": {"ticks": 633, "finished": 0, "created": 1, "wip": 1, "…": "…"}}
```

**Line-by-line reading of the first one:**
- `status: finished`, `reason: all_products_done`: it ended normally, because the 5 products of the set finished. It did not reach the horizon (20,000).
- `ticks: 10635`: it ended at that tick. `created_at` → `finished_at`: 55 real seconds.
- `rule: 4`, `strategy: agent`: the agent decided (here, the mock one).
- `seed: 42`, `seed_source: user`: we gave the seed; with it and the same list the run can be repeated.
- `mode: fast`: fast mode; the run waited for the agent at each decision.
- `kpis.finished: 5`, `created: 5`, `wip: 0`: 5 products entered and all 5 finished.
- `kpis.makespan_ticks: 10018` (3105.58 u.t.): the last product finished at tick 10,018. It is the main measure of the experiments: **lower is better**.
- `kpis.mean_flow_time: 2005.82` u.t.: on average, each product took that long from the start of its first operation until it finished.
- `utilization.M5: 0.643`: M5 was processing 64 % of the time; M7 was not used.
- `decisions_summary.applied: 31`: the agent made 31 decisions, none late.

## Useful calculations

- **Real duration of the run:** `finished_at − created_at` (s).
- **Makespan in time:** `makespan_time` (u.t.) ≈ `makespan_ticks × 0.31`.
- **Comparing two runs:** only meaningful if they have the same `seed` and the same `products_hash` (or both without a list). The page groups them that way when comparing.
- **% of decisions by the LLM:** `decisions_summary.by_level_pct.llm + by_level_pct["llm-what-if"]`.

## Pitfalls

- **`ticks` and `kpis.ticks` can differ.** KPIs are computed at most once per second, so in a run stopped half-way (in the example, deleted) they are the last ones computed: `ticks: 642` but `kpis.ticks: 633`. In a `finished` run they match.
- **`decisions_summary` counts the whole session, not only this run.** If the session was reset and ran again, the summary also includes the decisions of the previous runs of the same session. The list of decisions (`GET /runs/{id}/decisions`) is only this run's. With one run per session (the usual case from the page) they match.
- **`makespan_*`, `products_total` and `all_done` only have a value with a product set.** Without a set they are `null` and `false`.
- **In memory, everything is lost when the API restarts.** Runs persist only with DynamoDB.
- **Order with DynamoDB:** `GET /runs` reads the table page by page and sorts each page by date; across pages the order may not be perfect.
- **"Repeat" does not repeat the mode:** it creates a new session with the same rule, strategy, seed, horizon and list; the mode (live or fast) is chosen when starting it.

## CSV of a run ("CSV" button in the History Logs tab)

A file `run-<first 8 characters of run_id>.csv` with two blocks separated by an empty line:

1. **Parameters and KPIs**, as `field,value`, one row per field:
   `run_id`, `status`, `reason`, `rule`, `strategy`, `seed`, `seed_source`, `horizon_ticks`, `mode`, `product_set_id`, `products_hash`, `ticks`, `scenario_id`, then `kpi.<name>` for each field of `kpis`.
2. **Decisions**, with the header `seq,tick,request_tick,product,seq_op,machine,decision_level,late,latency_ms,reason`. The fields are those of [decisions.md](decisions.md); `reason` is quoted.

For a decisions CSV with product type and operation, use "Decisions" → "Download CSV" ([decisions.md](decisions.md#decisions-csv)).
