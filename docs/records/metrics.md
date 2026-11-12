# Session metrics

[← Index and glossary](README.md)

## What it is

Counters and timings of a session, in two groups: **`decisions`** (how the agent did: how many decisions, of which level, how many late, how long they took) and **`whatif`** (how many what-ifs were requested, how they ended and how long they took). It gives an overview of the agent's behaviour without going through every decision.

## How it is produced and when it is available

- It is updated **live**, as long as the session exists: every decision and every what-if adds to the counters.
- It accumulates **over the whole life of the session**: a `reset` does **not** set it back to zero.
- When a run ends it is copied to the saved run as `decisions_summary` (without `log`) and `whatif_summary` ([runs.md](runs.md)).
- It disappears when the session is closed.

## How to see it

- `GET /sessions/{id}/metrics` → `{"whatif": {...}, "decisions": {...}}`.
- The page reads it every 2 s and shows a summary in the "Agent" part of the **Indicators** panel (Visualization tab).

## Group `decisions`

| Field | Meaning | Unit | Values |
|---|---|---|---|
| `strategy` | Strategy of the session | — | `agent`, `b1`, `b1b`, `none`; `null` with rules 1–3 |
| `requests_sent` | Requests sent to the agent = recorded decisions + pending ones | count | — |
| `decide_failed` | `/decide` sends that failed (the agent did not accept the send) | count | — |
| `applied` | Decisions applied (not late) | count | — |
| `late` | Late decisions | count | — |
| `unanswered` | Requests with no answer yet (or that will never have one) | count | — |
| `by_level` | Applied ones by level | count | keys: `code-obvious`, `llm`, `llm-what-if`, `code-fallback`, `heuristic` |
| `by_level_pct` | The same as a % of `applied` | % | — |
| `sources` | How the model assigned each destination with rule 4 | count | keys: `agent` (used the agent's decision), `rule3-fallback` (no decision in time: used rule 3), `single-option` (only one possible machine) |
| `rule3_fallback_pct` | % of assignments with several possible machines that ended in rule 3: `rule3-fallback / (agent + rule3-fallback)` | % | `null` if there were none |
| `single_option` | Equal to `sources["single-option"]` | count | — |
| `latency_ms` | Latency of the applied ones: `mean`, `p95`, `max`, `n` | real ms | `null` if there were none |
| `log` | List of decisions (applied and late): `tick`, `request_tick`, `product`, `seq` (**the operation**), `machine`, `decision_level`, `late`, `latency_ms`, `reason` | — | see [decisions.md](decisions.md) |

## Group `whatif`

| Field | Meaning | Unit |
|---|---|---|
| `requests` | What-ifs requested | count |
| `ok`, `timeout`, `error` | Ended with that `status` | count |
| `invalid` | Rejected for invalid data (for example, the decision was no longer pending, or the session is not rule 4) | count |
| `skipped` | Not run, by reason: `no-free-worker` (no free what-if worker), `already-used` (one was already done for that same decision), `entry-beyond-cap` (both options would enter beyond the tick cap) | count per reason |
| `would_skip_entry_beyond_cap` | How many would have been skipped for `entry-beyond-cap` if that criterion were active (today it is only recorded) | count |
| `options_run` | Copies simulated (2 per complete what-if) | count |
| `entered` | Copies in which the product did enter the tested machine | count |
| `cap_reached` | Copies that reached the tick cap (`max_ticks`) | count |
| `stalled` | Copies that got stuck (the plant stopped moving) | count |
| `pruned` | Copies cut when reaching the other one's window without having entered | count |
| `options_timed_out` | Copies cut for lack of time | count |
| `duration_ms` | Total duration of each what-if (`mean`, `p95`, `max`, `n`) | real ms |
| `export_ms` | Time to take the snapshot of the plant | real ms |
| `import_ms` | Time to load the snapshot in the what-if workers (sum of both copies) | real ms |
| `advance_ms` | Time simulating (sum of both copies) | real ms |
| `ticks_to_entry` | In copies where the product entered: ticks from the snapshot until the entry | ticks |
| `ticks_simulated` | Ticks simulated per copy | ticks |

The timing fields are `null` while there has been no what-if.

## Real example

Fast run (rule 4, mock agent, 5 products), excerpt:

```json
{"decisions": {"strategy": "agent", "requests_sent": 31, "decide_failed": 0, "applied": 31, "late": 0,
               "unanswered": 0,
               "by_level": {"code-obvious": 19, "llm": 8, "llm-what-if": 3, "code-fallback": 1},
               "by_level_pct": {"code-obvious": 61.3, "llm": 25.8, "llm-what-if": 9.7, "code-fallback": 3.2},
               "sources": {"agent": 31, "single-option": 5}, "rule3_fallback_pct": 0.0, "single_option": 5,
               "latency_ms": {"mean": 1179.4, "p95": 5313.0, "max": 7515.0, "n": 31},
               "log": [{"tick": 367, "request_tick": 366, "product": 200, "seq": 1, "machine": "M2",
                        "decision_level": "code-obvious", "late": false, "latency_ms": 453.0, "reason": "…"}]},
 "whatif": {"requests": 3, "ok": 3, "timeout": 0, "error": 0, "invalid": 0, "options_run": 6, "entered": 3,
            "pruned": 3, "cap_reached": 0, "stalled": 0, "options_timed_out": 0,
            "skipped": {"no-free-worker": 0, "already-used": 0, "entry-beyond-cap": 0},
            "duration_ms": {"mean": 5489.3, "p95": 6703.5, "max": 6703.5, "n": 3},
            "ticks_to_entry": {"mean": 859.7, "p95": 1160.0, "max": 1160.0, "n": 3}, "…": "…"}}
```

**Line-by-line reading:**
- `requests_sent: 31`, `applied: 31`, `late: 0`, `unanswered: 0`: every request got an answer in time (expected in fast mode).
- `by_level`: 19 obvious cases for the code, 8 decided by the LLM, 3 by the LLM with a what-if, 1 fell back to the code because the LLM failed.
- `sources`: the model used the agent's decision 31 times and there were 5 assignments with only one possible machine, which did not go through the agent. **36 assignments in total.**
- `rule3_fallback_pct: 0.0`: rule 3 never had to decide.
- `latency_ms.p95: 5313`: 95 % of the decisions took less than 5.3 s (the mock LLM was configured to be slow on purpose).
- `whatif.requests: 3`: they match the 3 `llm-what-if` decisions. `options_run: 6`: two copies each. `entered: 3` and `pruned: 3`: in each what-if, one copy did enter and the other was cut when reaching the window.

## Useful calculations

- **Total assignments with rule 4** = `sources.agent + sources["rule3-fallback"] + sources["single-option"]`.
- **% of LLM decisions** = `by_level_pct.llm + by_level_pct["llm-what-if"]`.
- **% late** = `late / (applied + late)`.
- **Mean time per what-if copy** ≈ `(import_ms.mean + advance_ms.mean) / 2`.

## Pitfalls

- **It accumulates the whole session.** After a `reset`, the counters keep adding up. For one run, look at the saved run and its list of decisions; with only one run per session it is the same.
- **`sources` can lag behind** `applied`: it is read from the model at the end of each block. In the live run of the example, deleted right after its only decision, it ended with `applied: 1` and `sources: {}`.
- **`unanswered` includes those still being thought about**, not only the lost ones. At the end of a run, if it is still above 0, those requests never got an answer.
- **In `log`, `seq` is the operation**; in the saved decisions it is the row number ([decisions.md](decisions.md#pitfalls)).
- **`ticks_simulated` counts every copy; `ticks_to_entry` only those that entered**, which is why their `n` can differ.
