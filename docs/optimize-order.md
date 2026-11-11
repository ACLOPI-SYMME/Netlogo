# Optimize order (platform side)

Before running, the user can ask the platform to look for a better **entry order** for the session's product list. The platform simulates whole orders and shows which one finishes first (makespan) and how much it saves against the user's order. The user picks one; the platform sets the session up again with it; then the session runs as usual.

This document covers the platform: flow, endpoints, states, messages, limits and what is saved. The two pieces it uses come from Línea A and are described in [sequencing.md](sequencing.md):

- `simulate_list` (`aclopi/sim/sequencing.py`): the makespan of a list in a given order, with `details`;
- `POST /sequence/propose` (agent service): up to 2 new orders from the AI, given what was already simulated.

How to read each field: [records/optimize-order.md](records/optimize-order.md).

## Flow on the page (Visualization tab)

1. Create the session with a list (Product set: "Current list" or a saved set).
2. "Optimize order": **Quick (~1 min)** or **Full (~3 min)**. Progress shows with a "Cancel" button.
3. The comparison updates after every simulation: the best order so far ("Use this") and a table with every order evaluated ("Use this order").
4. When the user chooses an order, the platform cuts the rounds that are left and sets the session up again with that order.
5. Run (live or fast). The estimate and the real result are both kept, so they can be compared.

## Rounds

| Round | What | AI |
|---|---|---|
| 0 | The **original** order and the **heuristic** (`largest_first`), simulated one after the other | No call |
| 1..N | `POST /sequence/propose` with the products and **every order evaluated so far** (`order`, `makespan_ticks`, `details`). The valid, new orders it returns are simulated and added | One call per round |

| Mode | `reasoning` sent to the AI | Rounds with the AI | Simulations | Measured duration |
|---|---|---|---|---|
| `quick` | `none` | 1 | up to 4 | ~1 min (5 products, rule 4: 61 s) |
| `full` | `medium` | `ACLOPI_OPTIMIZE_ROUNDS_FULL` (2) | up to 6 | ~3 min with the real LLM |

Rules of the rounds:

- **Validation.** Each order of the AI must be a complete permutation of `0..n−1`. If it is not, it is discarded as `invalid`. If it equals an order already evaluated, or another one of the same answer, it is discarded as `same_as` and marked with that order's name ("same as Heuristic"). It is not simulated again. If the heuristic equals the original, it is listed as "same as Original".
- **Times.** Times always come from `simulate_list`, never from the AI's text.
- **Simulation parameters** (the same for every order):
  - strategy: rules 1–3 → `rule1`–`rule3`; rule 4 → `b1b` (`b1` if the session uses `b1`);
  - mode `Deterministic`;
  - the session's seed;
  - `max_ticks` = the session's horizon. If the list does not finish by then, the order shows "not done by the horizon" and has no makespan.
- **The AI fails or brings nothing valid:** the rounds end with what was evaluated so far (at least the original and the heuristic). It is not an error: the status is `done`, with a `warning`.
- **Agent down:** the platform does not call it. The optimization ends after round 0 with the warning "the AI is not available; only the original and the heuristic were compared". The platform knows the agent is down from its health check (`GET /health` of the agent, the same check the platform already runs).
- **AI timeout:** 90 s per call (`ACLOPI_OPTIMIZE_AI_TIMEOUT_S`). After that, the optimization ends with what was evaluated so far.
- **429 (`sequence_busy`):** the agent runs one ordering call at a time. The platform waits the `Retry-After` it gets, with status `waiting_turn`, and tries again. If the waits add up to more than `ACLOPI_OPTIMIZE_MAX_WAIT_S` (300 s), the optimization ends as `failed` with "optimization busy". What was evaluated is kept and can still be applied.
- **Savings.** The saving is measured against the original order: `original.makespan_time − makespan_time` (u.t.) and the same as a %. A negative saving means the order is worse.

## Where it runs

Every simulation runs on **the session's own worker**, never on a what-if worker:

- **Starting a simulation.** The `optimize_sim` operation starts it and answers at once. The worker runs it in its own loop, like a run: `simulate_list` advances in pieces of at most 1,000 ticks (about 1 s).
- **Between pieces**, the worker:
  - pushes `optimize_sim_progress`;
  - answers `optimize_cancel`, `stop` and `ping`;
  - refuses any other request (`RunStateError`).

  So no request waits for a whole simulation. This is the rule of [workers.md](workers.md).
- **At the end** the worker pushes `optimize_sim_done` with `simulate_list`'s answer, or `optimize_sim_error`.
- **Priority.** The worker lowers its own priority while it simulates and restores it at the end. On Windows this is `BELOW_NORMAL_PRIORITY_CLASS`, then `NORMAL`. On Linux it is `nice +10`, then `0`; going back to 0 needs `CAP_SYS_NICE` (root in the container), otherwise the worker stays at +10.
- **Hung worker.** If 30 s go by without progress from the worker, it is treated as hung and killed, and the session is lost.

`simulate_list` sets the worker up again for each order, so the session's own world is lost while optimizing. **At the end, the platform runs the session's setup again**, with the same seed, rule, strategy, horizon and list:

- with its current order when finished, cancelled or failed without applying anything: the session is **exactly as it was** (tested: a 3,000-tick fast run gives the same KPIs as a session that never optimized);
- with the chosen order when applying.

While an optimization is active, the session refuses every other operation with **409** (`invalid_run_state`), for example run, step or reset. `DELETE` still works and stops the optimization.

## Endpoints

| Route | What it does |
|---|---|
| `POST /sessions/{id}/optimize-order` `{"mode": "quick" \| "full"}` | Starts it. **202** with the state (`Optimization`) |
| `GET /sessions/{id}/optimize-order` | State, round `k` of `N`, progress and results of the session's last optimization. 404 `optimization_not_found` if there was none |
| `POST /sessions/{id}/optimize-order/cancel` | Stops it: the simulation in progress stops in ≤ 1,000 ticks, and a wait for the AI is abandoned at once. Answers when the session has been set up again. 409 if it already ended |
| `POST /sessions/{id}/apply-order` `{"candidate": i}` | Applies the evaluated order `i` (`evaluated[].index`). If the optimization is still running, it **stops the rounds that are left** first. Reorders **the session's copy** of the list (not the saved set) and runs setup again with the same seed, rule, strategy and horizon. Answers `{session, products, optimization}`. Only before running: 409 if the session is not idle at tick 0 |

**When `POST optimize-order` is refused**, checked in this order:

| HTTP | `code` | When |
|---|---|---|
| 409 | `optimize_not_allowed` | Another optimization of the session is in progress |
| 409 | `optimize_not_allowed` | The session is not `idle`, or it already advanced (tick > 0: reset it first) |
| 409 | `optimize_not_allowed` | The session has no list ("needs a product list"): its products come from the seed |
| 422 | `optimize_too_many_products` | More than `ACLOPI_OPTIMIZE_MAX_PRODUCTS` (50) products. Today the API accepts at most 30 per list, so it only applies with a lower value |
| 409 | `optimize_not_allowed` | **Provisional rule**: there is at least one live session with rule 4 and the agent (`running_live`, strategy `agent`): "optimize order is not available while there are live simulations with the agent" |
| 503 | `fast_run_limit` | `ACLOPI_MAX_FAST_RUNS` is full: "another fast simulation or optimization is in progress" |

**An optimization counts as a fast run.** While it is active, it takes one of the `ACLOPI_MAX_FAST_RUNS` slots, so a fast run of another session gets 503 and so does another optimization.

**Provisional rule.** It protects the live agent's LLM calls until Línea A confirms its test of the ordering calls running next to them. `ACLOPI_OPTIMIZE_BLOCK_WHEN_LIVE_AGENT=0` removes it. It applies only when starting: a live agent session started later is not refused.

## States

| `status` | Meaning |
|---|---|
| `running` | Simulating an order (`current`: its name, ticks, products done and total) |
| `waiting_ai` | Waiting for `POST /sequence/propose` (`ai_elapsed_s`) |
| `waiting_turn` | The agent answered 429: waiting `Retry-After` (`waited_s`, in total) |
| `done` | Ended: every round, or fewer if the AI failed, brought nothing new or an order was applied (`stopped_early`) |
| `cancelled` | Cancelled by the user. The session is as it was |
| `failed` | Error: optimization busy (429 for too long), a failed simulation, or the session could not be set up again. What was evaluated is kept |

The final status (`done`, `cancelled`, `failed`) shows only **after** the session's setup has been made again. A client that sees it can run the session at once.

## WebSocket messages

Published on the session's channel (`/ws/sessions/{id}`), with `optimization_id` and `seq`. Detail in [websocket.md](websocket.md) and [records/websocket.md](records/websocket.md).

| `type` | When | Content |
|---|---|---|
| `optimize_progress` | At the start and end of each simulation, at least every 1,000 ticks while it runs, and every second while waiting for the AI or for a turn | `status`, `phase` (`simulating`, `waiting_ai`, `waiting_turn`), `round`, `rounds`, `simulation` (`label`, `ticks`, `done`, `total`), `progress_pct`, `ai_elapsed_s`, `waited_s` |
| `optimize_best` | After each simulation | `evaluated` (the order just simulated) and `best` (the best so far) |
| `optimize_result` | At the end (`done` or `cancelled`), and after an `apply-order` made once it had ended | `result`: the same as `GET /optimize-order` |
| `optimize_failed` | At the end with `failed` | `error` and `result` |

## What is saved

When an order is applied, the session keeps `optimization`. It shows in `GET /sessions/{id}`, and every run saved afterwards copies it into its record (`GET /runs/{id}`), so the estimate shows next to the real result:

```json
{"optimized": true, "mode": "quick", "order": [0, 1, 2, 3, 4], "origin": "original", "label": "Original", "round": 0,
 "estimated_makespan_ticks": 10005, "estimated_makespan_time": 3101.55,
 "estimated_saving_time": 0.0, "estimated_saving_pct": 0.0,
 "estimate_strategy": "b1b", "estimate_mode": "Deterministic", "optimization_id": "d0b7acc1…"}
```

- **The list.** The session's list (`products` in `SessionInfo`) and `products_hash` change to the new order. `product_set_id` stays as the set it came from, and the saved set is not changed.
- **Not applied.** Without applying, `optimization` stays `null`; only `optimize_status` shows the outcome.
- **Not persisted.** The optimization itself (every order evaluated) lives in memory with the session. It is not stored in DynamoDB.

## Configuration

| Variable | Default | Description |
|---|---|---|
| `ACLOPI_OPTIMIZE_ROUNDS_FULL` | `2` | Rounds with the AI in `full` |
| `ACLOPI_OPTIMIZE_MAX_PRODUCTS` | `50` | Longest list that can be optimized (422 above) |
| `ACLOPI_OPTIMIZE_BLOCK_WHEN_LIVE_AGENT` | `1` | Provisional rule: refuse while live agent sessions run (`0` removes it) |
| `ACLOPI_OPTIMIZE_MAX_WAIT_S` | `300` | Total wait for a turn at the AI (429) before failing |
| `ACLOPI_OPTIMIZE_AI_TIMEOUT_S` | `90` | Timeout of each `POST /sequence/propose` |

**Mock agent** (`aclopi.agent_mock`, for tests and local runs). `POST /sequence/propose` takes `products`, `evaluated`, `strategy`, `mode` and `reasoning`. It answers:

- 2 new orders, built from the best one evaluated (reversed, rotated or swapped);
- the heuristic;
- an `analysis`.

Its behaviour can be set with these variables:

| Variable | Effect |
|---|---|
| `ACLOPI_MOCK_SEQUENCE_DELAY_S` | Wait before answering |
| `ACLOPI_MOCK_SEQUENCE_BUSY=n` | The first `n` calls answer 429 with `Retry-After: ACLOPI_MOCK_SEQUENCE_RETRY_AFTER_S` (1 by default) |
| `ACLOPI_MOCK_DOWN=sequence` | `POST /sequence/propose` never answers |

## Notice shown with the results

> Estimate in deterministic mode, with a single seed and a simple rule (b1b) as an approximation of the agent. The real saving may vary.

For rules 1–3 the page says "the session's rule (rule N)" instead of b1b.

In the real example, rule 4 with the agent and 5 products: the estimate (Deterministic, b1b) was 10,005 ticks, and the real fast run (Stochastic, mock agent) took 10,276 ticks.

## Known limits

- **What the AI receives.** The real agent service (`aclopi/agent/service.py`) does not read `reasoning` yet: it uses its own `ACLOPI_SEQUENCE_REASONING`. `quick` and `full` therefore differ in the number of rounds, but not in the reasoning effort, until Línea A accepts the field. The platform already sends it.
- **One optimization at a time.** Only one per session, and only with the session idle at tick 0.
