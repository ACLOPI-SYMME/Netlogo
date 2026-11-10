# WebSocket messages

[← Index and glossary](README.md)

## What it is

An open channel between the platform and whoever is watching a session (the `/ui` page, or any program). Everything that happens arrives through it in real time: the plant advancing, the events, the KPIs, the agent's decisions and the state changes. The design (order, queues, closing) is in `docs/websocket.md`; this page explains how to read each message.

## How it is produced and when it is available

- Only **while the session exists**. Nothing that goes through here is stored as such: if nobody was connected, it is lost (except what also goes to the saved run).
- On connecting, a full picture (`snapshot`) arrives first; then the news.
- The client sends nothing; everything is controlled over HTTP.

## How to see it

- Connect to `ws://<host>:8000/ws/sessions/{session_id}` (for example with the Python `websockets` library).
- The `/ui` page uses it for everything it shows in the Visualization tab.

## The messages, in the order they usually arrive

| Type | When it arrives | Carries `seq` |
|---|---|---|
| `snapshot` | On connecting, and after a `resync` | yes (the last one included) |
| `run_state` | Every time the run's state changes | yes |
| `tick` | Live: one block every ~100 ms. Also after a manual `step` | yes |
| `progress` | Fast: one block (1,000 ticks, or fewer if it stops at a decision) | yes |
| `decision` | Every time an agent decision arrives (applied or late) | yes |
| `finished` | When the run ends (horizon or set finished) | yes |
| `run_error` | If a block fails inside NetLogo | yes |
| `resync` | If the client fell behind and messages were dropped, or after a reset | no |
| `heartbeat` | If 5 s went by without any other message | no |
| `closed` | When the session is closed (or does not exist); then the connection is cut | no |
| `scenario_event` | **No longer sent** (scenarios not available, see [scenarios.md](scenarios.md)) | — |

`seq` is a number that increases per session and is the same for every client. A jump in `seq` means messages were lost (it only happens right before a `resync`). Careful: in the `decision` message, `seq` is this number, **not** the operation ([decisions.md](decisions.md#pitfalls)).

## Fields by type

**`snapshot`**

| Field | Meaning |
|---|---|
| `tick` | Current tick of the session |
| `session` | The session information, same as `GET /sessions/{id}` ([sessions-and-state.md](sessions-and-state.md)) |
| `layout` | The plant geometry, same as `GET /sessions/{id}/layout` |
| `state`, `state_tick` | The plant snapshot and its tick. They may be missing (for example, in fast mode) or be a few ticks old |
| `kpis` | The last KPIs computed ([kpis.md](kpis.md)) |
| `recent_events` | The last 500 events ([events.md](events.md)) |
| `scenario`, `scenario_events` | Always `{"id": "S0", "params": {}}` and `[]` |

**`run_state`**

| Field | Meaning | Values |
|---|---|---|
| `run_state` | State of the run | `idle` (not running), `running_live`, `running_fast`, `waiting_decision` (fast, waiting for the agent), `paused`, `finished`, `failed` |
| `mode`, `speed` | Mode and speed of the current or paused run | `live`/`fast`; 0.5, 1, 2, 4; `null` when not running |
| `reason` | Why it ended or failed | `horizon`, `all_products_done`, `agent_unavailable`, or `null` |
| `pending_decisions` | Decisions the run is waiting for | count |
| `tick` | Tick of the change | ticks |

**`tick`** (live mode)

| Field | Meaning | Unit |
|---|---|---|
| `source` | `run` in a run; `step` in a manual advance | — |
| `tick`, `advanced` | Tick at the end of the block and how many it advanced (at 1×: 3) | ticks |
| `speed` | Speed | 0.5 / 1 / 2 / 4 |
| `rate` | Ticks per second measured over the last second; compare with 32 × speed | ticks/s |
| `lag_ms` | How late the block was compared with its planned time | real ms |
| `events` | New events of the block | — |
| `kpis` | KPIs; only ~once per second (missing in the other blocks) | — |
| `state` | Plant snapshot, to draw it | — |

**`progress`** (fast mode)

| Field | Meaning | Unit |
|---|---|---|
| `tick`, `advanced` | Tick at the end of the block and how many it advanced | ticks |
| `finished_products` | Products finished so far | count |
| `ticks_per_s` | Measured speed of the fast run | ticks/s |
| `block_ms` | How long the block took | real ms |
| `events`, `kpis`, `state` | Same as in `tick` (`state` at most once per second) | — |

**`decision`**: `product`, `product_type`, `seq_op`, `operation`, `machine`, `level`, `reason`, `late`, `latency_ms`, `tick`. Same meanings as in [decisions.md](decisions.md) (here `level` = `decision_level`).

**`finished`**: `tick`, `reason` (`horizon` or `all_products_done`), `kpis` (the final ones). A `run_state` with `finished` follows.

**`run_error`**: `error` (the error text). The run goes to `idle`.

**`resync`**: `reason` (`client_too_slow`: the client's queue filled up; `reset`: the session went back to tick 0) and `dropped` (messages dropped). A `snapshot` follows.

**`heartbeat`**: `server_time` (the server's Unix time).

**`closed`**: `code` and `reason`. `code` is `session_lost` (the worker crashed), `session_expired` (inactivity), `session_deleted` (deleted), `session_not_found`, `platform_starting` or `server_shutdown`.

## Real example

Live run at 1× (excerpt; `state` and `kpis` left out):

```json
{"type": "run_state", "seq": 1, "run_state": "running_live", "mode": "live", "speed": 1.0,
 "reason": null, "pending_decisions": 0, "tick": 0}
{"type": "tick", "seq": 2, "source": "run", "tick": 3, "advanced": 3, "speed": 1.0, "rate": null,
 "lag_ms": 15.0, "events": [], "kpis": {"…": "…"}, "state": {"…": "…"}}
{"type": "decision", "seq": 139, "product": 200, "product_type": "T", "seq_op": 1, "operation": "O1",
 "machine": "M2", "level": "llm", "reason": "mock llm: best finish", "late": false, "latency_ms": 1282.0, "tick": 411}
{"type": "run_state", "seq": 217, "run_state": "paused", "mode": "live", "speed": 1.0, "tick": 642, "…": "…"}
{"type": "closed", "code": "session_deleted", "reason": "the session was closed (DELETE)"}
```

Fast run with decisions:

```json
{"type": "progress", "seq": 2, "tick": 367, "advanced": 367, "finished_products": 0, "ticks_per_s": null,
 "block_ms": 453.0, "events": [{"tick": 366, "event": "ProductEntersMachine", "…": "…"}], "kpis": {"…": "…"}}
{"type": "run_state", "seq": 3, "run_state": "waiting_decision", "pending_decisions": 1, "tick": 367, "…": "…"}
{"type": "run_state", "seq": 4, "run_state": "running_fast", "pending_decisions": 0, "tick": 367, "…": "…"}
{"type": "decision", "seq": 5, "product": 200, "machine": "M2", "level": "code-obvious", "tick": 367, "…": "…"}
{"type": "finished", "seq": 129, "tick": 10635, "reason": "all_products_done", "kpis": {"finished": 5, "…": "…"}}
```

**Line-by-line reading of the live `tick`:**
- `seq: 2`: second message of the session (number 1 was the `run_state`).
- `source: run`: it comes from a run, not from a manual advance.
- `tick: 3`, `advanced: 3`: the block advanced 3 ticks and the plant is now at tick 3.
- `rate: null`: there is not one second of history to measure yet. In the following blocks it is ~32 (for example, 31.98).
- `lag_ms: 15`: the block went out 15 ms after its planned time.
- `events: []`: nothing happened in those 3 ticks.

## Useful calculations

- **Real speed in live mode** = `rate`; it should be around 32 × `speed`.
- **Messages per second** in live mode: ~10.7 (`tick` every ~94 ms at 1×). In the example: 214 `tick` in ~20 s.
- **Time the fast run spent waiting for the agent:** between each `run_state` `waiting_decision` and the next `running_fast`.
- **`run_state` messages in fast mode with rule 4:** two per decision (wait and resume). In the example, 64 for 31 decisions.

## Pitfalls

- **In fast mode with decisions, blocks are not 1,000 ticks:** they stop at each decision (`advanced` 367, 645, 38…).
- **`ticks_per_s` is usually `null` in fast mode with decisions:** each decision restarts the speed measurement.
- **`kpis` does not come in every `tick`:** only ~once per second. Use the last one received.
- **The resume `run_state` arrives before the `decision`** of the same decision (in the example, `seq` 4 and 5): the run has already moved on when the decision is published.
- **After a `resync`, replace everything** (state and event list) with the following `snapshot`.
- **A client that connects late does not receive earlier decisions**: the `snapshot` does not carry them. They are in the metrics and, at the end, in the saved run.
