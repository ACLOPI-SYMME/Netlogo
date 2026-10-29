"""What-if of a pending decision (L5.4) through the API, against a real pool.

Fast tests share one API with 2 session + 2 what-if workers (no warm-up). Decisions are found in a
direct SimulationSession (rule 4, same seed) with run_until_decision; the API session is stepped to
the same tick, so both worlds are identical there.
"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Any

import httpx
import pytest

from aclopi.sim import SimulationSession
from aclopi.sim.decisions import DecisionRequest, clear_decisions, pending_decisions, run_until_decision, set_next_machine
from apiserver import ApiServer, start_server, wait_session_workers_free

from test_live import Watcher


@pytest.fixture(scope="module")
def api(tmp_path_factory: pytest.TempPathFactory) -> Any:
    # Warmed-up workers, as in production: a cold JVM runs the copies several times slower.
    # The 5 s budget is checked by test_timeout_returns_what_is_ready and measured in the container
    # (scripts/l5/bench_whatif.py); here a loaded laptop must not turn exactness checks into timeouts.
    server = start_server(tmp_path_factory.mktemp("whatif"), 2, 2, warm=True, idle_s=600, whatif_timeout_s=20.0)
    yield server
    server.stop()


@pytest.fixture()
def client(api: ApiServer) -> Any:
    wait_session_workers_free(api.url)
    with httpx.Client(base_url=api.url, timeout=120) as c:
        yield c


def find_decision(seed: int, nth: int = 1) -> tuple[int, DecisionRequest, Path]:
    """The nth decision request of a rule-4 run: (tick, request, snapshot of the world at that tick)."""
    with SimulationSession() as s:
        s.setup(seed=seed, rule=4)
        for _ in range(nth):
            run_until_decision(s, 10000)
            reqs = pending_decisions(s)
            clear_decisions(s)
        return s.ticks, reqs[0], s.export_world()


def truth(snapshot: Path, req: DecisionRequest, machine: str, max_ticks: int = 4000) -> tuple[int, float, float]:
    """The real session from the snapshot with the machine assigned: (entry tick, entry time, op end)."""
    with SimulationSession() as s:
        s.import_world(snapshot)
        assert set_next_machine(s, req.who, machine, req.seq) == "ok"
        for _ in range(max_ticks):
            if int(s._report(f"length [ProductRealStart] of turtle {req.who}")) > req.seq:
                break
            s.step(1)
        return (s.ticks, float(s._report(f"item {req.seq} [ProductRealStart] of turtle {req.who}")),
                float(s._report(f'[Next.Completion] of one-of machines with [Machine.Name = "{machine}"]')))


def api_session(c: httpx.Client, seed: int, tick: int, rule: int = 4, horizon: int = 10000) -> str:
    r = c.post("/sessions", json={"seed": seed, "rule": rule, "horizon_ticks": horizon})
    assert r.status_code == 201, r.text
    sid = r.json()["session_id"]
    while tick > 0:
        n = min(tick, 2000)
        c.post(f"/sessions/{sid}/step", params={"n": n}).raise_for_status()
        tick -= n
    return sid


def whatif(c: httpx.Client, sid: str, req: DecisionRequest, options: list[str], max_ticks: int = 2000) -> httpx.Response:
    return c.post(f"/sessions/{sid}/what-if",
                  json={"product": req.who, "seq": req.seq, "options": options, "max_ticks": max_ticks})


# ----- a) exactness and c) two options -----

def test_a_c_exact_prediction_and_common_window(client: httpx.Client) -> None:
    tick, req, snapshot = find_decision(seed=42, nth=4)
    try:
        sid = api_session(client, 42, tick)
        assert client.get(f"/sessions/{sid}/state").json()["tick"] == tick
        options = list(req.candidates[:2])
        r = whatif(client, sid, req, options)
        assert r.status_code == 200, r.text
        body = r.json()
        print("\nwhat-if:", json.dumps({k: body[k] for k in ("status", "run_order", "window_tick", "timings_ms")}),
              [(o["machine"], o["stop_reason"], o["ticks_simulated"], o["duration_ms"]) for o in body["options"]])
        assert body["status"] == "ok" and body["snapshot_tick"] == tick
        assert [o["machine"] for o in body["options"]] == options  # request order
        first, second = (next(o for o in body["options"] if o["machine"] == m) for m in body["run_order"])
        # a) the first copy stops when its product enters: exactly what the real session does
        assert first["entered"] and first["stop_reason"] == "entered" and not first["entry_estimated"]
        t_tick, t_time, t_end = truth(snapshot, req, first["machine"])
        assert (first["entry_tick"], first["entry_time"], first["op_end_time"]) == (t_tick, t_time, t_end)
        # c) common window: the first stop; both metrics measured there
        assert body["window_tick"] == first["stop_tick"] == first["others"]["window_tick"]
        assert second["others"]["window_tick"] == body["window_tick"]
        s_tick, s_time, s_end = truth(snapshot, req, second["machine"])
        if second["entered"]:
            assert (second["entry_tick"], second["entry_time"], second["op_end_time"]) == (s_tick, s_time, s_end)
            assert s_tick <= body["window_tick"]
        else:
            assert second["pruned"] and second["stop_reason"] == "pruned" and second["entry_estimated"]
            assert s_tick > body["window_tick"]  # pruning was right: it enters later
        for o in body["options"]:
            assert {"work", "wait", "finished", "score"} <= set(o["others"])
        # the real session did not move and the same decision cannot be tested twice
        assert client.get(f"/sessions/{sid}").json()["ticks"] == tick
        again = whatif(client, sid, req, options).json()
        assert again["status"] == "skipped" and again["skipped_reason"] == "already-used"
        m = client.get(f"/sessions/{sid}/metrics").json()["whatif"]
        assert m["requests"] == 2 and m["ok"] == 1 and m["skipped"]["already-used"] == 1 and m["options_run"] == 2
        client.delete(f"/sessions/{sid}")
    finally:
        snapshot.unlink(missing_ok=True)


# ----- d) cap -----

def test_d_cap_gives_an_estimate(client: httpx.Client) -> None:
    tick, req, snapshot = find_decision(seed=7, nth=2)
    snapshot.unlink()
    sid = api_session(client, 7, tick)
    body = whatif(client, sid, req, list(req.candidates[:2]), max_ticks=5).json()
    assert body["status"] == "ok"
    for o in body["options"]:
        assert not o["entered"] and o["entry_estimated"] and o["op_end_estimated"]
        assert o["ticks_simulated"] <= 5
        assert o["cap_reached"] or o["pruned"]
        assert o["entry_tick"] >= o["stop_tick"] and o["op_end_time"] > o["entry_time"]
    assert next(o for o in body["options"] if o["machine"] == body["run_order"][0])["cap_reached"]
    assert client.get(f"/sessions/{sid}/metrics").json()["whatif"]["cap_reached"] >= 1
    client.delete(f"/sessions/{sid}")


# ----- e) no free what-if worker -----

def test_e_no_free_worker_answers_at_once(api: ApiServer, client: httpx.Client) -> None:
    tick1, req1, s1 = find_decision(seed=42, nth=4)
    tick2, req2, s2 = find_decision(seed=7, nth=4)
    s1.unlink()
    s2.unlink()
    sid1, sid2 = api_session(client, 42, tick1), api_session(client, 7, tick2)

    async def scenario() -> tuple[list[httpx.Response], httpx.Response, float]:
        async with httpx.AsyncClient(base_url=api.url, timeout=120) as ac:
            def body(req: DecisionRequest) -> dict[str, Any]:
                return {"product": req.who, "seq": req.seq, "options": list(req.candidates[2:4]), "max_ticks": 2000}
            busy = [asyncio.create_task(ac.post(f"/sessions/{sid}/what-if", json=body(req)))
                    for sid, req in ((sid1, req1), (sid2, req2))]
            await asyncio.sleep(0.4)  # both have borrowed their worker
            t0 = time.perf_counter()
            third = await ac.post(f"/sessions/{sid1}/what-if",
                                  json={"product": 99999, "seq": 1, "options": ["M2", "M3"]})
            latency = time.perf_counter() - t0
            return list(await asyncio.gather(*busy)), third, latency

    busy, third, latency = asyncio.run(scenario())
    print(f"\nno_free_worker answered in {1000 * latency:.1f} ms")
    assert third.status_code == 200
    assert third.json()["status"] == "skipped" and third.json()["skipped_reason"] == "no-free-worker"
    assert latency < 0.05
    assert all(r.status_code == 200 and r.json()["status"] in ("ok", "timeout") for r in busy), [r.text for r in busy]
    assert client.get(f"/sessions/{sid1}/metrics").json()["whatif"]["skipped"]["no-free-worker"] == 1
    for sid in (sid1, sid2):
        client.delete(f"/sessions/{sid}")


# ----- f) validation -----

def test_f_validation(client: httpx.Client) -> None:
    tick, req, snapshot = find_decision(seed=42, nth=4)
    with SimulationSession() as s:
        s.import_world(snapshot)
        finished = int(s._report('[who] of min-one-of products with [Product.State = "death"] [who]')) \
            if int(s._report('count products with [Product.State = "death"]')) else None
    snapshot.unlink()
    sid = api_session(client, 42, tick)
    ok = list(req.candidates[:2])
    incapable = next(m for m in ("M1", "M2", "M3", "M4", "M5", "M6", "M7") if m not in req.candidates)

    def post(**changes: Any) -> httpx.Response:
        payload = {"product": req.who, "seq": req.seq, "options": ok, "max_ticks": 50, **changes}
        return client.post(f"/sessions/{sid}/what-if", json=payload)

    for payload, code, error in (
        ({"product": 99999}, 422, "invalid_option"),
        ({"seq": req.seq + 1}, 409, "decision_not_pending"),
        ({"options": [ok[0], incapable]}, 422, "invalid_option"),
    ):
        r = post(**payload)
        assert r.status_code == code and r.json()["code"] == error, (payload, r.text)
        assert "unknown-product" in r.text or "seq" in r.text or "not-capable" in r.text
    if finished is not None:
        r = post(product=finished)
        assert r.status_code == 409 and "product-finished" in r.text
    assert post(options=[ok[0], ok[0]]).status_code == 422  # must be two different machines
    assert post(options=[ok[0]]).status_code == 422  # exactly two
    assert post(options=["M2", "M3", "M5"]).status_code == 422
    rule3 = api_session(client, 42, tick, rule=3)
    r = client.post(f"/sessions/{rule3}/what-if", json={"product": req.who, "seq": req.seq, "options": ok})
    assert r.status_code == 409 and r.json()["code"] == "rule4_required"
    m = client.get(f"/sessions/{sid}/metrics").json()["whatif"]
    assert m["invalid"] >= 3 and m["ok"] == 0
    for x in (sid, rule3):
        client.delete(f"/sessions/{x}")


def test_timeout_returns_what_is_ready(api: ApiServer, client: httpx.Client) -> None:
    tick, req, snapshot = find_decision(seed=42, nth=4)
    snapshot.unlink()
    sid = api_session(client, 42, tick)
    settings = api.app.state.settings
    previous = settings.whatif_timeout_s
    object.__setattr__(settings, "whatif_timeout_s", 0.6)
    try:
        body = whatif(client, sid, req, list(req.candidates[:2])).json()
    finally:
        object.__setattr__(settings, "whatif_timeout_s", previous)
    assert body["status"] == "timeout"
    assert any(o["timed_out"] for o in body["options"])
    assert body["timings_ms"]["total"] < 600 + 2500  # import + one chunk past the deadline at most
    client.delete(f"/sessions/{sid}")


def test_candidates_endpoint(client: httpx.Client) -> None:
    tick, req, snapshot = find_decision(seed=42, nth=4)
    snapshot.unlink()
    sid = api_session(client, 42, tick)
    r = client.get(f"/sessions/{sid}/candidates", params={"product": req.who, "seq": req.seq})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["valid"] and body["operation"] == req.operation and body["tick"] == tick
    assert sorted(c["machine"] for c in body["candidates"]) == sorted(req.candidates)
    bad = client.get(f"/sessions/{sid}/candidates", params={"product": req.who, "seq": req.seq + 1}).json()
    assert bad["valid"] is False and bad["reason"]
    assert client.get(f"/sessions/{sid}/candidates", params={"product": req.who}).status_code == 422  # seq required
    client.delete(f"/sessions/{sid}")


# ----- g) live session -----

def pending_from_state(c: httpx.Client, sid: str) -> list[tuple[int, int, list[str]]]:
    """Decisions available now: products in a machine whose next operation has >= 2 candidates."""
    state = c.get(f"/sessions/{sid}/state").json()
    busy = {m.get("product") for m in state["machines"]}
    found = []
    for p in state["products"]:
        seq = int(p["sequence_order"]) + 1
        if p["id"] in busy and seq < len(p["operations"]):
            cand = c.get(f"/sessions/{sid}/candidates", params={"product": p["id"], "seq": seq}).json()
            if cand["valid"] and len(cand["candidates"]) >= 2:
                found.append((p["id"], seq, [x["machine"] for x in cand["candidates"]]))
    return found


def test_g_whatif_does_not_slow_a_live_session(api: ApiServer, client: httpx.Client) -> None:
    sid = api_session(client, 42, 0)
    w = Watcher(api, sid)
    client.post(f"/sessions/{sid}/run", json={"mode": "live", "speed": 1})
    time.sleep(1.0)
    start = time.monotonic()
    tested, statuses = set(), []
    while time.monotonic() - start < 15:
        for product, seq, cands in pending_from_state(client, sid):
            if (product, seq) not in tested:
                tested.add((product, seq))
                r = client.post(f"/sessions/{sid}/what-if",
                                json={"product": product, "seq": seq, "options": cands[:2]})
                statuses.append(r.json().get("status", r.status_code) if r.status_code == 200 else r.status_code)
                break
        time.sleep(2.0)
    ticks = [(t, m["tick"]) for t, m in w.messages if m["type"] == "tick" and t >= start]
    rate = (ticks[-1][1] - ticks[0][1]) / (ticks[-1][0] - ticks[0][0])
    print(f"\nlive 1x with what-ifs {statuses}: {rate:.2f} ticks/s")
    assert statuses and "ok" in statuses
    assert abs(rate - 32.0) <= 32.0 * 0.05
    w.close()
    client.delete(f"/sessions/{sid}")


# ----- h) fast mode streams the state about once a second -----

def test_h_fast_progress_carries_state_once_a_second(api: ApiServer, client: httpx.Client) -> None:
    sid = api_session(client, 42, 0, rule=3)
    w = Watcher(api, sid)
    client.post(f"/sessions/{sid}/run", json={"mode": "fast"})
    finished = w.wait_for("finished", timeout_s=180)[0]
    progress = [(t, m) for t, m in w.messages if m["type"] == "progress"]
    with_state = [(t, m) for t, m in progress if "state" in m]
    assert with_state and "state" in progress[-1][1] and progress[-1][1]["state"]["tick"] == 10000
    gaps = [b[0] - a[0] for a, b in zip(with_state, with_state[1:-1])]  # the last one is forced
    assert all(g >= 0.9 for g in gaps), gaps  # at most once a second (every block if blocks take > 1 s)
    size = sum(len(json.dumps(m)) for _, m in progress)
    elapsed = progress[-1][0] - progress[0][0]
    print(f"\nfast: {len(progress)} progress, {len(with_state)} with state, {size / max(elapsed, 0.001) / 1024:.1f} KB/s")
    with SimulationSession() as direct:
        direct.setup(seed=42, rule=3)
        direct.run_to_end()
        assert finished["kpis"] == direct.kpis().as_dict()
    w.close()
    client.delete(f"/sessions/{sid}")


# ----- b) no interference (slow) -----

@pytest.mark.slow
def test_b_whatifs_do_not_change_the_session(client: httpx.Client) -> None:
    with_whatifs, plain = api_session(client, 42, 0), api_session(client, 42, 0)
    tested: set[tuple[int, int]] = set()
    for _ in range(20):  # 20 x 500 ticks; what-ifs on pending decisions along the way
        for product, seq, cands in pending_from_state(client, with_whatifs):
            if (product, seq) in tested:  # still in the same machine: already-used
                continue
            r = client.post(f"/sessions/{with_whatifs}/what-if",
                            json={"product": product, "seq": seq, "options": cands[:2]})
            assert r.status_code == 200 and r.json()["status"] in ("ok", "timeout"), r.text
            tested.add((product, seq))
            break
        for sid in (with_whatifs, plain):
            client.post(f"/sessions/{sid}/step", params={"n": 500}).raise_for_status()
    assert len(tested) >= 5
    kpis = [client.get(f"/sessions/{sid}/kpis").json() for sid in (with_whatifs, plain)]
    assert kpis[0]["ticks"] == 10000 and kpis[0] == kpis[1]
    for sid in (with_whatifs, plain):
        client.delete(f"/sessions/{sid}")
