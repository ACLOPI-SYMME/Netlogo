# Status of Línea A (agent)

Branch `agent/line-a` (from main `f829fbd`, which includes `5c2c39c`). Updated at the end of each phase.

## Phase 0 — "Product set" tab (now "Order entry")

| Requirement | Status |
|---|---|
| Separate tab with the list: add, edit type, delete, reorder by dragging | Already there (Línea B, `live.html`) |
| CSV → the same editable list | Already there |
| Per-row errors visible without discarding the rest | **Added**: on a 422, the frontend resends the CSV without the lines with errors (the API validates again) and loads the rest; empty rows, which the API skips silently, are reported as "empty row" |
| The list sent when creating the session is the one shown, in that order | **Added**: option "Current list" in the session's set selector (chosen automatically when the list is edited); it sends `products` inline in that order. Before, only a saved set could be chosen |

Test: `tests/test_ui_product_set.py` (Playwright, mini-API with the real parser). **Pending:** Playwright
is not installed in the venv and installing it needs internet: proposal `pip install playwright` and use
the installed Edge (`channel="msedge"`, without downloading browsers). Without Playwright the test is skipped. The
page's JS passes `node --check`.

## Phase 1 — candidates (`aclopi/sim/candidates.py`, `aclopi/contracts/candidates.py`)

`compute_candidates` (pure), `read_model_static` and `candidates_for_session` with the agreed signatures.
The stub's `estimate_start`, `machine_loads` and `travel_time` stay the same (used by `aclopi/sim/whatif.py`
and the worker). Note for Línea B: the stub's `travel_time` computes `distances / 0.3 × 0.31`, 3.3 %
more than the measured real trip (`distances` is already in u.t.); `estimate_start` should use
`aclopi.sim.candidates.travel`.

Measured trip (`data/a0/travel_times.csv`): on the 16 routes with 2 or more trips, the minimum = `distances`
(±0.1 %). The 3 routes seen only once (M3→M7, M6→M5, M6→M4) included waits (+7 % to +78 %);
`distances` is their lower bound.

**Fields of `CandidatesResult` (for Línea B).** The stub's fields are kept with the same name and type.

| Field | Type | Meaning |
|---|---|---|
| `product`, `seq`, `operation`, `tick`, `time`, `valid`, `reason` | – | same as the stub (`reason`: `unknown-or-finished-product`, `invalid-seq`, `seq-mismatch`, `not-in-machine`) |
| `candidates` | list | sorted by `finish` (tie: lowest machine number) |
| `current_machine` | str | machine where the product is being processed |
| `own_remaining` | u.t. | what is left of its current operation |
| `next_operation` | str \| null | operation `seq+1` |
| `best_by_finish`, `best_by_finish_plus_next` | str | best by each criterion |
| `gap_finish`, `gap_finish_plus_next` | u.t. \| null | second − best (null with one candidate) |
| `travel_source` | str | `"distances"` |

Per candidate:

| Field | Type | Meaning |
|---|---|---|
| `machine` | str | |
| `own_remaining`, `travel`, `current_remaining`, `queue_time`, `en_route_time` | u.t. (duration) | `travel` = `distances[current][m]`, 0 if it is the current machine |
| `available_in` | u.t. | `current_remaining + queue_time + en_route_time` (= `own_remaining` if it is the current machine) |
| `arrival`, `start`, `finish`, `finish_plus_next` | **absolute** u.t. (as in the stub) | `arrival = now + own + travel`, `start = now + max(own + travel, available_in)`, `finish = start + proc_time` |
| `proc_time` | u.t. | `Machine.Operations.Time` + 10 (Stochastic, not on M1) |
| `delta_finish`, `delta_finish_plus_next` | u.t. | against the best of each criterion |
| `next_machine`, `travel_next` | str \| null, u.t. | closest machine for `seq+1` (trip 0 if it is the same) |
| `available` | bool | `machine-available?` hook (today always true). Kept as bool because the API's `CandidateInfo` types it that way; the available time is in `available_in` |
| `is_current_machine` | bool | reprocessed in place: no trip, no queue |
| `queue`, `en_route` | lists of who | products counted in each term |

Differences with the design: `arrival/start/finish` are absolute (compatibility with the stub) and the
available time is called `available_in` (in the API `available` is a bool). En route = live products that
are not in the queue nor in process on the candidate and are heading to it: travelling or waiting to leave
their station with `Heading.Workstation` = candidate, or in process (also on the candidate itself,
reprocessing in place) with `AI.Next.Machine` = candidate for their next operation.

## Phases 2–5 — filter, LLM, flow and service

- `aclopi/agent/triage.py`, `strategies.py` (b1, b1b, the agent's code level), `local.py` (b1/b1b as
  rule-4 deciders over `SimulationSession`, fast mode, main thread).
- `aclopi/agent/llm/` (fake, ollama, anthropic) and `aclopi/agent/prompts/` (largest prompt ≈ 800 estimated tokens).
- `aclopi/agent/core.py`: flow with live and fast deadlines, what-if, fallback and a record per decision.
- `aclopi/agent/service.py` (`python -m aclopi.agent`, port 8100), `docker/agent.Dockerfile`,
  `requirements-agent.txt`, service `agent` in `docker-compose.yml` with `profiles: [agent]`,
  `.env.agent.example`.

## Línea A's comments on the proposal (`docs/agent-api.md`, `aclopi/contracts/agent.py`)

1. **Agreed** with `/decide` → 202, `next-machine`, levels, token, 409/422 without retry and the record.
2. **`latencies`:** the agent can also send `what_if_ms`; `Latencies` already accepts extras, but it should be documented.
3. **`/decide` could carry `own_remaining`, the product type and its pending operations.** Today the agent
   needs `GET /state` besides `candidates` for the prompt's context (2 calls per decision).
4. **`CandidateInfo` types `available` as bool.** The agent keeps it (`machine-available?` hook) and publishes the time
   in `available_in`. The new fields (`available_in`, `proc_time`, `travel_next`, `is_current_machine`, `queue`,
   `en_route` and, in the result, `best_by_*`, `gap_*`, `current_machine`, `own_remaining`, `next_operation`,
   `travel_source`) should be declared in the API model so that they appear in the OpenAPI; today they pass as extras.
5. **The what-if's `estimate_start`** computes the trip with `distances / 0.3 × 0.31`; the measured one is `distances` (−3.3 %).
6. **Fast-mode deadline:** the agent uses a 60 s safety margin + what-if ≤ 15 s, below
   `ACLOPI_FAST_DECISION_TIMEOUT_S` (90 s). That order should be kept if any of them changes.
7. **The agent's `/health`** answers 200 with `{"llm": "ok"|"down"|"unknown"}`. With the LLM down b1/b1b keep working
   and `agent` decides by `code-fallback`; the platform could show that state.
8. **Rule 4 in the API:** `SessionCreate` already accepts rule 4 with `strategy`; nothing to ask for.
9. **KPIs `created` and `work_completed`:** still not in the API's `Kpis` model (2 tests accepted as failing).

## Phase 6 — experiments and smoke test

- `scripts/a4/run_experiments.py` (strategies × seeds, fixed list of N products, fast mode, CSV per run,
  resumable, progress every 30 s, `--events` saves the WebSocket events) and `scripts/a4/estimation_error.py`.
- **Smoke test (once).** Local platform with 1 session worker and 1 what-if worker; agent with the fake LLM
  (0.5 s, 10 % invalid JSON, asks for a what-if in half of the very close ones). 10 products, seed 42, fast.

| Strategy | makespan_ticks | All finished | Decisions | Levels |
|---|---|---|---|---|
| rule3 | 14357 | yes | 0 | – |
| b1 | 14580 | yes | 60 | heuristic 100 % |
| agent | 15565 | yes | 60 | llm 48.3 %, code-obvious 36.7 %, code-fallback 8.3 %, llm-what-if 6.7 % |

  409/422 rejections: 0 (no `stale-seq`). The agent's filter: 22 obvious, 27 doubtful, 11 very close; 5 what-ifs
  requested, all 5 `ok`. The 5 `code-fallback` are invalid JSON from the fake. It only checks that it works: there
  are no conclusions about the makespan.
- **Error of `estimated_finish`** against the real end (120 decisions, u.t.; negative = optimistic): mean −65.6,
  median 2.8, p90 of |error| 202.5. The median is almost 0, but the mean is biased towards optimism: in
  some of the decisions the operation ends well after the estimate (waits at gates or crossings that
  `candidates` does not model).

## Diagnosis of the `finish` error and `occupant_may_stay`

`scripts/a4/diagnose_finish_error.py`, over the events of the smoke test, without simulating. 16 decisions with
the real end > 100 u.t. after the estimate (7945 u.t. in total):

| Cause | Main cause in | u.t. explained |
|---|---|---|
| (a) the occupant of the chosen machine reprocessed in place | 16 | 7627 (96 %) |
| (b) another product, not counted, arrived | 0 | 0 |
| (c) trip / entry slower than `distances` | 0 | 190 (~11 u.t. per case: sensor → station section) |
| (d) other (own processing, counted jobs) | 0 | 129 |

(a) depends on the machine, it is not common to every candidate: it changes which one wins. Change:
`CandidateParams.occupant_may_stay` (true by default). The occupant of a candidate, and the first of its queue,
add the `proc` of their next operation if that machine can do it (if the next one is already counted by
`AI.Next.Machine`, the one after it). New fields per candidate: `stay_time`, `stay`.

Error of `estimated_finish` in b1 (10 products, seed 42; u.t., negative = optimistic):

| | Mean | Median | p90 of \|error\| |
|---|---|---|---|
| without `occupant_may_stay` | −58.2 | 3.2 | 197.7 |
| with `occupant_may_stay` | −31.0 | −2.2 | 46.2 |
| with chain (`occupant_chain_max` = 3) | −12.9 | −0.3 | 23.4 |

Chain: the occupant (and the first of the queue) adds all its consecutive operations that the machine can
do, up to the first one it cannot or up to `occupant_chain_max` (3).

## Pending / blocked

- Solved: `langgraph` 1.2.19 and `playwright` 1.64.1 installed (`requirements-agent.txt`,
  `requirements-agent-dev.txt`). `core.py` uses the real `StateGraph`; its own runner is only kept as a
  fallback if LangGraph is not available. The browser test runs with the installed Edge (`channel="msedge"`).
- **respx is not installed;** the tests use `httpx.MockTransport` (equivalent, no new dependency).
