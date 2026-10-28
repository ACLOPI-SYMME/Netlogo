"""Continuous runs (live / fast) and the WebSocket stream (L5.3), against a real API and pool.

Fast tests share one API with 2 session + 1 what-if workers (no warm-up), idle timeout 4 s.
Rule 3, Stochastic. Message formats: docs/websocket.md.
"""

from __future__ import annotations

import json
import socket
import threading
import time
from typing import Any

import httpx
import psutil
import pytest
from websockets.sync.client import ClientConnection, connect

from aclopi.workers import protocol
from apiserver import ApiServer, start_server, wait_session_workers_free

IDLE_TIMEOUT_S = 4.0


@pytest.fixture(scope="module")
def api(tmp_path_factory: pytest.TempPathFactory) -> Any:
    server = start_server(tmp_path_factory.mktemp("live"), 2, 1, warm=False, idle_s=IDLE_TIMEOUT_S)
    yield server
    server.stop()


@pytest.fixture()
def client(api: ApiServer) -> Any:
    wait_session_workers_free(api.url)
    with httpx.Client(base_url=api.url, timeout=60) as c:
        yield c


def _create(c: httpx.Client, seed: int = 42, horizon: int = 10000) -> str:
    r = c.post("/sessions", json={"seed": seed, "rule": 3, "horizon_ticks": horizon})
    assert r.status_code == 201, r.text
    return r.json()["session_id"]


class Watcher:
    """A WebSocket client that records every message (with its arrival time) in a thread."""

    def __init__(self, api: ApiServer, session_id: str, read: bool = True, rcvbuf: int | None = None,
                 wait_snapshot: bool = True) -> None:
        sock = None
        if rcvbuf is not None:  # a tiny receive buffer: the server's sends block sooner
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, rcvbuf)
            sock.connect(("127.0.0.1", int(api.url.rsplit(":", 1)[1])))
        self._cm = connect(f"{api.ws_url}/ws/sessions/{session_id}", sock=sock,
                           max_queue=1 if not read else 64, open_timeout=30)
        self.ws: ClientConnection = self._cm.__enter__()
        self.messages: list[tuple[float, dict[str, Any]]] = []
        self.close_code: int | None = None
        self.done = threading.Event()
        if read:
            threading.Thread(target=self._read, daemon=True).start()
            if wait_snapshot:
                self.wait_for_any(("snapshot", "closed"))

    def _read(self) -> None:
        try:
            for text in self.ws:
                self.messages.append((time.monotonic(), json.loads(text)))
        except Exception:  # noqa: BLE001
            pass
        finally:
            self.close_code = self.ws.close_code
            self.done.set()

    def of(self, kind: str) -> list[dict[str, Any]]:
        return [m for _, m in self.messages if m["type"] == kind]

    def wait_for(self, kind: str, timeout_s: float = 30.0, count: int = 1) -> list[dict[str, Any]]:
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            found = self.of(kind)
            if len(found) >= count:
                return found
            time.sleep(0.05)
        raise AssertionError(f"no {kind!r} message within {timeout_s} s; got {[m['type'] for _, m in self.messages]}")

    def wait_for_any(self, kinds: tuple[str, ...], timeout_s: float = 30.0) -> None:
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            if any(m["type"] in kinds for _, m in self.messages):
                return
            time.sleep(0.02)
        raise AssertionError(f"none of {kinds} within {timeout_s} s")

    def close(self) -> None:
        self._cm.__exit__(None, None, None)


def _rate(watcher: Watcher, since: float = 0.0) -> float:
    ticks = [(t, m["tick"]) for t, m in watcher.messages if m["type"] == "tick" and t >= since]
    (t0, k0), (t1, k1) = ticks[0], ticks[-1]
    return (k1 - k0) / (t1 - t0)


# ----- a) live rate -----

def test_a_live_rate_1x(api: ApiServer, client: httpx.Client) -> None:
    sid = _create(client)
    w = Watcher(api, sid)
    assert client.post(f"/sessions/{sid}/run", json={"mode": "live", "speed": 1}).json()["run_state"] == "running_live"
    time.sleep(1.0)
    start = time.monotonic()
    time.sleep(20.0)
    rate = _rate(w, since=start)
    print(f"\nlive 1x over 20 s: {rate:.2f} ticks/s")
    assert abs(rate - 32.0) <= 32.0 * 0.05
    info = client.get(f"/sessions/{sid}").json()
    assert info["run_state"] == "running_live" and info["mode"] == "live" and info["speed"] == 1.0
    assert info["watchers"] == 1
    w.close()
    client.delete(f"/sessions/{sid}")


# ----- b) pause and resume -----

def test_b_pause_resume(api: ApiServer, client: httpx.Client) -> None:
    sid = _create(client)
    w = Watcher(api, sid)
    client.post(f"/sessions/{sid}/run", json={"mode": "live", "speed": 2})
    time.sleep(1.5)
    paused = client.post(f"/sessions/{sid}/pause").json()
    assert paused["run_state"] == "paused" and paused["mode"] == "live" and paused["speed"] == 2.0
    tick = paused["ticks"]
    assert tick > 0
    n_ticks = len(w.of("tick"))
    time.sleep(2.0)
    assert client.get(f"/sessions/{sid}/state").json()["tick"] == tick
    assert client.get(f"/sessions/{sid}").json()["ticks"] == tick
    assert len(w.of("tick")) == n_ticks  # nothing streamed while paused
    resumed = client.post(f"/sessions/{sid}/resume").json()
    assert resumed["run_state"] == "running_live" and resumed["speed"] == 2.0
    first = w.wait_for("tick", count=n_ticks + 1)[n_ticks]
    assert first["tick"] - first["advanced"] == tick  # continues from the same tick
    states = [m["run_state"] for m in w.of("run_state")]
    assert states[-3:] == ["running_live", "paused", "running_live"]
    w.close()
    client.delete(f"/sessions/{sid}")


# ----- d) requests during the run -----

def test_d_requests_while_running(api: ApiServer, client: httpx.Client) -> None:
    sid = _create(client)
    assert client.post(f"/sessions/{sid}/pause").status_code == 409  # idle
    assert client.post(f"/sessions/{sid}/resume").status_code == 409
    client.post(f"/sessions/{sid}/run", json={"mode": "live", "speed": 1})
    time.sleep(0.5)
    for path in ("state", "kpis", "layout"):
        t0 = time.perf_counter()
        r = client.get(f"/sessions/{sid}/{path}")
        assert r.status_code == 200 and time.perf_counter() - t0 < 1.0, (path, r.text)
    r = client.post(f"/sessions/{sid}/step", params={"n": 1})
    assert r.status_code == 409 and r.json()["code"] == "invalid_run_state"
    assert client.get(f"/sessions/{sid}/events").status_code == 409
    assert client.post(f"/sessions/{sid}/resume").status_code == 409  # running, not paused
    # switching mode or speed while running is allowed
    assert client.post(f"/sessions/{sid}/run", json={"mode": "live", "speed": 4}).json()["speed"] == 4.0
    assert client.post(f"/sessions/{sid}/run", json={"mode": "live", "speed": 3}).status_code == 422
    client.post(f"/sessions/{sid}/pause")
    assert client.post(f"/sessions/{sid}/step", params={"n": 5}).status_code == 200  # allowed while paused
    assert client.get(f"/sessions/{sid}/events").status_code == 200
    reset = client.post(f"/sessions/{sid}/reset").json()
    assert reset["run_state"] == "idle" and reset["ticks"] == 0 and reset["mode"] is None
    client.delete(f"/sessions/{sid}")


# ----- e) WebSocket: snapshot, several clients, slow client, disconnect -----

def test_e_websocket_clients(api: ApiServer, client: httpx.Client) -> None:
    sid = _create(client)
    client.post(f"/sessions/{sid}/step", params={"n": 50})
    a, b = Watcher(api, sid), Watcher(api, sid)
    slow = Watcher(api, sid, read=False, rcvbuf=4096)
    for w in (a, b):
        first = w.wait_for("snapshot")[0]
        assert w.messages[0][1]["type"] == "snapshot"
        assert first["tick"] == 50 and first["state"]["tick"] == 50
        assert {"nodes", "conveyors"} <= set(first["layout"]) and first["kpis"]["ticks"] == 50
        assert first["session"]["session_id"] == sid
    client.post(f"/sessions/{sid}/run", json={"mode": "live", "speed": 4})
    time.sleep(1.0)
    start = time.monotonic()
    time.sleep(12.0)
    for w in (a, b):
        ticks = [m["tick"] for m in w.of("tick")]
        assert ticks == sorted(ticks) and len(set(ticks)) == len(ticks)  # strictly increasing
        assert abs(_rate(w, since=start) - 128.0) <= 128.0 * 0.05  # the slow client slows nobody
    seq_a = [m["seq"] for _, m in a.messages if "seq" in m and m["type"] != "snapshot"]
    seq_b = [m["seq"] for _, m in b.messages if "seq" in m and m["type"] != "snapshot"]
    common = sorted(set(seq_a) & set(seq_b))
    assert len(common) > 50
    tick_a = {m["seq"]: m["tick"] for m in a.of("tick")}
    tick_b = {m["seq"]: m["tick"] for m in b.of("tick")}
    assert all(tick_a[s] == tick_b[s] for s in common if s in tick_a and s in tick_b)  # same content

    # the slow client: once it reads, it gets a resync with a fresh snapshot (or was dropped)
    resynced = False
    try:
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            m = json.loads(slow.ws.recv(timeout=5))
            if m["type"] == "resync":
                resynced = True
                assert m["dropped"] > 0
                assert json.loads(slow.ws.recv(timeout=5))["type"] == "snapshot"
                break
    except Exception:  # noqa: BLE001 - closed by the server for not reading: also acceptable
        pass
    print(f"\nslow client resynced: {resynced}")

    # disconnecting a client does not stop the run
    a.close()
    tick = client.get(f"/sessions/{sid}").json()["ticks"]
    time.sleep(1.0)
    info = client.get(f"/sessions/{sid}").json()
    assert info["run_state"] == "running_live" and info["ticks"] > tick
    assert len(b.of("tick")) > 0 and not b.done.is_set()
    for w in (b, slow):
        w.close()
    client.delete(f"/sessions/{sid}")


# ----- f) worker crash during a live run -----

def test_f_crash_closes_websocket(api: ApiServer, client: httpx.Client) -> None:
    sid = _create(client)
    w = Watcher(api, sid)
    client.post(f"/sessions/{sid}/run", json={"mode": "live", "speed": 1})
    w.wait_for("tick", count=3)
    pid = next(x["pid"] for x in client.get("/health").json()["workers"] if x["session_id"] == sid)
    psutil.Process(pid).kill()
    closed = w.wait_for("closed", timeout_s=10)[0]
    assert closed["code"] == "session_lost" and closed["reason"]
    assert w.done.wait(10) and w.close_code == 4410
    r = client.get(f"/sessions/{sid}/state")
    assert r.status_code == 410 and r.json()["code"] == "session_lost"
    # a new client of the lost session is told why and closed
    late = Watcher(api, sid)
    assert late.done.wait(10) and late.of("closed")[0]["code"] == "session_lost" and late.close_code == 4410
    client.delete(f"/sessions/{sid}")


# ----- g) end of the run -----

def test_g_fast_run_to_the_end(api: ApiServer, client: httpx.Client) -> None:
    sid = _create(client, horizon=3000)
    w = Watcher(api, sid)
    client.post(f"/sessions/{sid}/run", json={"mode": "fast"})
    finished = w.wait_for("finished", timeout_s=60)[0]
    assert finished["tick"] == 3000 and finished["kpis"]["ticks"] == 3000
    progress = w.of("progress")
    assert progress and progress[-1]["tick"] == 3000 and "state" not in progress[-1]
    assert sum(len(p["events"]) for p in progress) > 0  # fast mode sends its events in batches
    assert w.wait_for("run_state", count=2)[-1]["run_state"] == "finished"
    info = client.get(f"/sessions/{sid}").json()
    assert info["run_state"] == "finished" and info["finished"] is True and info["ticks"] == 3000
    assert client.post(f"/sessions/{sid}/run", json={"mode": "live"}).status_code == 409
    assert client.get(f"/sessions/{sid}/kpis").json() == finished["kpis"]
    w.close()
    client.delete(f"/sessions/{sid}")


def test_live_run_to_the_end(api: ApiServer, client: httpx.Client) -> None:
    sid = _create(client, horizon=400)
    w = Watcher(api, sid)
    client.post(f"/sessions/{sid}/run", json={"mode": "live", "speed": 4})
    finished = w.wait_for("finished", timeout_s=30)[0]
    assert finished["tick"] == 400 and w.of("tick")[-1]["tick"] == 400
    assert client.get(f"/sessions/{sid}").json()["run_state"] == "finished"
    w.close()
    client.delete(f"/sessions/{sid}")


# ----- limits, inactivity and watchdog -----

def test_fast_run_limit(api: ApiServer, client: httpx.Client) -> None:
    a, b = _create(client, horizon=200000), _create(client, horizon=200000)
    assert client.post(f"/sessions/{a}/run", json={"mode": "fast"}).status_code == 200
    r = client.post(f"/sessions/{b}/run", json={"mode": "fast"})
    assert r.status_code == 503 and r.json()["code"] == "fast_run_limit"
    assert client.post(f"/sessions/{b}/run", json={"mode": "live"}).status_code == 200  # live is not limited
    client.post(f"/sessions/{a}/pause")
    assert client.post(f"/sessions/{b}/run", json={"mode": "fast"}).status_code == 200
    r = client.post(f"/sessions/{a}/resume")  # a paused fast run counts when it resumes
    assert r.status_code == 503 and r.json()["code"] == "fast_run_limit"
    for sid in (a, b):
        client.delete(f"/sessions/{sid}")


def test_inactivity_websocket_counts_only_while_running(api: ApiServer, client: httpx.Client) -> None:
    watched_paused, watched_running = _create(client), _create(client)
    wp, wr = Watcher(api, watched_paused), Watcher(api, watched_running)
    for sid in (watched_paused, watched_running):
        client.post(f"/sessions/{sid}/run", json={"mode": "live", "speed": 0.5})
    client.post(f"/sessions/{watched_paused}/pause")
    t0 = time.monotonic()
    closed = wp.wait_for("closed", timeout_s=IDLE_TIMEOUT_S + 6)[0]
    assert closed["code"] == "session_expired" and time.monotonic() - t0 >= IDLE_TIMEOUT_S - 0.5
    assert wp.done.wait(5) and wp.close_code == 4410
    # the running one, watched and without HTTP requests, is still alive
    time.sleep(1.0)
    assert not wr.done.is_set()
    with httpx.Client(base_url=api.url, timeout=30) as c:
        listing = {s["session_id"]: s for s in c.get("/sessions").json()}  # listing does not touch
    assert listing[watched_running]["status"] == "active"
    assert listing[watched_paused]["status"] == "expired"
    # without watchers it expires even while running
    wr.close()
    deadline = time.monotonic() + IDLE_TIMEOUT_S + 6
    while time.monotonic() < deadline:
        with httpx.Client(base_url=api.url, timeout=30) as c:
            status = next(s["status"] for s in c.get("/sessions").json() if s["session_id"] == watched_running)
        if status == "expired":
            break
        time.sleep(0.5)
    assert status == "expired"
    for sid in (watched_paused, watched_running):
        client.delete(f"/sessions/{sid}")


def test_watchdog_kills_a_stalled_run(api: ApiServer, client: httpx.Client) -> None:
    sid = _create(client)
    w = Watcher(api, sid)
    client.post(f"/sessions/{sid}/run", json={"mode": "live", "speed": 1})
    w.wait_for("tick", count=2)
    pid = next(x["pid"] for x in client.get("/health").json()["workers"] if x["session_id"] == sid)
    protocol.set_timeout_scale(0.2)  # watchdog limit 3 s
    try:
        psutil.Process(pid).suspend()  # alive but silent: looks hung
        closed = w.wait_for("closed", timeout_s=15)[0]
    finally:
        protocol.set_timeout_scale(None)
        if psutil.pid_exists(pid):
            try:
                psutil.Process(pid).resume()
            except psutil.Error:
                pass
    assert closed["code"] == "session_lost" and "no progress" in closed["reason"]
    assert client.get(f"/sessions/{sid}/kpis").status_code == 410
    client.delete(f"/sessions/{sid}")


# ----- c) same results as SimulationSession (slow) -----

@pytest.mark.slow
def test_c_live_and_fast_match_direct(api: ApiServer, client: httpx.Client) -> None:
    from aclopi.sim import SimulationSession

    live, fast = _create(client, seed=42), _create(client, seed=42)
    wl, wf = Watcher(api, live), Watcher(api, fast)
    client.post(f"/sessions/{live}/run", json={"mode": "live", "speed": 4})
    client.post(f"/sessions/{fast}/run", json={"mode": "fast"})
    kpis_fast = wf.wait_for("finished", timeout_s=300)[0]["kpis"]
    kpis_live = wl.wait_for("finished", timeout_s=300)[0]["kpis"]
    print(f"\nlive 4x reached 10,000 ticks with {len(wl.of('tick'))} tick messages")
    with SimulationSession() as direct:
        direct.setup(seed=42, rule=3, modeling_type="Stochastic", horizon_ticks=10000)
        direct.run_to_end()
        expected = direct.kpis().as_dict()
    assert kpis_live == expected
    assert kpis_fast == expected
    for w, sid in ((wl, live), (wf, fast)):
        w.close()
        client.delete(f"/sessions/{sid}")
