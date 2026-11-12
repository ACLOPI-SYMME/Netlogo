# Local deployment with Docker Compose (L5.7)

`docker-compose.yml`, at the root of the repo, defines these services on an internal network. **The platform always works with Línea A's real agent**; the mock agent is only for the automatic tests.

| Service | Image | What it is | Published port |
|---|---|---|---|
| `platform` | `aclopi-sim` (`docker/Dockerfile`, `CMD` = the API) | API, NetLogo workers and `/ui` | **8000** |
| `agent` (profile `agent`, **the default**) | `aclopi-agent` (`docker/agent.Dockerfile`) | Línea A's real agent | none |
| `agent-mock` (profile `mock`, only for tests) | `aclopi-sim`, with `python -m aclopi.agent_mock` | Mock agent (`docs/agent-api.md`) | none |
| `dynamodb-local` | `amazon/dynamodb-local:2.5.2` | Results and product sets, in memory | none |

## Prepare

```powershell
Copy-Item .env.example .env      # if it does not exist; then set ACLOPI_AGENT_TOKEN to a value of your own
```

- `.env` is not committed to git.
- Compose reads `ACLOPI_AGENT_TOKEN` from it and passes it to the platform and to the agent.
- The NetLogo paths in `.env` are only used on Windows; they do not matter inside the container.
- **Do not put `ACLOPI_AGENT_URL` in `.env`.** The `up` scripts set it for the agent they start. In `.env` it would apply to every start, whatever agent is running.
- **The real agent's settings** (LLM, triage) come from `.env.agent`, which is not in git (see `.env.agent.example`). Without that file the real agent uses its fake LLM.

## Start, watch, stop

Always use the scripts in `docker/`. They choose the agent and stop everything:

```powershell
.\docker\up.ps1                  # with Línea A's real agent (default): profile "agent"; its image is rebuilt
.\docker\up.ps1 -Agent mock      # with the mock agent (profile "mock"): only for automatic tests
docker compose ps                    # platform becomes "healthy" when /health/ready answers 200 (~1.5 min)
docker compose logs -f platform      # JSON logs; also agent-mock / agent and dynamodb-local
.\docker\down.ps1                # stops and removes EVERYTHING, the real agent included (DynamoDB Local is in memory: it is lost)
```

On Linux or macOS: `docker/up.sh [--agent real|mock]` and `docker/down.sh`.

What the scripts do:

| Script | Agent | What it runs |
|---|---|---|
| `up` (default: real) | `agent` | It first removes a mock agent left from an earlier start (`docker compose --profile mock rm --stop --force agent-mock`). Then `docker compose --profile agent up -d --build` with `ACLOPI_AGENT_URL=http://agent:8100` |
| `up -Agent mock` / `--agent mock` | `agent-mock` | It first removes a real agent left over (`docker compose --profile agent rm --stop --force agent`). Then `docker compose --profile mock up -d --build` with `ACLOPI_AGENT_URL=http://agent-mock:8100` |
| `down` | every one | `docker compose --profile "*" down --remove-orphans` |

**Which agent the platform talks to:** `GET /health` → `agent`. It shows:
- `kind`: `mock` or `real`, deduced from the host of the configured URL (`agent-mock` or `agent`; any other host gives `other`);
- `url`: the URL itself;
- `status`.

If Línea A adds `kind` to its own `/health`, it can be read from there instead of deduced from the URL.

### The profile trap

Both agents are in profiles (`agent` and `mock`), and a plain `docker compose up` starts neither of them. A plain `docker compose down` **ignores the services of profiles that are not active**: it neither stops nor removes them. This happened on 12 Nov, in this order:

1. `aclopi-agent-1` was left running after `down`, with the image of 9 Nov.
2. That image had no `POST /sequence/propose`.
3. Because `.env` had `ACLOPI_AGENT_URL=http://agent:8100`, the platform talked to it.
4. "Optimize order" ended with "the AI answered 404".

Before the fix, the service also had `restart: unless-stopped`, so Docker started it again every time Docker itself started. Now it has `restart: "no"`. And `down.ps1` / `down.sh` always use `--profile "*"`.

If an old agent might still be around: `docker ps -a --filter label=com.docker.compose.project=aclopi` lists everything of the project; `.\docker\down.ps1` removes it.

Test page: `http://localhost:8000/ui`. API: `http://localhost:8000/docs`.

## Platform variables in Compose

| Variable | Value | What for |
|---|---|---|
| `ACLOPI_AGENT_URL` | Set by `docker/up` for the agent it starts: `http://agent:8100` (real, also the default) or `http://agent-mock:8100` (mock, tests only) | Where the agent is. Not in `.env` |
| `ACLOPI_AGENT_TOKEN` | `.env` | Token shared with the agent (`Authorization: Bearer`) |
| `ACLOPI_DYNAMODB_ENDPOINT` | `http://dynamodb-local:8000` | Turns on the DynamoDB store (`aclopi/api/results.py`) |
| `ACLOPI_CREATE_TABLES` | `1` | Creates the tables at startup (local only; in the cloud the infrastructure creates them) |
| `ACLOPI_AWS_REGION` | `eu-north-1` | DynamoDB region (Stockholm). DynamoDB Local ignores it |
| `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` | `local` | DynamoDB Local accepts any value |

**Platform limits:** those of L4 (`cpus: 4`, `cpuset: 0-3`, `mem_limit: 6g`).

**Healthchecks:**
- `platform` uses `/health/ready`. The image's own `HEALTHCHECK` uses `/health/live`, and Compose replaces it.
- `agent` and `agent-mock` use their `/health`.

**Restart:** `restart: unless-stopped` for `platform`, `agent-mock` and `dynamodb-local`; `restart: "no"` for the real `agent`, so that an old agent never comes back on its own. If DynamoDB Local does not accept connections yet when the platform starts, the startup fails and Docker restarts it.

## Tables (prefix `aclopi_`)

| Table | Key | Content |
|---|---|---|
| `aclopi_runs` | `run_id` | One per run: state (`finished`, `failed` or `stopped`), reason, rule, strategy, seed and its origin, horizon, mode, set (id, hash and copy of the list), KPIs, decisions summary and what-if summary |
| `aclopi_decisions` | `run_id` + `seq` | The decisions of the run, written in a batch at the end. The operation's seq goes in `seq_op` |
| `aclopi_product_sets` | `id` | Product sets |

- **When a run is saved:** when it finishes, fails or is stopped. Stopped means `DELETE`, `reset`, inactivity or loss of the worker.
- **If DynamoDB fails:** the error is written to the log and the run is not affected.

Queries: `GET /runs` (filters `seed`, `strategy`, `rule`, `product_set_id`; paging with `cursor`), `GET /runs/{id}` and `GET /runs/{id}/decisions`. The "History Logs" tab of `/ui` shows them, with Repeat, Compare and CSV export. How to read each field: `docs/records/README.md`.

## Test

```powershell
python scripts\l5\smoke_compose.py                    # with the stack up; uses ACLOPI_AGENT_TOKEN from the environment or from .env
python scripts\l5\smoke_compose.py --up mock --down   # starts it with the mock agent (explicitly: tests use the mock), tests, and stops everything
```

The script:
1. uploads a CSV of 8 products, saves it as a set and runs rule 4 with `b1` in fast mode, without a seed. It checks `all_products_done`, the makespan, the decisions, that the random seed was kept and that the run is in DynamoDB Local (`/runs`);
2. runs rule 4 with `agent` live for 30 s. It checks the decisions through the WebSocket and the pace of ~32 ticks/s;
3. checks that `/health` shows the agent, its `kind` and its `url`;
4. "Optimize order" with a list of 8 varied products (rule 3): at least one round of the AI, that is, `POST /sequence/propose` answers;
5. with `--down`: stops everything (`docker/down`) and checks that no container of the project is left. It checks both `docker compose --profile "*" ps -a` and the label `com.docker.compose.project=aclopi`.
