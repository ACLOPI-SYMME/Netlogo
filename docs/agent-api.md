# Platform ↔ agent contract (L5.5)

**Agreed with Línea A on 4 Nov.** The code is in `aclopi/contracts/agent.py`. The API, the mock agent (`aclopi/agent_mock/`) and the agent (`aclopi/agent/`) implement it.

## When the agent is called

With **rule 4**, when a product **enters** a machine and its next operation has several possible machines, the model leaves a request in `decision-queue` (`docs/rule4-decision-hook.md`). With only one possible machine there is no request, and the record marks it as `single-option`.

- **The platform always calls the agent** if the session has `strategy` = `b1`, `b1b` or `agent`. The filter for obvious cases lives inside the agent.
- **`strategy: "none"`** is rule 4 without a decider (equal to rule 3): nobody is called. Tests only.
- With rule 4 and no `strategy`, the session uses `agent`. `b1`, `b1b` and `none` are not user options (see `docs/api.md`).

## Platform → agent: `POST {ACLOPI_AGENT_URL}/decide`

```json
{"session_id": "…", "product": 201, "seq": 1, "strategy": "agent", "mode": "live",
 "ticks_per_second": 32.0, "tick": 1011, "simulated_time": 313.41,
 "operation": "O1", "origin": "M1", "candidates": ["M2", "M3", "M5", "M7"],
 "context_tick": 1012, "product_type": "E", "priority": 80, "current_machine": "M1", "current_operation": "O8", "own_remaining": 30.7,
 "next_operation": "O2", "pending_operations": ["O1", "O2", "O9"],
 "products_in_plant": 6, "m1": {"busy": true, "remaining": 30.7, "queue_length": 2}}
```

| Field | Meaning |
|---|---|
| `mode` | `live` or `fast` |
| `ticks_per_second` | 32 × live speed; `null` in fast mode, where the run waits |
| `tick`, `simulated_time` | Moment of the request, which is the entry to the machine |
| `operation`, `origin`, `candidates` | Operation to decide (`seq`), machine where it is and capable machines |
| `context_tick` | Tick of the state the context was read from. In fast mode it is the end of the `go` in which the request was made (`tick` or `tick + 1`, because `ticks` advances at the end of the `go`); live, the end of the block that collected it (it can be a little later) |
| `product_type`, `priority` | Type of the product (`A`, `I`, `P`, `B`, `E`, `L` or `T`) and its priority (60–100, model variable `priority`). The priority is read with a separate reporter at the same moment, because `platform-state` does not carry it |
| `current_machine` | Machine processing the product (`null` if it already left it) |
| `current_operation` | Operation in process (`seq − 1`) |
| `own_remaining` | What is left of the operation in process, in u.t. (0 if it is no longer in a machine) |
| `next_operation` | Operation `seq + 1`, the one after the one being decided (`null` if `seq` is the last). Same as in `candidates` |
| `pending_operations` | Operations from `seq` on, in order; the first is the one being decided |
| `products_in_plant` | Live products in the plant |
| `m1` | `busy`, `remaining` (u.t. left of its job; 0 if idle) and `queue_length` of M1 (O8/O9, which every product goes through) |

**Context.** The session's worker reads it at the same moment it collects the request, from **a single** `platform-state`. It consumes no randomness and does not alter the run. Times are in u.t. (1 tick = 0.31 u.t.).

- **Expected response:** an immediate **202**. The agent decides afterwards.
- **If it fails or takes more than 2 s** (`ACLOPI_AGENT_DECIDE_TIMEOUT_S`), it is logged and **not retried**:
  - live, the model applies rule 3 when the machine finishes (`rule3-fallback`);
  - fast, the run waits; see "Fast mode".

## Agent → platform: `POST /sessions/{id}/next-machine`

```json
{"product": 201, "seq": 1, "machine": "M3", "decision_level": "llm",
 "reason": "short text", "latencies": {"total_ms": 3400, "llm_ms": [3100]}}
```

- **`decision_level`:** `code-obvious`, `code-fallback`, `llm`, `llm-what-if` or `heuristic`.
- **`latencies`:** optional. Fields `total_ms`, `llm_ms` (one per LLM call) and `what_if_ms`; other extras are kept too.
- **Application:** applied in the worker with `platform-set-next-machine`, between blocks.

| Response | When |
|---|---|
| 200 `{"applied": true, "tick", "late": false, "run_state", "pending_decisions"}` | It was applied |
| 409 `decision_not_pending` | The seq is old or no longer pending (for example, the product finished the operation). It is recorded as **late** |
| 422 `invalid_option` | Machine not capable or unknown. A machine outside M1–M7 is rejected when validating the body |
| 409 `rule4_required` | The session is not rule 4 |

## Agent → platform: data to decide

- `GET /sessions/{id}/candidates?product=&seq=`. The response is Línea A's `CandidatesResult` (`aclopi/contracts/candidates.py`; fields in `docs/agent-status.md`), see `docs/whatif.md`.
- `POST /sessions/{id}/what-if` (see `docs/whatif.md`).

## Shared token

- **When `ACLOPI_AGENT_TOKEN` is set:** `next-machine`, `candidates` and `what-if` require `Authorization: Bearer <token>`, and answer 401 if it is missing or does not match. The comparison is constant-time (`secrets.compare_digest`, in `aclopi.contracts.agent.bearer_matches`), in the platform and in the mock agent. The platform sends the same header on `/decide` and `/health`.
- **Without the variable (development):** it is not required.
- **Logs:** the token is never written.

## Health: `GET {ACLOPI_AGENT_URL}/health`

- **Check:** the API makes it every 30 s (`ACLOPI_AGENT_HEALTH_INTERVAL_S`). A 200 is `ok`; any other response or a 2 s timeout is `down`.
- **Where it shows:** in `GET /health`, field `agent`. It **does not affect** `/health/ready`.
- **Sessions with `b1`, `b1b` or `agent` and the agent down:**
  - `POST /sessions` is allowed, with `warnings: ["agent_unavailable"]`;
  - `POST /run` **live** is allowed;
  - `POST /run` **fast** answers **503 `agent_unavailable`**. The strategy is fixed when the session is created, but the mode only when running, which is why the rejection is on `POST /run`.

## Live mode

- **Collecting requests:** after each block, the worker reads and empties `decision-queue` and delivers the requests with the block's message.
- **Sending:** the API calls `/decide` without waiting for the response (asynchronous client), so the pace of 32 ticks/s does not change.
- **No pause:** the simulation never stops. If the agent does not answer in time, the model applies rule 3 when the machine finishes, and the platform counts it as `rule3-fallback`.

## Fast mode

- **Advancing:** the worker advances with `platform-run-until-decision` until there is a request or the block ends. With requests it goes to `waiting_decision`, which is a state and not a long request: it keeps serving requests and sends a heartbeat every 2 s.
- **Resuming:** it does not advance until it receives `next-machine` for **every** pending request, including those raised in the same tick.
- **Deadline:** controlled by the API. The 15 s watchdog only looks at the worker's activity, which keeps sending heartbeats, so waiting for the agent does not count as a hang.
- **No answer within `ACLOPI_FAST_DECISION_TIMEOUT_S` (90 s):**
  - the run ends with `run_state: "failed"` and `reason: "agent_unavailable"`; it does **not** continue with rule 3;
  - the WebSocket sends `run_state` with that reason;
  - `/ui` shows "Agent not available: the run stopped".

## Record and metrics

- **Record per applied or late decision**, per session and in memory: tick, request tick, product, seq, strategy, level, machine, reason, latency (from `/decide` to `next-machine`) and whether it was late. How to read it: `docs/records/decisions.md`.
- **`Decision.Source` of each assignment of the model** (`agent`, `rule3-fallback`, `single-option`): it comes from the `decision-log` the worker reads after each block.
- **`GET /sessions/{id}/metrics` → `decisions`:**
  - applied, late and unanswered;
  - count and % per level;
  - `sources`;
  - `rule3_fallback_pct`, only over the assignments with several machines (`agent` + `rule3-fallback`);
  - `single_option`;
  - mean, p95 and maximum latency;
  - `log`.
- **WebSocket:** `decision` message, see `docs/websocket.md`.

## Mock agent (`python -m aclopi.agent_mock`, port 8100)

| Strategy | Behaviour |
|---|---|
| `b1` / `b1b` | Answers at once with the best candidate by `finish`. `b1b` uses `finish_plus_next` if present, `finish` otherwise. Level `heuristic` |
| `agent` | Level drawn with configurable weights (`ACLOPI_MOCK_FRACTIONS`; by default `code-obvious` 0.5, `llm` 0.3, `llm-what-if` 0.15, `code-fallback` 0.05) |

Levels of `agent`:

| Level | What it does |
|---|---|
| `code-obvious` | Immediate |
| `llm` | Waits 3–4 s (`ACLOPI_MOCK_LLM_DELAY_S`) |
| `llm-what-if` | Waits ~3 s, asks for a what-if with the 2 best by `finish` (`budget_ms` 10000 live and 15000 fast), waits ~1.5 s and picks the one with the lowest `op_end_time`. Live, if `own_remaining` in seconds minus 2 s does not reach ~12 s, it decides as `llm`. If the what-if answers `skipped` or `timeout`, it decides without it |
| `code-fallback` | The best by `finish` |

Other options: `ACLOPI_MOCK_DOWN=decide|health|all` so that those endpoints do not answer, and `ACLOPI_MOCK_SEED` to make its draws reproducible.

## Variables

| Variable | Default | |
|---|---|---|
| `ACLOPI_AGENT_URL` | – | URL of the agent; without it, the strategies with a decider have nobody to call |
| `ACLOPI_AGENT_TOKEN` | – | Shared token |
| `ACLOPI_AGENT_DECIDE_TIMEOUT_S` | 2 | Maximum time of `/decide` and `/health` |
| `ACLOPI_AGENT_HEALTH_INTERVAL_S` | 30 | How often `/health` is checked |
| `ACLOPI_FAST_DECISION_TIMEOUT_S` | 90 | Maximum wait of a fast run for its decisions |
