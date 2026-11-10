# ACLOPI Annecy – Simulation platform

Digital twin of a plant (monorail) in NetLogo 6.4.0 (`model/Paper.nlogo`), run headless from Python with pynetlogo.

## Requirements

- Windows 11
- 64-bit Python 3.12 (the venv must be created with `py -3.12`, not with the system's default Python)
- NetLogo 6.4.0 installed in `C:\Program Files\NetLogo 6.4.0`

## Environment setup (PowerShell)

Every command is run from the root of the repository.

Create the virtual environment:

```powershell
py -3.12 -m venv .venv
```

Activate it (if PowerShell blocks the script, first run `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`):

```powershell
.\.venv\Scripts\Activate.ps1
```

Install the dependencies:

```powershell
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip install -e .
```

The last command installs the project's package, `aclopi`, in editable mode so that the scripts and the tests can import it.

Create the `.env` file from the template and adjust the paths if NetLogo is somewhere else:

```powershell
Copy-Item .env.example .env
```

## Smoke test

Checks that NetLogo starts headless, loads the model, runs `setup` and 100 ticks:

```powershell
python scripts\smoke_test.py
```

The output folders `Results/Data` and `Results/Events` are created inside `model/`, because NetLogo resolves relative paths against the model's folder.

## Validation and regression

Full runs (10,000 ticks) of rules 1, 2 and 3 with seed 42 in Stochastic mode, with a determinism check:

```powershell
.\scripts\run_all_rules.ps1
```

Comparison of those runs with the baseline committed in `tests/fixtures/baseline/` (KPIs, SHA-256 of Events and Data column by column):

```powershell
python scripts\compare_baseline.py
```

Tests (structure of the platform reporters, non-interference of the reads and regression against the baseline; it takes about 1 minute):

```powershell
python -m pytest -v
```

The long regression (rule 3, 100,000 ticks, seeds 42 and 7, against `tests/fixtures/long/`) is marked as slow and is left out of the normal run. It is run separately (about 2 minutes):

```powershell
python -m pytest -m slow -v
```

`pytest.ini` disables `faulthandler`, which on Windows would print as "access violation" exceptions that the JVM raises and handles internally; it does not affect the result of the tests.

## The model's platform interface

Read-only reporters for Python. They return JSON in a string (`json.loads(str(netlogo.report(...)))`) and consume no random numbers:

- `platform-layout`: nodes, conveyors (curves included), machines, sensors and gates. Read once, after `setup`.
- `platform-state`: compact state of segments, gates, machines and live products.
- `platform-events`: events recorded since the last call to `platform-clear-events`.

Read time of `platform-state`:

```powershell
python scripts\benchmark_platform_state.py
```

## Simulation sessions (`aclopi.sim`)

`SimulationSession` wraps a simulation in its own NetLogo workspace and its own output folder (`results/sessions/<session_id>/`), so the exports of several sessions do not overwrite each other. One process can hold several sessions, as long as they are used from a single thread.

```python
from aclopi.sim import SimulationSession

with SimulationSession() as s:
    s.setup(seed=42, rule=3, modeling_type="Stochastic", horizon_ticks=10000)
    s.step(100)          # advances up to 100 ticks in a single call
    state = s.state()    # platform-state as a dict
    events = s.events()  # reads and empties the event buffer
    s.run_to_end()
    print(s.kpis())
```

What-if: `path = s.export_world()` and then `other.import_world(path)` on one or several sessions (or directly `s.clone_to(other)`). The exported world keeps the state of the random generator, so the clone continues exactly like the original.

The horizon of the run is the model's global `horizon-ticks` (10000 by default), which `setup(..., horizon_ticks=...)` sets after `setup`.

Session benchmarks (cloning at tick 3000 and runs in blocks):

```powershell
python scripts\benchmark_session.py --part clone
python scripts\benchmark_session.py --part blocks
```

## Workers (`aclopi.workers`)

Each simulation runs in its own worker process (NetLogo only works from the main thread of a process). `WorkerPool` starts 5 session workers and 2 what-if workers, and talks to them through queues:

```python
from aclopi.workers import WorkerPool

with WorkerPool() as pool:
    h = pool.acquire_session("demo")
    h.request("setup", seed=42, rule=3)
    h.request("step", n=100)            # at most 2000 ticks per request
    with pool.whatif_from_session("demo") as w:
        w.request("step", n=1000)
    pool.release_session("demo")
```

The design, the request-duration rule and crash handling are in `docs/workers.md`.

## REST API (`aclopi.api`)

HTTP API (FastAPI) over the pool of workers. The contract for Línea A is in `contracts/openapi.json`, and the design, errors and configuration in `docs/api.md`.

What each piece of data produced by the platform means (runs, decisions, metrics, KPIs, events, WebSocket, logs) and how to read it: [`docs/records/README.md`](docs/records/README.md).

**Always a single process with a single uvicorn worker.** Each API process starts its own pool (7 JVMs, ~3.3 GB). That is why `uvicorn --workers N` must not be used: several uvicorn workers or several APIs on the same folder would multiply the JVMs and the memory. A lock file (`results/workers/api.lock`) prevents starting a second instance.

### On Windows

```powershell
python -m aclopi.api
```

- It listens on `http://localhost:8000`, and the interactive documentation is at `http://localhost:8000/docs`.
- `GET /health/ready` answers 503 while the pool starts (about 1–1.5 min) and 200 when it is ready. `GET /health` shows the detail per worker.
- Configuration goes through environment variables (`ACLOPI_API_PORT`, `ACLOPI_N_SESSION_WORKERS`, `ACLOPI_SESSION_IDLE_TIMEOUT_S`, …; see `docs/api.md`).

Example:

```powershell
$s = Invoke-RestMethod -Method Post http://localhost:8000/sessions -ContentType application/json -Body '{"seed": 42, "rule": 3}'
Invoke-RestMethod -Method Post "http://localhost:8000/sessions/$($s.session_id)/step?n=2000"
Invoke-RestMethod "http://localhost:8000/sessions/$($s.session_id)/kpis"
Invoke-RestMethod -Method Delete "http://localhost:8000/sessions/$($s.session_id)"
```

**Continuous and real-time runs (L5.3).** `POST /sessions/{id}/run` with `{"mode": "live", "speed": 1}` (pace of 32 ticks/s × speed) or with `{"mode": "fast"}` (no speed limit). Then `/pause` and `/resume`. The state, the events and the KPIs arrive through the WebSocket at `ws://localhost:8000/ws/sessions/{id}`; the format is in `docs/websocket.md`.

To try it by hand, the page **`http://localhost:8000/ui`** has three tabs:
- **Order entry:** build the list of products (type and order, at most 30), generate it from a seed, upload or download it as CSV, save it;
- **Visualization:** create a session, run it live (the speed can be changed while it runs) or fast, pause, resume, reset and close it. It draws the plant and the products (coloured and lettered by type), the indicators, the agent's latest decisions and the model events;
- **History Logs:** the saved runs, with filters, comparison, their decisions, "Repeat" and CSV export.

To regenerate the contract after changing the API (a test fails if it is out of date):

```powershell
python scripts\export_openapi.py
```

### In the container

With the same L4 limits (`--cpus=4 --cpuset-cpus=0-3 --memory=6g --memory-swap=6g`) and port 8000 published:

```powershell
docker build -f docker/Dockerfile -t aclopi-sim .
.\docker\run_api.ps1                                      # in the foreground; Ctrl+C stops it
.\docker\run_api.ps1 -Detach -Restart unless-stopped      # in the background, with automatic restart
```

- **Logs:** seen with `docker logs aclopi-api`; each line is a JSON object with `session_id`.
- **Healthcheck:** the image's `HEALTHCHECK` uses `/health/live`. The cloud load balancer must use `/health/ready`.

**Recommended restart policy.** If some worker does not start within `ACLOPI_STARTUP_TIMEOUT_S`, the API shuts the pool down and exits with code 3.

| Policy | When to use it |
|---|---|
| `restart: on-failure` (or `--restart=on-failure`) | Retries only when the API exits with an error. The conservative option |
| `restart: unless-stopped` | Also starts it again when Docker or the machine restarts, unless it was stopped by hand. Recommended for the cloud, where the platform is switched on before working hours |

Local deployment with Docker Compose (platform + DynamoDB Local + mock agent): `docs/deploy-local.md`.

## Linux container (Docker)

Image with Python 3.12, NetLogo 6.4.0 for Linux (downloaded from `downloads.netlogo.org` with its checksum verified) and the `aclopi` package:

```powershell
docker build -f docker/Dockerfile -t aclopi-sim .
```

`docker/run.ps1` runs a command in the container with the limits of the measurements (`--cpus=4 --cpuset-cpus=0-3 --memory=6g --memory-swap=6g`) and mounts `results/`:

```powershell
.\docker\run.ps1 bash scripts/l4/regression.sh
```

The L4 concurrency measurements are in `scripts/l4/` and leave their results in `results/l4/`.

The known problems of the model that are not fixed are in `docs/known-issues.md`.
