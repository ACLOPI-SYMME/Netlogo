# Session WebSocket (L5.3)

`ws://<host>:<port>/ws/sessions/{session_id}`

Streams in real time what happens in a session. It is what the web interface consumes.

- **Control over HTTP.** The client **sends nothing**: creating, running, pausing or resetting the session is done with the HTTP API (`docs/api.md`). Anything it sends is ignored.
- **Several clients.** They can watch the same session at the same time and receive exactly the same messages.
- **Disconnecting.** Disconnecting does not affect the run.

The test page `GET /ui` uses everything described here. How to read each field: `docs/records/websocket.md`.

## Order of the messages

1. **First, always `snapshot`:** a full picture of the session.
2. **Then the updates** (`tick`, `progress`, `decision`, `run_state`, `finished`, `run_error`), all after the picture.
3. **If the client falls behind** (see "Slow client"): `resync` and then a new `snapshot`.
4. **If there was nothing to send for 5 s:** `heartbeat`.
5. **When the session closes:** `closed` with the reason, and the server closes the connection.

Every message is a JSON object with `type`. Those published by the session (`tick`, `progress`, `decision`, `run_state`, `finished`, `run_error`) also carry `seq`, increasing per session and the same for every client. A jump in `seq` means the client lost messages, which only happens before a `resync`. `snapshot.seq` is the last `seq` the picture already includes.

## Messages

### `snapshot`

```json
{"type": "snapshot", "seq": 41, "tick": 1290, "state_tick": 1290,
 "session": { ...SessionInfo, same as GET /sessions/{id}... },
 "layout": { ...platform-layout, same as GET /sessions/{id}/layout... },
 "state": { ...platform-state, same as GET /sessions/{id}/state... },
 "kpis": { ...same as GET /sessions/{id}/kpis... },
 "recent_events": [ {"tick": 1288, "event": "...", "who": 230, ...}, ... ],
 "scenario": {"id": "S0", "params": {}},
 "scenario_events": []}
```

- **`scenario` and `scenario_events`:** scenarios are not available on the platform (`docs/scenarios.md`): they are always S0 and `[]`. They are kept for compatibility.
- **`recent_events`:** the session's last 500 events (since the last `reset`). The client replaces its list with these.
- **`state` and `state_tick`:** they only come if a state is known. In fast mode the state is not always streamed, so they can be missing or older than `tick`.
- **`kpis`:** the last ones computed (at most ~1 s old during a run).

### `tick`: live-mode block, or manual step with clients watching

```json
{"type": "tick", "seq": 42, "source": "run", "tick": 1293, "advanced": 3, "speed": 1.0,
 "rate": 32.1, "lag_ms": 2.4,
 "events": [ {"tick": 1291, "event": "...", ...} ],
 "kpis": { ... },
 "state": { ...platform-state... }}
```

- **Cadence:** live there is a `tick` every ~100 ms, with `advanced` ticks (speed 1×: 3 ticks every 94 ms).
- **`source`:** `"run"` in a run and `"step"` in a manual `POST /step`. The manual step carries no `rate`, `lag_ms`, `speed` nor `kpis`, and its `events` is empty: the events of a manual step arrive in the next run block, or through `GET /events`.
- **`rate`:** ticks/s measured over the last second, to compare with 32 × speed.
- **`lag_ms`:** how late this block was compared with its planned time. If the worker falls more than 1 s behind, it resumes the pace from that moment instead of speeding up to catch up.
- **`events`:** the **new** events of the block (event-buffer), without repeats.
- **`kpis`:** comes about once per second, and always in the last block.

Format of an event:

```json
{"tick": 1291, "event": "...", "who": 230, "product_type": "...", "location": "...",
 "operation": "...", "next_operation": "...", "destination": "...", "time": 400.21}
```

### `progress`: fast-mode block

```json
{"type": "progress", "seq": 90, "tick": 23000, "advanced": 1000, "finished_products": 12,
 "ticks_per_s": 2150.4, "block_ms": 465.0,
 "events": [ ...the block's events... ],
 "kpis": { ... }}
```

- **Cadence:** one message per block of `ACLOPI_FAST_BLOCK_TICKS` ticks (1000 by default).
- **`state` at most once per second** (L5.4), and always in the last block. With it the `/ui` canvas shows the fast run as a sped-up video. If a block takes more than 1 s, every block carries `state`.
- **`events`:** **all** of them arrive, in a batch (~18 events per 1000 ticks). The API also keeps them for the L5.6 persistence.
- **`kpis`:** comes about once per second.

### `scenario_event`: no longer sent

Scenarios are not available on the platform (`docs/scenarios.md`), so no session publishes this message. Its format remains described in `docs/scenarios.md` for the experiments.

### `run_state`: change of the run's state

```json
{"type": "run_state", "seq": 43, "run_state": "paused", "mode": "live", "speed": 1.0, "tick": 1293}
```

- **States:** `run_state` is `idle`, `running_live`, `running_fast`, `waiting_decision` (fast with a decider, waiting for the agent), `paused`, `finished` or `failed`.
- **`reason`:** why it ended, for example `agent_unavailable` in `failed`. `pending_decisions` says how many decisions are awaited.
- **`mode` and `speed`:** those of the current or paused run, and `null` in `idle` and `finished`. A live run's speed can be changed while it runs (`POST /run` with the new speed); a new `run_state` reports it.

### `decision`: an agent decision was applied (or arrived late) (L5.5)

```json
{"type": "decision", "seq": 61, "product": 201, "product_type": "A", "seq_op": 1, "operation": "O2",
 "machine": "M3", "level": "llm", "reason": "M3 finishes before M5", "late": false, "latency_ms": 3412.0,
 "tick": 1113}
```

- `product_type` and `operation` (the operation decided) come from the request sent to the agent; `reason` is the reason the agent gave (it can be `null`).
- The page uses it for the "Latest decisions" panel (the 50 newest on top, with a level filter).
- The aggregated metrics are in `GET /sessions/{id}/metrics` (`decisions`). Note: the message's `seq` field is the WebSocket message number, and the `seq` of the decided operation goes in **`seq_op`**.

### `finished`: the run reached the horizon

```json
{"type": "finished", "seq": 120, "tick": 10000, "reason": "horizon", "kpis": { ...final KPIs... }}
```

`reason` is `horizon`, or `all_products_done` with a product set (L5.6). A `run_state` with `finished` and the same `reason` follows.

### `run_error`: a block failed inside NetLogo

```json
{"type": "run_error", "seq": 77, "error": "NetLogoException: ..."}
```

The run stops (`run_state` goes to `idle`) and the worker stays alive.

### `resync`: the client lost messages

```json
{"type": "resync", "reason": "client_too_slow", "dropped": 33}
```

A `snapshot` follows **immediately**, and the client must replace its state and its list of events.

| `reason` | When it happens |
|---|---|
| `client_too_slow` | The client's queue filled up (see below) |
| `reset` | The session was reset with `POST /reset` and goes back to tick 0 |

### `heartbeat`

```json
{"type": "heartbeat", "server_time": 1793098812.123}
```

Sent if there was no other message in 5 s, for example with the session `idle` or `paused`. If a client receives nothing for ~15 s, it should consider the connection lost and reconnect. The browser does not see protocol pings; the server uses them to detect dead clients (every 10 s, with a 10 s timeout).

### `closed`: the session ended for this client

```json
{"type": "closed", "code": "session_lost", "reason": "worker process exited unexpectedly (exit code 1)"}
```

Then the server closes the connection with this code:

| `code` | Close code | When |
|---|---|---|
| `session_lost` | 4410 | The worker crashed or hung. `GET /sessions/{id}` shows the reason and the other endpoints answer 410 |
| `session_expired` | 4410 | The session was closed for inactivity |
| `session_deleted` | 4404 | Deleted with `DELETE /sessions/{id}` |
| `session_not_found` | 4404 | The id does not exist, for example when connecting |
| `platform_starting` | 4503 | The platform is still starting |
| `server_shutdown` | 1001 | The API is shutting down |

When connecting to a session that is already lost, expired or does not exist, the client only receives the `closed`.

## Slow client

- **Separate queues.** Each client has its own queue of `ACLOPI_WS_QUEUE` messages (32 by default) and its own sending task. The worker and the other clients never wait for a client.
- **If the queue fills up:** the queued messages are dropped, since they are intermediate states and not needed, and the client receives `resync` and a `snapshot` with the latest state and the last 500 events. That way it recovers the events it did not receive.
- **If a send does not complete in 10 s:** that client's connection is closed.

## Sizes and bandwidth (measured)

See `results/l5/bench_live.json`:

Measured in the container, with rule 3, Stochastic and 60 s at 1×:

| Message | Mean size |
|---|---|
| `tick` | ~2.8 KB |
| `snapshot` | ~15.8 KB (with the layout) |
| `progress` | ~3.3 KB (with events and KPIs) |
| `run_state` | ~90 B |
| `finished` | ~370 B |

A live session at 1× uses **~27–28 KB/s per client**, about 10.7 messages per second. A fast run uses ~5 KB/s.
