# Local deployment with Docker Compose (L5.7)

`docker-compose.yml`, at the root of the repo, starts three services on an internal network. **The platform always works with Línea A's agent.** The mock agent (`aclopi.agent_mock`) is not in Compose: only the automatic tests use it, inside their own process.

| Service | Image | What it is | Published port |
|---|---|---|---|
| `platform` | `aclopi-sim` (`docker/Dockerfile`, `CMD` = the API) | API, NetLogo workers and `/ui` | **8000** |
| `agent` | `aclopi-agent` (`docker/agent.Dockerfile`) | Línea A's agent | none |
| `dynamodb-local` | `amazon/dynamodb-local:2.5.2` | Results and product sets, in memory | none |

## Prepare

```powershell
Copy-Item .env.example .env      # if it does not exist; then set ACLOPI_AGENT_TOKEN to a value of your own
```

- `.env` is not committed to git.
- Compose reads `ACLOPI_AGENT_TOKEN` from it and passes it to the platform and to the agent.
- The NetLogo paths in `.env` are only used on Windows; they do not matter inside the container.
- The agent's settings (LLM, triage) come from `.env.agent`, which is not in git (see `.env.agent.example`). Without that file the agent uses its fake LLM.

## Start, watch, stop

```powershell
docker compose up -d --build         # everything; --build rebuilds the agent's image with the current code
docker compose ps                    # platform becomes "healthy" when /health/ready answers 200 (~1.5 min)
docker compose logs -f platform      # JSON logs; also agent and dynamodb-local
docker compose down                  # stops and removes everything, the agent included (DynamoDB Local is in memory: it is lost)
```

The agent is a plain service of the stack, with no profile, so a plain `up` / `down` starts and stops it like the others.

**Use `--build` after changes to Línea A's code.** Without it, Compose reuses the old image. On 12 Nov an image of 9 Nov without `POST /sequence/propose` made "Optimize order" end with "the AI answered 404". The page now explains that case: "The AI is not available (the agent has no order-proposing function)".

**Which agent the platform talks to:** `GET /health` → `agent`. It shows:
- `kind`: `real`, deduced from the host of the URL (`agent`);
- `url`: `http://agent:8100`;
- `status`: `ok` when the agent answers.

If Línea A adds `kind` to its own `/health`, it can be read from there instead of deduced from the URL.

To check that nothing of the project is left after `down`: `docker ps -a --filter label=com.docker.compose.project=aclopi`.

Test page: `http://localhost:8000/ui`. API: `http://localhost:8000/docs`.

## Platform variables in Compose

| Variable | Value | What for |
|---|---|---|
| `ACLOPI_AGENT_URL` | `http://agent:8100` (fixed in `docker-compose.yml`) | Where the agent is. Not in `.env` |
| `ACLOPI_AGENT_TOKEN` | `.env` | Token shared with the agent (`Authorization: Bearer`) |
| `ACLOPI_DYNAMODB_ENDPOINT` | `http://dynamodb-local:8000` | Turns on the DynamoDB store (`aclopi/api/results.py`) |
| `ACLOPI_CREATE_TABLES` | `1` | Creates the tables at startup (local only; in the cloud the infrastructure creates them) |
| `ACLOPI_AWS_REGION` | `eu-north-1` | DynamoDB region (Stockholm). DynamoDB Local ignores it |
| `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` | `local` | DynamoDB Local accepts any value |

**Platform limits:** those of L4 (`cpus: 4`, `cpuset: 0-3`, `mem_limit: 6g`).

**Healthchecks:**
- `platform` uses `/health/ready`. The image's own `HEALTHCHECK` uses `/health/live`, and Compose replaces it.
- `agent` uses its `/health`.

**Restart:** `restart: unless-stopped` for every service: a `docker compose down` removes them all. If DynamoDB Local does not accept connections yet when the platform starts, the startup fails and Docker restarts it.

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
python scripts\l5\smoke_compose.py               # with the stack up; uses ACLOPI_AGENT_TOKEN from the environment or from .env
python scripts\l5\smoke_compose.py --up --down   # starts it (docker compose up -d --build), tests, and stops everything
```

The script:
1. uploads a CSV of 8 products, saves it as a set and runs rule 4 with `b1` in fast mode, without a seed. It checks `all_products_done`, the makespan, the decisions, that the random seed was kept and that the run is in DynamoDB Local (`/runs`);
2. runs rule 4 with `agent` live for 30 s. It checks the decisions through the WebSocket and the pace of ~32 ticks/s;
3. checks that `/health` shows Línea A's agent (`kind: real`, `http://agent:8100`) answering;
4. "Optimize order" with a list of 8 varied products (rule 3): at least one round of the AI, that is, `POST /sequence/propose` answers;
5. with `--down`: stops everything (`docker compose down`) and checks that no container of the project is left (`docker compose ps -a` and the label `com.docker.compose.project=aclopi`).
