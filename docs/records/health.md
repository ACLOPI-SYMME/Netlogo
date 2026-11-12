# Platform health

[← Index and glossary](README.md)

## What it is

Three queries to know whether the platform is alive and ready: `/health/live` (does the process answer?), `/health/ready` (can sessions be created?) and `/health` (the detail: workers, sessions and agent). Docker and the cloud use them to restart the platform or route traffic to it, and they help with diagnosis.

## How it is produced and when it is available

Always, computed at the moment of each query. Not stored. The page queries `/health` every 10 s to show the "The agent is not available" warning.

## How to see it

| Query | Answers | HTTP code |
|---|---|---|
| `GET /health/live` | `{"status": "alive"}` | Always 200 if the process answers |
| `GET /health/ready` | `{"status": "<state>"}` | 200 if `ready` or `degraded`; 503 if `starting`, `failed` or `stopping` |
| `GET /health` | The detail (below) | Always 200 |

## Fields of `GET /health`

| Field | Meaning | Unit | Values |
|---|---|---|---|
| `status` | Overall state | — | `starting` (loading the models, about 70 s), `ready`, `degraded` (some worker is down), `failed`, `stopping` |
| `uptime_s` | Time since the API started | s | — |
| `startup_s` | How long it took to be ready | s | `null` while starting |
| `sessions.active`, `sessions.max` | Open sessions and maximum (= session workers) | count | — |
| `workers[]` | Per worker: `slot` (number), `role` (`session` or `whatif`), `ready`, `state` (`starting`, `free`, `busy`, `restarting`, `failed`, `stopped`), `pid`, `rss_mib` (memory, MiB), `restarts` (times it was restarted), `session_id` (session it serves) | — | — |
| `agent` | State of the agent. **Does not affect `/health/ready`** | — | see below |

Fields of `agent`:

| Field | Meaning | Values |
|---|---|---|
| `configured` | Whether an agent is configured (`ACLOPI_AGENT_URL`) | `true`, `false` |
| `kind` | Which agent: deduced from the host of the configured URL (`agent-mock` → `mock`, `agent` → `real`, any other → `other`; `docs/deploy-local.md`) | `mock`, `real`, `other`, `null` without agent |
| `url` | The agent's URL (`ACLOPI_AGENT_URL`) | text, or `null` |
| `status` | Whether it answers | `ok`, `down`, `unknown` (not tested yet), `not_configured` |
| `last_check`, `last_ok` | Last check and last time it answered well | Unix time (s) |
| `last_error` | Last error | text or `null` |
| `decide_sent`, `decide_failed` | `/decide` requests sent and failed since startup | count |

## Real example

Right after starting (2 session workers and 2 what-if workers):

```json
{"status": "ready", "uptime_s": 71.7, "startup_s": 70.46, "sessions": {"active": 0, "max": 2},
 "agent": {"configured": true, "status": "ok", "last_check": 1794220312.13, "last_ok": 1794220312.13,
           "last_error": null, "decide_sent": 0, "decide_failed": 0},
 "workers": [{"slot": 0, "role": "session", "ready": true, "state": "free", "pid": 6580, "rss_mib": 358.6,
              "restarts": 0, "session_id": null},
             {"slot": 2, "role": "whatif", "ready": true, "state": "free", "pid": 26080, "rss_mib": 498.4,
              "restarts": 0, "session_id": null}, "…"]}
```

**Reading:** the platform is ready (`ready`) and took 70 s to start. There are no open sessions out of 2 possible. The agent answers (`ok`). Each worker uses between 360 and 500 MiB and none was restarted.

## Pitfalls

- **`ready` does not guarantee there is room:** if `sessions.active` = `sessions.max`, creating a session answers 503.
- **The agent being down does not take the platform out of `ready`:** it shows as `agent.status: down`. In that state, fast runs with rule 4 cannot start and in live runs rule 3 decides.
- **`restarts` above 0** means a worker crashed or hung; the session it had became `lost`.
- The default configuration has 5 session workers and 2 what-if workers; the example used fewer.
