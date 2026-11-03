"""REST API (L5.2) against a real worker pool, through real HTTP (uvicorn in a thread + httpx).

Fast tests share one small API (2 session + 1 what-if workers, no warm-up, idle timeout 3 s).
Slow tests (-m slow) start the full platform (5 + 2 workers, warmed up).
The pool always runs with debug=False, as in production.
"""


from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

import httpx
import psutil
import pytest

from aclopi.api.instance_lock import InstanceLock, InstanceLockError
from aclopi.logjson import JsonFormatter
from aclopi.workers import protocol
from apiserver import ApiServer, free_port as _free_port, start_server as _start_server, wait_session_workers_free

REPO_ROOT = Path(__file__).resolve().parents[1]
CONTRACT = REPO_ROOT / "contracts" / "openapi.json"
IDLE_TIMEOUT_S = 3.0


@pytest.fixture(scope="module")
def api(tmp_path_factory: pytest.TempPathFactory) -> Any:
    server = _start_server(tmp_path_factory.mktemp("api"), 2, 1, warm=False, idle_s=IDLE_TIMEOUT_S)
    yield server
    server.stop()
    assert not server.thread.is_alive()
    alive = [pid for pid in server.runtime.pool.spawned_pids if psutil.pid_exists(pid)
             and psutil.Process(pid).status() != psutil.STATUS_ZOMBIE]
    assert alive == [], f"worker processes left behind: {alive}"


@pytest.fixture()
def client(api: ApiServer) -> Any:
    wait_session_workers_free(api.url)
    with httpx.Client(base_url=api.url, timeout=60) as c:
        yield c

def _create(c: httpx.Client, seed: int = 42, rule: int = 3, **extra: Any) -> str:
    r = c.post("/sessions", json={"seed": seed, "rule": rule, **extra})
    assert r.status_code == 201, r.text
    return r.json()["session_id"]


def _worker_of(c: httpx.Client, session_id: str) -> dict[str, Any]:
    return next(w for w in c.get("/health").json()["workers"] if w["session_id"] == session_id)


# ----- h) startup -----

def test_h_startup_phases(api: ApiServer) -> None:
    s = api.startup
    assert s["first_answer_s"] < 5.0  # uvicorn answers while the pool is still starting
    assert s["live"] == 200 and s["live_after"] == 200
    assert s["health_status"] == "starting"
    assert s["ready_code"] == 503
    assert s["create_code"] == 503
    assert s["create_body"]["code"] == "platform_starting"
    assert s["create_body"]["detail"] == "plataforma iniciando"
    assert s["ready_code_after"] == 200
    ready = s["ready_health"]
    assert ready["status"] == "ready"
    assert len(ready["workers"]) == 3
    assert all(w["ready"] and w["state"] == "free" and w["pid"] for w in ready["workers"])
    assert {w["role"] for w in ready["workers"]} == {"session", "whatif"}
    assert ready["sessions"] == {"active": 0, "max": 2}


# ----- i) diagnostic operations are not exposed -----

def test_i_no_diagnostic_operations(api: ApiServer, client: httpx.Client) -> None:
    paths = client.get("/openapi.json").json()["paths"]
    assert not [p for p in paths if "command" in p or "report" in p]
    sid = _create(client)
    for op in ("command", "report"):
        assert client.post(f"/sessions/{sid}/{op}", json={"code": "ca"}).status_code == 404
    assert api.runtime.pool.debug is False
    client.delete(f"/sessions/{sid}")


def test_contract_is_up_to_date(api: ApiServer) -> None:
    rendered = json.dumps(api.app.openapi(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    assert CONTRACT.read_text(encoding="utf-8") == rendered, "run python scripts/export_openapi.py"


# ----- d) validation -----

def test_d_validation(client: httpx.Client) -> None:
    sid = _create(client)
    for n in (2001, 0, -1):
        assert client.post(f"/sessions/{sid}/step", params={"n": n}).status_code == 422
    assert client.post(f"/sessions/{sid}/step").status_code == 422  # n is required
    assert client.post(f"/sessions/{sid}/step", params={"n": "abc"}).status_code == 422
    assert client.post("/sessions", json={"seed": 1, "rule": 5}).status_code == 422  # rule 4 is valid since L5.4
    assert client.post("/sessions", json={"seed": 1, "rule": 3, "modeling_type": "Random"}).status_code == 422
    assert client.post("/sessions", json={"seed": 1, "rule": 3, "horizon_ticks": 0}).status_code == 422
    assert client.post("/sessions", json={"rule": 3}).status_code == 422
    assert client.post("/sessions", json={"seed": 1, "rule": 3, "extra": 1}).status_code == 422
    # the session is untouched by the rejected requests
    assert client.get(f"/sessions/{sid}").json()["ticks"] == 0

    missing = "0" * 32
    for method, path in (("GET", ""), ("GET", "/state"), ("GET", "/events"), ("GET", "/layout"), ("GET", "/kpis"),
                         ("POST", "/reset"), ("DELETE", "")):
        r = client.request(method, f"/sessions/{missing}{path}")
        assert r.status_code == 404, (method, path, r.text)
        assert r.json()["code"] == "session_not_found"
    r = client.post(f"/sessions/{missing}/step", params={"n": 1})
    assert r.status_code == 404
    client.delete(f"/sessions/{sid}")


def test_session_endpoints_shape(client: httpx.Client) -> None:
    sid = _create(client, seed=7, rule=2, modeling_type="Deterministic", horizon_ticks=3000)
    info = client.get(f"/sessions/{sid}").json()
    assert info["parameters"] == {"seed": 7, "rule": 2, "modeling_type": "Deterministic", "horizon_ticks": 3000}
    assert info["status"] == "active" and info["ticks"] == 0 and info["finished"] is False
    step = client.post(f"/sessions/{sid}/step", params={"n": 2000}).json()
    assert step == {"ticks": 2000, "advanced": 2000, "finished": False}
    state = client.get(f"/sessions/{sid}/state").json()
    assert state["tick"] == 2000 and set(state) >= {"segments", "gates", "machines", "products"}
    events = client.get(f"/sessions/{sid}/events").json()
    assert events and {"tick", "event"} <= set(events[0])
    assert client.get(f"/sessions/{sid}/events").json() == []  # reading empties the buffer
    layout = client.get(f"/sessions/{sid}/layout").json()
    assert len(layout["machines"]) == 7
    kpis = client.get(f"/sessions/{sid}/kpis").json()
    assert kpis["ticks"] == 2000 and len(kpis["utilization"]) == 7
    step = client.post(f"/sessions/{sid}/step", params={"n": 2000}).json()
    assert step["finished"] is True and step["ticks"] == 3000
    assert client.get(f"/sessions/{sid}").json()["finished"] is True
    assert client.post(f"/sessions/{sid}/step", params={"n": 10}).json()["advanced"] == 0
    reset = client.post(f"/sessions/{sid}/reset").json()
    assert reset["ticks"] == 0 and reset["finished"] is False
    assert [s["session_id"] for s in client.get("/sessions").json() if s["status"] == "active"] == [sid]
    assert client.delete(f"/sessions/{sid}").status_code == 204
    assert client.get(f"/sessions/{sid}").status_code == 404


# ----- b) no free worker -----

def test_b_no_free_worker(client: httpx.Client) -> None:
    first, second = _create(client), _create(client)
    r = client.post("/sessions", json={"seed": 3, "rule": 3})
    assert r.status_code == 503
    assert r.json()["code"] == "no_free_worker"
    assert "busy" in r.json()["detail"]
    assert client.delete(f"/sessions/{first}").status_code == 204
    third = _create(client)
    for sid in (second, third):
        client.delete(f"/sessions/{sid}")


# ----- c) lost session -----

def test_c_lost_session_after_worker_crash(api: ApiServer, client: httpx.Client) -> None:
    sid = _create(client)
    client.post(f"/sessions/{sid}/step", params={"n": 100})
    worker = _worker_of(client, sid)
    psutil.Process(worker["pid"]).kill()

    r = client.get(f"/sessions/{sid}/state")
    assert r.status_code == 410, r.text
    body = r.json()
    assert body["code"] == "session_lost" and body["session_id"] == sid
    assert "exit" in body["detail"] or "not running" in body["detail"]
    assert client.post(f"/sessions/{sid}/step", params={"n": 1}).status_code == 410
    info = client.get(f"/sessions/{sid}").json()
    assert info["status"] == "lost" and info["lost_reason"]

    # the restarted worker is available again
    deadline = time.monotonic() + 180
    while True:
        w = next(w for w in client.get("/health").json()["workers"] if w["slot"] == worker["slot"])
        if w["state"] == "free" and w["ready"]:
            break
        assert time.monotonic() < deadline, "worker was not restarted"
        time.sleep(0.25)
    assert w["restarts"] == 1 and w["pid"] != worker["pid"]
    assert client.get("/health").json()["status"] == "ready"
    sids = [_create(client), _create(client)]  # both session workers usable
    assert client.delete(f"/sessions/{sid}").status_code == 204
    for s in sids:
        client.delete(f"/sessions/{s}")


def test_worker_timeout_gives_504_then_410(client: httpx.Client) -> None:
    sid = _create(client)
    slot = _worker_of(client, sid)["slot"]
    protocol.set_timeout_scale(1e-4)  # step(2000) timeout becomes 1.5 ms: the worker is treated as hung
    try:
        r = client.post(f"/sessions/{sid}/step", params={"n": 2000})
    finally:
        protocol.set_timeout_scale(None)
    assert r.status_code == 504, r.text
    assert r.json()["code"] == "worker_timeout"
    r = client.get(f"/sessions/{sid}/kpis")
    assert r.status_code == 410 and r.json()["code"] == "session_lost"
    assert "unresponsive" in r.json()["detail"]
    deadline = time.monotonic() + 180
    while True:
        w = next(w for w in client.get("/health").json()["workers"] if w["slot"] == slot)
        if w["state"] == "free" and w["ready"]:
            break
        assert w["state"] in ("busy", "restarting"), w  # never "free" while dead
        assert time.monotonic() < deadline
        time.sleep(0.1)
    client.delete(f"/sessions/{sid}")


def test_json_logs_carry_session_id(client: httpx.Client, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO)
    sid = _create(client)
    client.post(f"/sessions/{sid}/step", params={"n": 5})
    access = [r for r in caplog.records if r.name == "aclopi.api.app" and getattr(r, "path", "").startswith("/sessions")]
    assert {"/sessions", f"/sessions/{sid}/step"} <= {r.path for r in access}
    assert all(r.session_id == sid for r in access)
    line = json.loads(JsonFormatter().format(access[-1]))
    assert line["session_id"] == sid and line["status_code"] == 200 and line["path"] == f"/sessions/{sid}/step"
    created = [r for r in caplog.records if r.name == "aclopi.api.registry" and "created" in r.getMessage()]
    assert created and json.loads(JsonFormatter().format(created[-1]))["session_id"] == sid
    client.delete(f"/sessions/{sid}")


# ----- f) order within a session -----

def test_f_concurrent_steps_same_session(client: httpx.Client, api: ApiServer) -> None:
    sid = _create(client)

    async def burst() -> list[httpx.Response]:
        async with httpx.AsyncClient(base_url=api.url, timeout=60) as ac:
            return await asyncio.gather(*(ac.post(f"/sessions/{sid}/step", params={"n": 1}) for _ in range(20)))

    responses = asyncio.run(burst())
    assert [r.status_code for r in responses] == [200] * 20
    assert sorted(r.json()["ticks"] for r in responses) == list(range(1, 21))
    assert client.get(f"/sessions/{sid}").json()["ticks"] == 20
    assert client.get(f"/sessions/{sid}/state").json()["tick"] == 20
    client.delete(f"/sessions/{sid}")


def test_health_answers_while_worker_busy(client: httpx.Client, api: ApiServer) -> None:
    sid = _create(client)
    done: list[float] = []

    def long_step() -> None:
        with httpx.Client(base_url=api.url, timeout=60) as c:
            t0 = time.perf_counter()
            for _ in range(3):
                c.post(f"/sessions/{sid}/step", params={"n": 2000})
            done.append(time.perf_counter() - t0)

    t = threading.Thread(target=long_step)
    t.start()
    time.sleep(0.3)
    latencies = []
    while t.is_alive():
        t0 = time.perf_counter()
        assert client.get("/health").status_code == 200
        latencies.append(time.perf_counter() - t0)
        time.sleep(0.1)
    t.join()
    assert latencies and max(latencies) < 1.0, latencies
    client.delete(f"/sessions/{sid}")


# ----- g) idle sessions -----

def test_g_idle_session_closed(client: httpx.Client) -> None:
    idle, busy = _create(client), _create(client)
    t0 = time.monotonic()
    status = "active"
    while time.monotonic() - t0 < IDLE_TIMEOUT_S + 5:
        client.post(f"/sessions/{busy}/step", params={"n": 1})  # keeps "busy" alive
        status = next(s["status"] for s in client.get("/sessions").json() if s["session_id"] == idle)
        if status == "expired":
            break
        time.sleep(0.5)
    assert status == "expired"
    assert time.monotonic() - t0 >= IDLE_TIMEOUT_S
    r = client.post(f"/sessions/{idle}/step", params={"n": 1})
    assert r.status_code == 410 and r.json()["code"] == "session_expired"
    assert next(s for s in client.get("/sessions").json() if s["session_id"] == busy)["status"] == "active"
    # its worker was freed: a new session fits next to "busy"
    other = _create(client)
    for sid in (busy, other, idle):
        assert client.delete(f"/sessions/{sid}").status_code == 204


# ----- startup failure and single instance -----

def test_startup_failure_exits_with_code_3(tmp_path: Path) -> None:
    env = dict(os.environ, ACLOPI_STARTUP_TIMEOUT_S="2", ACLOPI_N_SESSION_WORKERS="1", ACLOPI_N_WHATIF_WORKERS="1",
               ACLOPI_API_PORT=str(_free_port()), ACLOPI_API_HOST="127.0.0.1", ACLOPI_WORK_DIR=str(tmp_path))
    proc = subprocess.run([sys.executable, "-m", "aclopi.api"], cwd=REPO_ROOT, env=env, capture_output=True,
                          text=True, timeout=180)
    assert proc.returncode == 3, proc.stderr[-2000:]
    lines = [json.loads(line) for line in proc.stderr.splitlines() if line.startswith("{")]
    failed = [ln for ln in lines if "failed to start" in ln["msg"] and ln.get("worker")]
    assert failed and failed[0]["level"] == "ERROR" and "not ready after" in failed[0]["msg"]
    assert any(ln["msg"].startswith("Worker pool failed to start") for ln in lines)
    assert not (tmp_path / "api.lock").exists()  # released on the way out


def test_second_instance_refused(tmp_path: Path) -> None:
    first = InstanceLock(tmp_path)
    first.acquire()
    with pytest.raises(InstanceLockError, match="single uvicorn worker|already held"):
        InstanceLock(tmp_path).acquire()
    first.release()
    (tmp_path / "api.lock").write_text(json.dumps({"pid": 999999, "host": "other-host", "create_time": 0}))
    stale = InstanceLock(tmp_path)
    stale.acquire()  # a lock left by another host/container is replaced
    stale.release()


# ----- slow: full platform (5 + 2 warmed-up workers) -----

@pytest.fixture(scope="module")
def full_api(tmp_path_factory: pytest.TempPathFactory) -> Any:
    server = _start_server(tmp_path_factory.mktemp("api_full"), 5, 2, warm=True, idle_s=1800)
    yield server
    server.stop()


@pytest.mark.slow
def test_h_full_platform_ready(full_api: ApiServer) -> None:
    s = full_api.startup
    assert s["health_status"] == "starting" and s["create_code"] == 503 and s["ready_code"] == 503
    workers = s["ready_health"]["workers"]
    assert len(workers) == 7 and all(w["ready"] for w in workers)
    print(f"\nfull platform: first answer {s['first_answer_s']:.2f} s, ready {s['ready_s']:.1f} s")


@pytest.mark.slow
def test_a_full_cycle_matches_direct_session(full_api: ApiServer) -> None:
    from aclopi.sim import SimulationSession

    with httpx.Client(base_url=full_api.url, timeout=60) as c:
        sid = _create(c, seed=42, rule=3)
        slot = _worker_of(c, sid)["slot"]
        blocks = []
        for _ in range(5):
            blocks.append(c.post(f"/sessions/{sid}/step", params={"n": 2000}).json())
        assert [b["ticks"] for b in blocks] == [2000, 4000, 6000, 8000, 10000]
        assert blocks[-1]["finished"] is True
        api_kpis = c.get(f"/sessions/{sid}/kpis").json()
        assert c.delete(f"/sessions/{sid}").status_code == 204
        assert c.get(f"/sessions/{sid}").status_code == 404
        w = next(w for w in c.get("/health").json()["workers"] if w["slot"] == slot)
        assert w["state"] == "free" and w["session_id"] is None

    with SimulationSession() as direct:
        direct.setup(seed=42, rule=3, modeling_type="Stochastic", horizon_ticks=10000)
        direct.run_to_end()
        assert api_kpis == direct.kpis().as_dict()


@pytest.mark.slow
def test_e_parallel_sessions(full_api: ApiServer) -> None:
    async def run_session(ac: httpx.AsyncClient, sid: str) -> dict[str, Any]:
        for _ in range(5):
            r = await ac.post(f"/sessions/{sid}/step", params={"n": 2000})
            assert r.status_code == 200
        return (await ac.get(f"/sessions/{sid}/kpis")).json()

    async def scenario() -> tuple[float, float, list[dict[str, Any]], list[dict[str, Any]]]:
        async with httpx.AsyncClient(base_url=full_api.url, timeout=120) as ac:
            sids = []
            for _ in range(5):
                r = await ac.post("/sessions", json={"seed": 42, "rule": 3})
                assert r.status_code == 201
                sids.append(r.json()["session_id"])
            t0 = time.perf_counter()
            sequential = [await run_session(ac, sid) for sid in sids]
            t_seq = time.perf_counter() - t0
            for sid in sids:
                assert (await ac.post(f"/sessions/{sid}/reset")).status_code == 200
            t0 = time.perf_counter()
            parallel = await asyncio.gather(*(run_session(ac, sid) for sid in sids))
            t_par = time.perf_counter() - t0
            for sid in sids:
                await ac.delete(f"/sessions/{sid}")
            return t_seq, t_par, sequential, list(parallel)

    t_seq, t_par, sequential, parallel = asyncio.run(scenario())
    print(f"\n5 x 10,000 ticks over HTTP: sequential {t_seq:.1f} s, parallel {t_par:.1f} s, "
          f"speed-up {t_seq / t_par:.2f}x")
    assert all(k == sequential[0] for k in sequential + parallel)
    assert t_seq / t_par > 1.3
