"""L5.2 measurements: HTTP latency of step(3) and state with 1 and with 5 active sessions.

Starts `python -m aclopi.api` as a child process (full platform: 5 + 2 workers), waits for
/health/ready, measures from a client in this process and stops the API with a normal shutdown.
Then repeats the same load straight through a WorkerPool's queues (1 and 5 threads), so HTTP and
queue latency are compared under the same concurrency.
Rule 3, Stochastic. Results in results/l5/bench_api.json, next to the L5.1 queue latency
(results/l5/bench_workers.json) when that file exists.

    python scripts/l5/bench_api.py [--reps 500] [--port 8000]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import signal
import statistics
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

import httpx

REPO_ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = REPO_ROOT / "results" / "l5"

logger = logging.getLogger("bench_api")


def summary(values_s: list[float]) -> dict[str, float]:
    ms = sorted(1000 * v for v in values_s)
    p95 = ms[min(len(ms) - 1, int(round(0.95 * (len(ms) - 1))))]
    return {"mean_ms": round(statistics.fmean(ms), 3), "p95_ms": round(p95, 3), "max_ms": round(ms[-1], 3), "n": len(ms)}


def start_api(port: int) -> tuple[subprocess.Popen[bytes], float]:
    env = dict(os.environ, ACLOPI_API_PORT=str(port), ACLOPI_API_HOST="127.0.0.1")
    log = open(OUT_DIR / "bench_api_server.log", "wb")  # noqa: SIM115 - closed with the process
    flags = subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0
    t0 = time.perf_counter()
    proc = subprocess.Popen([sys.executable, "-m", "aclopi.api"], cwd=REPO_ROOT, env=env, stdout=log, stderr=log,
                            creationflags=flags)
    url = f"http://127.0.0.1:{port}"
    with httpx.Client(base_url=url, timeout=5) as c:
        while True:
            if proc.poll() is not None:
                raise RuntimeError(f"API exited with code {proc.returncode}; see {log.name}")
            try:
                if c.get("/health/ready").status_code == 200:
                    break
            except httpx.TransportError:
                pass
            time.sleep(0.25)
    return proc, time.perf_counter() - t0


def stop_api(proc: subprocess.Popen[bytes]) -> int:
    proc.send_signal(signal.CTRL_BREAK_EVENT if sys.platform == "win32" else signal.SIGINT)
    try:
        return proc.wait(120)
    except subprocess.TimeoutExpired:
        proc.kill()
        return proc.wait()


async def client_loop(ac: httpx.AsyncClient, sid: str, reps: int) -> tuple[list[float], list[float]]:
    steps, states = [], []
    for _ in range(reps):
        t0 = time.perf_counter()
        r = await ac.post(f"/sessions/{sid}/step", params={"n": 3})
        steps.append(time.perf_counter() - t0)
        r.raise_for_status()
        t0 = time.perf_counter()
        r = await ac.get(f"/sessions/{sid}/state")
        states.append(time.perf_counter() - t0)
        r.raise_for_status()
    return steps, states


async def measure(url: str, n_sessions: int, reps: int) -> dict[str, Any]:
    limits = httpx.Limits(max_connections=n_sessions + 2, max_keepalive_connections=n_sessions + 2)
    async with httpx.AsyncClient(base_url=url, timeout=60, limits=limits) as ac:
        sids = []
        for i in range(n_sessions):
            r = await ac.post("/sessions", json={"seed": 42 + i, "rule": 3, "modeling_type": "Stochastic"})
            r.raise_for_status()
            sids.append(r.json()["session_id"])
        for sid in sids:  # warm the HTTP path and move past the empty plant
            (await ac.post(f"/sessions/{sid}/step", params={"n": 300})).raise_for_status()
        t0 = time.perf_counter()
        results = await asyncio.gather(*(client_loop(ac, sid, reps) for sid in sids))
        wall = time.perf_counter() - t0
        for sid in sids:
            await ac.delete(f"/sessions/{sid}")
    steps = [v for s, _ in results for v in s]
    states = [v for _, s in results for v in s]
    return {"sessions": n_sessions, "reps_per_session": reps, "wall_s": round(wall, 2),
            "step3": summary(steps), "state": summary(states)}


def queue_loop(handle: Any, reps: int, steps: list[float], states: list[float]) -> None:
    for _ in range(reps):
        t0 = time.perf_counter()
        handle.request("step", n=3)
        steps.append(time.perf_counter() - t0)
        t0 = time.perf_counter()
        handle.request("state")
        states.append(time.perf_counter() - t0)


def measure_queue(n_sessions_list: list[int], reps: int) -> dict[str, Any]:
    """Same load straight through the WorkerPool queues (no HTTP), one thread per session."""
    from aclopi.workers import WorkerPool

    out: dict[str, Any] = {}
    with WorkerPool() as pool:
        for n_sessions in n_sessions_list:
            handles = []
            for i in range(n_sessions):
                h = pool.acquire_session(f"bench{n_sessions}_{i}")
                h.request("setup", seed=42 + i, rule=3)
                h.request("step", n=300)
                handles.append(h)
            steps: list[float] = []
            states: list[float] = []
            threads = [threading.Thread(target=queue_loop, args=(h, reps, steps, states)) for h in handles]
            t0 = time.perf_counter()
            for t in threads:
                t.start()
            for t in threads:
                t.join()
            wall = time.perf_counter() - t0
            for i in range(n_sessions):
                pool.release_session(f"bench{n_sessions}_{i}")
            out[f"queue_{n_sessions}_sessions"] = {"sessions": n_sessions, "reps_per_session": reps,
                                                   "wall_s": round(wall, 2), "step3": summary(steps),
                                                   "state": summary(states)}
            logger.info("queue, %d sessions: %s", n_sessions, out[f"queue_{n_sessions}_sessions"])
    return out


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
    logging.getLogger("httpx").setLevel(logging.WARNING)  # one line per request would load the client
    parser = argparse.ArgumentParser()
    parser.add_argument("--reps", type=int, default=500)
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    url = f"http://127.0.0.1:{args.port}"

    proc, ready_s = start_api(args.port)
    logger.info("API ready %.1f s after the process started", ready_s)
    try:
        one = asyncio.run(measure(url, 1, args.reps))
        logger.info("1 session: %s", one)
        five = asyncio.run(measure(url, 5, args.reps))
        logger.info("5 sessions: %s", five)
    finally:
        code = stop_api(proc)
        logger.info("API stopped with exit code %s", code)

    result: dict[str, Any] = {"process_to_ready_s": round(ready_s, 1), "http_1_session": one,
                              "http_5_sessions": five, "api_exit_code": code}
    result.update(measure_queue([1, 5], args.reps))
    l51 = OUT_DIR / "bench_workers.json"
    if l51.exists():
        queue = json.loads(l51.read_text(encoding="utf-8")).get("latency_queue", {})
        result["l51_queue"] = {"step3": queue.get("step3"), "state": queue.get("state")}
    out = OUT_DIR / "bench_api.json"
    out.write_text(json.dumps(result, indent=1), encoding="utf-8")
    print(json.dumps(result, indent=1))
    print(f"Saved: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
