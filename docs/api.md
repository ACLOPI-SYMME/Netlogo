# REST API (L5.2)

HTTP API (FastAPI) over the L5.1 `WorkerPool` (`docs/workers.md`). Code in `aclopi/api/`. The contract for Línea A is in `contracts/openapi.json`, generated with `python scripts/export_openapi.py`; a test checks that the committed file matches the app.

**How to read the data the platform produces** (runs, decisions, metrics, KPIs, events, WebSocket messages, logs…), field by field and with real examples: [`docs/records/README.md`](records/README.md).

## One process, one uvicorn worker

Each API process starts its own pool: 7 processes with their JVM, about 3.3 GB. If several uvicorn workers are used (`--workers N`), or two APIs on the same working folder, several pools are started, with twice the JVMs and the memory. To avoid it:

- `python -m aclopi.api` sets `workers=1`, without `reload` and without an option to change it. Do not launch the app with `uvicorn ... --workers`.
- On startup, the API takes the file `<ACLOPI_WORK_DIR>/api.lock`, which stores the pid, the host and the start time of the process:
  - if another live instance holds it, the startup fails with a clear message and exit code 3;
  - a file left by a dead process, or by another container sharing `results/`, is detected as stale and replaced.

To serve more users, add workers to the pool (`ACLOPI_N_SESSION_WORKERS`), not API processes.

## Startup and health

The pool starts in the background when the API comes up (lifespan), so uvicorn answers from the first second. The platform's phases are:

| Phase | Meaning |
|---|---|
| `starting` | The workers are loading and warming up. `POST /sessions` answers 503 `platform_starting`. |
| `ready` | The 7 workers are ready. |
| `degraded` | It has started, but some worker is restarting or failed. Sessions are accepted while there are free workers. |
| `failed` | Some worker did not start within `ACLOPI_STARTUP_TIMEOUT_S`. |
| `stopping` | The API is shutting down. |

If the startup fails, the JSON log says which worker failed and why. Then the pool shuts down in order and the process ends with **exit code 3**. In the cloud, Docker's restart policy is what retries (see README).

| Route | Response | Use |
|---|---|---|
| `GET /health/live` | 200 while the process answers, also during startup | The Dockerfile's `HEALTHCHECK` |
| `GET /health/ready` | 200 with `ready` or `degraded`; 503 with `starting`, `failed` or `stopping` | Cloud load balancer |
| `GET /health` | Always 200 | Detail: phase, active sessions and, per worker: role, ready, state, pid, memory, restarts and session |

`/health` reads the pool's state without talking to the workers, so it answers even when they are busy.

## Endpoints

| Method and route | Description |
|---|---|
| `POST /sessions` | Creates a session (`seed`, `rule` 1\|2\|3\|4, `modeling_type`, `horizon_ticks`) on a free worker and runs the setup. Returns 201 `SessionInfo` |
| — | **Scenarios: not available** (`docs/scenarios.md`). `GET /scenarios` no longer exists. `POST /sessions` only accepts `scenario` as S0 without parameters (the original plant); with any other it answers 422 `scenarios_unavailable` ("scenarios are not available") |
| `GET /sessions` | Every session: active, lost and expired |
| `GET /sessions/{id}` | Parameters, last known tick, whether it finished, state, reason for the loss and last activity |
| `POST /sessions/{id}/step?n=` | Advances up to `n` ticks (1–2000); stops at the horizon |
| `POST /sessions/{id}/reset` | Repeats the setup with the same parameters |
| `GET /sessions/{id}/state` | `platform-state` |
| `GET /sessions/{id}/events` | Events since the previous call. **Not idempotent**: reading them empties the buffer |
| `GET /sessions/{id}/layout` | `platform-layout` |
| `GET /sessions/{id}/kpis` | KPIs of the current state; does not alter the simulation |
| `DELETE /sessions/{id}` | Closes the session, stops its run and frees its worker (204) |
| `POST /sessions/{id}/run` | Continuous run: `{"mode": "live", "speed": 0.5\|1\|2\|4}` or `{"mode": "fast"}` (L5.3). Also changes the mode or the speed of a running or paused run |
| `POST /sessions/{id}/pause` | Pauses a run (409 if it is not running) |
| `POST /sessions/{id}/resume` | Resumes with the same mode and speed (409 if it is not paused) |
| `WS /ws/sessions/{id}` | Real-time stream (format in `docs/websocket.md`) |
| `GET /sessions/{id}/candidates?product=&seq=` | Candidates of a pending decision, with their load and estimated wait (L5.4, `docs/whatif.md`) |
| `POST /sessions/{id}/what-if` | Tests 2 assignments of a decision in copies of the simulation, within `budget_ms` (10 s by default, 2 to 15 s; the agent computes it from its decision deadline: from M2–M7 ~10 s fits, from M1 it does not fit together with the LLM calls). Rule 4 only; `docs/whatif.md` |
| `GET /sessions/{id}/metrics` | Session metrics: what-if (`whatif`) and decisions (`decisions`, L5.5) |
| `POST /sessions/{id}/next-machine` | The agent's decision for a pending request (rule 4; `docs/agent-api.md`) |
| `POST /sessions/{id}/optimize-order` | "Optimize order": no body (a `mode` sent by old clients is ignored), 202. Simulates the original order, the heuristic and the AI's proposals, on the session's worker (`docs/optimize-order.md`) |
| `GET /sessions/{id}/optimize-order` | State, progress and results of the last optimization |
| `POST /sessions/{id}/optimize-order/cancel` | Stops it; the session stays as it was |
| `POST /sessions/{id}/apply-order` | `{"candidate": i}`: stops the rounds left and sets the session up again with that order |

**Results (L5.7).**
- Each run is saved when it finishes, fails or is stopped, in memory or in DynamoDB depending on `ACLOPI_DYNAMODB_ENDPOINT` / `ACLOPI_RESULTS_STORE`.
- Routes:
  - `GET /runs`, with filters `seed`, `strategy`, `rule`, `product_set_id`, `scenario` (only useful for runs saved before scenarios were taken out), `limit` and `cursor`;
  - `GET /runs/{id}`;
  - `GET /runs/{id}/decisions`: each decision also carries `operation` and `product_type` (those saved since that change). The page shows them with the "Decisions" button (History Logs tab), paginated and downloadable as CSV.
- `SessionInfo.last_run_id` gives the session's last saved run.
- Detail in `docs/deploy-local.md`.

**Product sets and optional seed (L5.6).**
- `POST /sessions` accepts `product_set_id` or `products` (at most 30 products), and `seed` is optional: without it one is drawn, and it is kept in `parameters.seed` with `seed_source`.
- Routes `/product-sets*`.
- KPIs `products_total`, `all_done`, `makespan_ticks` and `makespan_time`.
- A session with a list ends with `run_reason: "all_products_done"`.
- Detail in `docs/product-sets.md`.

**Strategies (L5.5).** With `rule: 4`, `POST /sessions` accepts `strategy`, which is **optional**:

| `strategy` | Behaviour | User option? |
|---|---|---|
| `agent` (default) | The AI agent decides (code → LLM → what-if) | Yes: for the user, rule 4 **is** the agent |
| `b1`, `b1b` | Call the agent with the baseline strategies | No: comparison points of Línea A's experiments |
| `none` | Rule 4 without a decider, equal to rule 3 | No: tests only |

- With `rule: 4` and no `strategy`, the value is `agent`.
- `b1`, `b1b` and `none` are still accepted by the API, but the page (`/ui`) does not offer them: rule 4 always creates the session with `agent`. In the list of runs, a run with `b1`/`b1b` shows as "Rule 4 (B1)" or "Rule 4 (B1b)", and "Repeat" keeps its strategy.
- With rules 1–3, sending `strategy` answers 422.
- `SessionInfo` includes `strategy`, `run_reason` (for example `agent_unavailable`), `pending_decisions` and `warnings`.
- `candidates`, `what-if` and `next-machine` require `Authorization: Bearer` when `ACLOPI_AGENT_TOKEN` is set.
- `GET /health` shows the state of the agent (`agent`), which does not affect `/health/ready`.
- Details in `docs/agent-api.md`.

**Rule 4.** `POST /sessions` accepts `rule: 4` (AI Agent). Without a decider it behaves exactly like rule 3.

**KPIs** (`GET /kpis`, WebSocket messages):

| KPI | Definition |
|---|---|
| `finished`, `wip`, `created` | Products finished, in process and created (`created` = finished + in process) |
| `throughput` | Finished ÷ `Simulated.Time` |
| `mean_flow_time` | Mean of (last completion − **start of the first operation**, `ProductRealStart`) of the finished ones. **Measured from the first operation, not from creation** (`docs/product-sequence.md`) |
| `utilization` | Busy time ÷ `Simulated.Time`, per machine |
| `work_completed` | Processing work in **nominal** time (`OperationDuration`): the operation in progress adds the fraction processed |
| `GET /ui` | Minimal HTML test page (outside the OpenAPI contract) |

## Continuous runs (L5.3)

The worker runs the run inside its own loop, in short blocks: it is never a long request. Between blocks the worker keeps serving `state`, `kpis`, pause and export for what-if.

- **Live:** the target pace is 32 ticks/s × speed. There is a block every ~100 ms (`ACLOPI_LIVE_UPDATE_MS`) and, after each block, a message with the state and the new events. The worker sets the pace, not the client.
- **Fast:** no speed limit, in blocks of `ACLOPI_FAST_BLOCK_TICKS` ticks (1000 by default). For each block the progress and the block's events are sent, without the full state.
- **Results:** they do not depend on the speed nor on the block size. A run to the end gives the same KPIs as `SimulationSession` directly with the same seed (verified by `tests/test_live.py`).

States (`run_state` in `SessionInfo`, together with `mode` and `speed`):

```
idle ──run──► running_live / running_fast ──pause──► paused ──resume──► (same mode and speed)
  ▲              │  run with another mode or speed: changes without stopping
  │ reset        ▼ horizon (also by a manual step)
  └─────────── finished
```

With a decider and in fast mode, the run goes to `waiting_decision` while it waits for the agent. If nobody answers within `ACLOPI_FAST_DECISION_TIMEOUT_S` it ends in `failed`, with `run_reason: "agent_unavailable"`; from `failed` only `reset` is valid.

| Request | idle | running_* | paused | finished |
|---|---|---|---|---|
| `step` | ✔ | 409 | ✔ | 200 with `advanced: 0` |
| `run` | ✔ | ✔ (changes mode or speed) | ✔ | 409 |
| `pause` / `resume` | 409 / 409 | ✔ / 409 | 409 / ✔ | 409 / 409 |
| `events` (HTTP) | ✔ | 409 (events go through the WebSocket) | ✔ | ✔ |
| `reset`, `state`, `kpis`, `layout`, `DELETE` | ✔ | ✔ | ✔ | ✔ |

**Simultaneous fast runs.** At most `ACLOPI_MAX_FAST_RUNS` (1 by default). Past the limit, `run` (or `resume` of a paused fast run) answers 503 `fast_run_limit`. Live runs have no such limit. The goal is that a fast run, which takes a whole core, does not slow down the live sessions. **For experiment runs without live users** (for example, Línea A with rule 4) it can be raised, for example to 4.

**Watchdog.** If a running session sends no message for 15 s (`RUN_WATCHDOG_S` × `ACLOPI_TIMEOUT_SCALE`), the API treats the worker as hung: it kills it and the session is lost (410). Blocks last much less than 1 s. The `waiting_decision` state (waiting for the agent) sends a heartbeat so as not to hit this limit.

Notes:
- `ticks` and `finished` of `SessionInfo` are the last known value. Every advance goes through the API, so the value is exact, and reading it does not query the worker.
- The workers' diagnostic operations (`command`, `report`) do not exist in the API, and the pool is always created with `debug=False`.
- A `step` on a session that already finished answers 200 with `advanced: 0`.

## Errors

The body is `{"code": ..., "detail": ..., "session_id": ...}`. The exception is 422, which uses FastAPI's standard format (except the platform's own 422 codes, such as `scenarios_unavailable` or `invalid_option`).

| HTTP | `code` | When |
|---|---|---|
| 404 | `session_not_found` | Unknown id or session already deleted |
| 409 | `invalid_run_state` | The request is not allowed in the run's state (e.g. `step` while it runs, or anything but `DELETE` while the session optimizes its order) |
| 409 | `optimize_not_allowed` | Optimize order: the session is not idle at tick 0, has no list, already optimizes, or live agent sessions run (provisional rule) |
| 404 | `optimization_not_found` | `GET`, `cancel` or `apply-order` without a previous `POST optimize-order` |
| 422 | `optimize_too_many_products` | Optimize order: more than `ACLOPI_OPTIMIZE_MAX_PRODUCTS` products |
| 410 | `session_lost` | The session's worker crashed or hung. `detail` gives the reason |
| 410 | `session_expired` | The session was closed for inactivity |
| 422 | – | Invalid parameters (`n` outside 1–2000, rule, modelling type, extra fields, more than 30 products) |
| 500 | `simulation_error` | NetLogo or worker error, with its message. The worker stays alive |
| 503 | `platform_starting` | The platform is starting |
| 503 | `no_free_worker` | Every session worker is busy |
| 503 | `fast_run_limit` | There are already `ACLOPI_MAX_FAST_RUNS` fast runs or optimizations in progress (an optimization counts as a fast run) |
| 503 | `worker_unavailable` | The worker crashed during the creation, or the platform is not ready (`failed` or `stopping`) |
| 504 | `worker_timeout` | The worker did not answer in time. The pool restarts it and the session is lost, so the next request gives 410 |

Lost or expired sessions still appear in `GET /sessions` and answer 410 until they are deleted with `DELETE` or 24 h go by (at most 1000 are kept).

## Concurrency

- Calls to the workers are blocking and run in threads (`anyio.to_thread`, at most 32 at once), never in the event loop.
- Each session has an `asyncio.Lock`, so its requests run one at a time and in order of arrival. Different sessions advance in parallel.
- If the client disconnects, the request in progress finishes anyway and the lock is released.
- So as not to hand out a dead worker, a worker killed by a timeout still shows as busy until the pool's monitor restarts it.

## Inactivity

A session without activity for `ACLOPI_SESSION_IDLE_TIMEOUT_S` seconds (1800 by default) closes by itself: its run stops and its worker becomes free.

What counts as activity:
- **HTTP requests:** any request to the session, including `GET /sessions/{id}`. `GET /sessions` does not count.
- **WebSocket clients:** they count **only while the session is in `running_live` or `running_fast`**. In `idle`, `paused` or `finished` only HTTP requests count, so a forgotten tab does not hold a worker forever.
- **A run with nobody around:** a session that runs with nobody watching or asking for anything also closes when the time is up.

A session with a request in progress never closes.

## Configuration (environment variables)

| Variable | Default | Description |
|---|---|---|
| `ACLOPI_API_HOST` | `0.0.0.0` | Interface it listens on |
| `ACLOPI_API_PORT` | `8000` | Port |
| `ACLOPI_N_SESSION_WORKERS` | `5` | Session workers |
| `ACLOPI_N_WHATIF_WORKERS` | `2` | What-if workers |
| `ACLOPI_SESSION_IDLE_TIMEOUT_S` | `1800` | Seconds without requests before closing a session |
| `ACLOPI_STARTUP_TIMEOUT_S` | `300` | Maximum time for every worker to start |
| `ACLOPI_TIMEOUT_SCALE` | `1.0` | Multiplies the per-operation timeouts of `protocol.py` |
| `ACLOPI_JVM_ARGS` | `-Xmx768m` | JVM arguments of each worker |
| `ACLOPI_WORK_DIR` | `results/workers` | Working folder of the pool and of the lock |
| `ACLOPI_LOG_LEVEL` | `INFO` | Log level |
| `ACLOPI_MAX_FAST_RUNS` | `1` | Simultaneous fast runs (raise it, e.g. to 4, for experiments without live users) |
| `ACLOPI_LIVE_UPDATE_MS` | `100` | Target interval between live-mode blocks |
| `ACLOPI_FAST_BLOCK_TICKS` | `1000` | Ticks per fast-mode block |
| `ACLOPI_FAST_YIELD` | `0` | Pause between fast blocks, as a fraction of the block's time |
| `ACLOPI_WS_QUEUE` | `32` | Queued messages per WebSocket client before resynchronising it |
| `ACLOPI_OPTIMIZE_ROUNDS` | `2` | Optimize order: rounds with the AI (replaces `ACLOPI_OPTIMIZE_ROUNDS_FULL`) |
| `ACLOPI_OPTIMIZE_MAX_PRODUCTS` | `50` | Optimize order: longest list (422 above) |
| `ACLOPI_OPTIMIZE_SEED` | `1` | Optimize order: fixed seed of every estimate (not the session's) |
| `ACLOPI_OPTIMIZE_BLOCK_WHEN_LIVE_AGENT` | `1` | Optimize order: provisional rule, refused while live agent sessions run (`0` removes it) |
| `ACLOPI_OPTIMIZE_MAX_WAIT_S` | `300` | Optimize order: total wait for a turn at the AI (429) before failing |
| `ACLOPI_OPTIMIZE_AI_TIMEOUT_S` | `90` | Optimize order: timeout of each `POST /sequence/propose` |

## Logs

Each line is a JSON object on stderr with `ts`, `level`, `logger`, `msg` and `session_id`. Depending on the case, they also carry `worker`, `method`, `path`, `status_code`, `elapsed_ms` or `phase`. How to read them: `docs/records/logs.md`.

- **API:** the `session_id` comes from the route or, when the session is created, from the new session.
- **Workers:** they also write JSON, with their name in `worker` and the `session_id` of their last setup.
- **Health:** the access lines of `/health*` go at DEBUG level, so that the load balancer's polling does not flood the log.
- **General lines** (startup, shutdown): they carry `session_id: null`.
