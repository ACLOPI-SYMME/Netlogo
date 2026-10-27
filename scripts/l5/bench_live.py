"""L5.3 measurements, end to end over WebSocket (rule 3, Stochastic).

The API runs in this process (uvicorn in a thread, full pool: 5 session + 2 what-if workers,
warmed up) so the what-if scenario can call pool.whatif_from_session directly (the endpoint
arrives in L5.4). The WebSocket clients run in a separate process (this script with --client),
so measuring does not compete with the API for this process's GIL.

Scenarios:
  1. 5 live sessions at 1x, one client each, 60 s: ticks/s per session, max and p95 gap between
     updates received by the client.
  2. The same with a what-if every 3 s (export -> import into a what-if worker -> 1000 ticks).
  3. 4 live sessions + 1 fast run of 100,000 ticks: live rate, and time of the fast run.
  Plus mean message size per type and bandwidth per session.

    python scripts/l5/bench_live.py [--duration 60]
Results: results/l5/bench_live.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import statistics
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = REPO_ROOT / "results" / "l5"

logger = logging.getLogger("bench_live")


def pct(values: list[float], q: float) -> float:
    s = sorted(values)
    return s[min(len(s) - 1, int(round(q * (len(s) - 1))))]


# ----- client process -----

async def watch(url: str, sid: str, duration: float, until_finished: bool, out: dict[str, Any]) -> None:
    from websockets.asyncio.client import connect

    arrivals: list[tuple[float, int]] = []
    sizes: dict[str, list[int]] = {}
    total = 0
    finished_at = None
    t_start = time.monotonic()
    async with connect(f"{url}/ws/sessions/{sid}", max_size=None, open_timeout=60) as ws:
        while True:
            remaining = (600.0 if until_finished else duration) - (time.monotonic() - t_start)
            if remaining <= 0:
                break
            try:
                text = await asyncio.wait_for(ws.recv(), remaining)
            except asyncio.TimeoutError:
                break
            now = time.monotonic()
            m = json.loads(text)
            sizes.setdefault(m["type"], []).append(len(text))
            total += len(text)
            if m["type"] in ("tick", "progress"):
                arrivals.append((now, m["tick"]))
            if m["type"] == "finished":
                finished_at = now - t_start
                if until_finished:
                    break
            if m["type"] == "closed" or (m["type"] == "run_state" and m["run_state"] == "paused"):
                break  # scenario 3 pauses the live sessions when the fast run ends
    elapsed = time.monotonic() - t_start
    gaps = [b[0] - a[0] for a, b in zip(arrivals, arrivals[1:])]
    steady = [a for a in arrivals if a[0] - t_start >= 2.0] or arrivals  # skip the first 2 s
    rate = (steady[-1][1] - steady[0][1]) / (steady[-1][0] - steady[0][0]) if len(steady) > 1 else None
    out[sid] = {
        "elapsed_s": round(elapsed, 2),
        "updates": len(arrivals),
        "ticks_per_s": round(rate, 2) if rate else None,
        "gap_ms": {"mean": round(1000 * statistics.fmean(gaps), 1), "p95": round(1000 * pct(gaps, 0.95), 1),
                   "max": round(1000 * max(gaps), 1)} if gaps else None,
        "bytes": total,
        "bandwidth_kb_s": round(total / elapsed / 1024, 1),
        "mean_size_by_type": {k: round(statistics.fmean(v)) for k, v in sizes.items()},
        "count_by_type": {k: len(v) for k, v in sizes.items()},
        "finished_after_s": round(finished_at, 2) if finished_at else None,
    }


async def client_main(url: str, sessions: list[str], duration: float, until_finished: str | None) -> None:
    out: dict[str, Any] = {}
    await asyncio.gather(*(watch(url, sid, duration, sid == until_finished, out) for sid in sessions))
    print(json.dumps(out))


def run_clients(ws_url: str, sessions: list[str], duration: float, until_finished: str | None = None) -> subprocess.Popen[str]:
    args = [sys.executable, __file__, "--client", "--url", ws_url, "--duration", str(duration), "--sessions", *sessions]
    if until_finished:
        args += ["--until-finished", until_finished]
    return subprocess.Popen(args, stdout=subprocess.PIPE, text=True)


# ----- API side -----

def whatif_loop(pool: Any, sessions: list[str], stop: threading.Event, results: list[dict[str, float]]) -> None:
    i = 0
    while not stop.wait(3.0):
        sid = sessions[i % len(sessions)]
        i += 1
        t0 = time.perf_counter()
        try:
            with pool.whatif_from_session(sid) as whatif:
                t1 = time.perf_counter()
                whatif.request("step", n=1000)
            results.append({"clone_ms": round(1000 * (t1 - t0), 1), "total_ms": round(1000 * (time.perf_counter() - t0), 1)})
        except Exception as exc:  # noqa: BLE001
            results.append({"error": str(exc)})  # type: ignore[dict-item]


def scenario(http: Any, ws_url: str, live: int, duration: float, pool: Any = None, whatif: bool = False,
             fast_ticks: int = 0) -> dict[str, Any]:
    live_ids = [http.post("/sessions", json={"seed": 42 + i, "rule": 3}).json()["session_id"] for i in range(live)]
    fast_id = None
    if fast_ticks:
        fast_id = http.post("/sessions", json={"seed": 99, "rule": 3, "horizon_ticks": fast_ticks}).json()["session_id"]
    ids = live_ids + ([fast_id] if fast_id else [])
    # With a fast run, the live clients measure until it ends (the live sessions are paused then).
    proc = run_clients(ws_url, ids, 900.0 if fast_id else duration, until_finished=fast_id)
    time.sleep(3.0)  # clients connected and holding their snapshots
    for sid in live_ids:
        http.post(f"/sessions/{sid}/run", json={"mode": "live", "speed": 1}).raise_for_status()
    t_fast = time.monotonic()
    if fast_id:
        http.post(f"/sessions/{fast_id}/run", json={"mode": "fast"}).raise_for_status()
    stop, whatifs = threading.Event(), []
    thread = None
    if whatif:
        thread = threading.Thread(target=whatif_loop, args=(pool, live_ids, stop, whatifs), daemon=True)
        thread.start()
    fast_s = None
    if fast_id:
        while http.get(f"/sessions/{fast_id}").json()["run_state"] != "finished":
            time.sleep(0.2)
        fast_s = time.monotonic() - t_fast
        for sid in live_ids:  # stop the live clients' clocks at the same moment
            http.post(f"/sessions/{sid}/pause")
    out, _ = proc.communicate(timeout=900)
    stop.set()
    if thread:
        thread.join(30)
    clients = json.loads(out)
    for sid in ids:
        http.delete(f"/sessions/{sid}")
    live_rates = [clients[s]["ticks_per_s"] for s in live_ids]
    live_gaps = [clients[s]["gap_ms"] for s in live_ids]
    result: dict[str, Any] = {
        "live_sessions": live,
        "live_ticks_per_s": {"min": min(live_rates), "max": max(live_rates), "mean": round(statistics.fmean(live_rates), 2)},
        "live_gap_ms": {"p95_max": max(g["p95"] for g in live_gaps), "max": max(g["max"] for g in live_gaps),
                        "mean": round(statistics.fmean(g["mean"] for g in live_gaps), 1)},
        "live_bandwidth_kb_s": round(statistics.fmean(clients[s]["bandwidth_kb_s"] for s in live_ids), 1),
        "per_session": clients,
    }
    if whatif:
        ok = [w for w in whatifs if "total_ms" in w]
        result["whatif"] = {"count": len(ok), "errors": len(whatifs) - len(ok),
                            "clone_ms_mean": round(statistics.fmean(w["clone_ms"] for w in ok), 1) if ok else None,
                            "total_ms_mean": round(statistics.fmean(w["total_ms"] for w in ok), 1) if ok else None}
    if fast_id:
        result["fast"] = {"ticks": fast_ticks, "seconds": round(fast_s, 1),
                          "ticks_per_s": round(fast_ticks / fast_s), "client": clients[fast_id]}
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--client", action="store_true")
    parser.add_argument("--url")
    parser.add_argument("--sessions", nargs="*")
    parser.add_argument("--duration", type=float, default=60.0)
    parser.add_argument("--until-finished")
    parser.add_argument("--fast-ticks", type=int, default=100_000)
    args = parser.parse_args()
    if args.client:
        asyncio.run(client_main(args.url, args.sessions, args.duration, args.until_finished))
        return 0

    import httpx

    sys.path.insert(0, str(REPO_ROOT / "tests"))
    from apiserver import start_server  # the same in-process server the tests use

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
    for name in ("httpx", "aclopi", "uvicorn"):
        logging.getLogger(name).setLevel(logging.WARNING)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    work = OUT_DIR / "bench_live_work"
    server = start_server(work, 5, 2, warm=True, idle_s=3600)
    logger.info("API ready in %.1f s", server.startup["ready_s"])
    results: dict[str, Any] = {"cpu_count": os.cpu_count()}
    try:
        with httpx.Client(base_url=server.url, timeout=60) as http:
            results["live5"] = scenario(http, server.ws_url, 5, args.duration)
            logger.info("5 live: %s", {k: v for k, v in results["live5"].items() if k != "per_session"})
            results["live5_whatif"] = scenario(http, server.ws_url, 5, args.duration, pool=server.runtime.pool, whatif=True)
            logger.info("5 live + what-if: %s", {k: v for k, v in results["live5_whatif"].items() if k != "per_session"})
            results["live4_fast1"] = scenario(http, server.ws_url, 4, args.duration, fast_ticks=args.fast_ticks)
            logger.info("4 live + 1 fast: %s", {k: v for k, v in results["live4_fast1"].items() if k != "per_session"})
    finally:
        server.stop()
    out = OUT_DIR / "bench_live.json"
    out.write_text(json.dumps(results, indent=1), encoding="utf-8")
    print(json.dumps({k: {kk: vv for kk, vv in v.items() if kk != "per_session"} if isinstance(v, dict) else v
                      for k, v in results.items()}, indent=1))
    print(f"Saved: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
