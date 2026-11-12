# Process logs

[← Index and glossary](README.md)

## What it is

The messages the programs write while they work: HTTP requests received, sessions created, runs saved, errors. They are used to diagnose problems (why was a session lost?, what did the agent ask for?). They are not simulation data.

## How it is produced and when it is available

- Each process writes **one JSON line per message** to its error output (*stderr*): the API, each worker, the mock agent and the real agent.
- Available **as long as the container exists** (Docker keeps what the process wrote). They are not stored in the database.

## How to see it

With Docker Compose (`docs/deploy-local.md`):

```powershell
docker compose logs platform          # the API and its workers
docker compose logs agent-mock        # the mock agent
docker compose logs agent             # the real agent ("agent" profile)
docker compose logs -f platform       # follow live
```

**Filter by session** (lines about a session carry its `session_id`):

```powershell
docker compose logs --no-log-prefix platform | Select-String '"session_id": "34cf16b45b8745feaedba86430dcc617"'
```

For a finer analysis, save the log to a file and read it line by line as JSON (for example with Python or `jq`).

## Fields of a line

| Field | Meaning | Always | Values |
|---|---|---|---|
| `ts` | Time of the message | yes | UTC date and time with milliseconds (ISO 8601) |
| `level` | Severity | yes | `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL` |
| `logger` | Part of the program that wrote it | yes | for example `aclopi.api.app` (HTTP requests), `aclopi.api.registry` (sessions and runs), `aclopi.api.ws` (WebSocket), `aclopi.workers.worker`, `aclopi.workers.pool`, `aclopi.sim.session` (the model), `uvicorn.error` (the web server), `httpx` (outgoing calls, for example to the agent) |
| `msg` | The message | yes | text |
| `session_id` | Session it refers to | yes (may be `null`) | 32 hexadecimal characters |
| `service` | Which service it is | agents only | `agent`, `agent-mock` |
| `worker` | Which worker (in its own lines: `session0[g0]` = session worker 0, generation 0; the generation goes up with each restart) | sometimes | — |
| `method`, `path`, `status_code`, `elapsed_ms` | In HTTP requests: method, path, response code and duration (ms) | in `aclopi.api.app` | — |
| `op`, `client`, `phase` | Worker operation, client, startup phase | sometimes | — |
| `exc` | Technical detail of an error (*traceback*) | errors only | text |

## Real example

When the session of the fast run was created (four consecutive lines):

```json
{"ts": "2026-11-09T10:31:52.465+00:00", "level": "INFO", "logger": "aclopi.workers.worker", "msg": "setup seed=42 rule=4 modeling_type=Stochastic horizon_ticks=20000 scenario=S0 (0 events)", "session_id": "34cf16b45b8745feaedba86430dcc617", "worker": "session0[g0]"}
{"ts": "2026-11-09T10:31:52.474+00:00", "level": "INFO", "logger": "aclopi.api.registry", "msg": "Session created on worker session0", "session_id": "34cf16b45b8745feaedba86430dcc617", "worker": "session0"}
{"ts": "2026-11-09T10:31:52.475+00:00", "level": "INFO", "logger": "aclopi.api.app", "msg": "POST /sessions 201", "session_id": "34cf16b45b8745feaedba86430dcc617", "method": "POST", "path": "/sessions", "status_code": 201, "elapsed_ms": 160.96}
{"ts": "2026-11-09T10:31:52.486+00:00", "level": "INFO", "logger": "uvicorn.error", "msg": "127.0.0.1:59849 - \"WebSocket /ws/sessions/34cf16b45b8745feaedba86430dcc617\" [accepted]", "session_id": "34cf16b45b8745feaedba86430dcc617"}
```

**Line-by-line reading:**
1. Session worker 0 loaded the session in the model: seed 42, rule 4, horizon 20,000, no scenario.
2. The API registered the session on that worker.
3. The API answered the `POST /sessions` with 201 (created) in 161 ms.
4. A client (here, the examples script) connected to that session's WebSocket.

## Pitfalls

- **Times are in UTC**, not local time.
- **Many lines have no session** (`session_id: null`): startup, health, general requests.
- **`httpx` is very noisy**: in the example run it wrote 740 of 1,083 lines (every call to the agent and from the agent to the platform). Filtering by `logger` helps.
- **The agent token never appears in the logs.**
- **If the container is recreated, its previous logs are lost.**
