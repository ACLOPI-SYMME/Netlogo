"""Smoke test of the Docker Compose stack (docker-compose.yml; docs/deploy-local.md).

With the stack up (docker compose up -d):
1. upload a CSV of 8 products, save it as a set, run rule 4 / b1 in fast mode with that set and no
   seed; check all_products_done, makespan, decisions, the random seed kept, and the run in
   DynamoDB Local (GET /runs);
2. run rule 4 / agent live for 30 s; check decisions over WebSocket and a pace of ~32 ticks/s;
3. check that /health shows the agent.

    python scripts/l5/smoke_compose.py [--url http://localhost:8000]
The token is ACLOPI_AGENT_TOKEN from the environment or from .env. Prints one line per check.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path

import httpx

REPO_ROOT = Path(__file__).resolve().parents[2]
CSV = "type;priority\nA;80\ne;70\nT;\nI;95\nP;60\nB;80\nL;85\nA;100\n"


def token() -> str | None:
    value = os.environ.get("ACLOPI_AGENT_TOKEN", "").strip()
    env_file = REPO_ROOT / ".env"
    if not value and env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            if line.startswith("ACLOPI_AGENT_TOKEN="):
                value = line.split("=", 1)[1].strip()
    return value or None


def check(ok: bool, what: str, detail: object = "") -> None:
    print(f"[{'OK' if ok else 'FAIL'}] {what} {detail}".rstrip())
    if not ok:
        sys.exit(1)


def wait_ready(c: httpx.Client, timeout_s: float = 300) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            if c.get("/health/ready").status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(2)
    check(False, "platform ready")


def wait_state(c: httpx.Client, sid: str, states: tuple[str, ...], timeout_s: float) -> dict:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        info = c.get(f"/sessions/{sid}").json()
        if info["run_state"] in states:
            return info
        time.sleep(1)
    check(False, f"session reaches {states}", c.get(f"/sessions/{sid}").json()["run_state"])
    return {}


async def watch_live(ws_url: str, seconds: float) -> tuple[list[tuple[float, int]], list[dict]]:
    from websockets.asyncio.client import connect

    ticks, decisions = [], []
    async with connect(ws_url, max_size=None) as ws:
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            try:
                m = json.loads(await asyncio.wait_for(ws.recv(), end - time.monotonic()))
            except asyncio.TimeoutError:
                break
            if m["type"] == "tick":
                ticks.append((time.monotonic(), m["tick"]))
            elif m["type"] == "decision":
                decisions.append(m)
    return ticks, decisions


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://localhost:8000")
    args = parser.parse_args()
    t = token()
    headers = {"Authorization": f"Bearer {t}"} if t else {}
    with httpx.Client(base_url=args.url, timeout=60, headers=headers) as c:
        wait_ready(c)
        check(True, "platform ready (/health/ready 200)")

        # 1. CSV -> set -> rule 4 / b1, fast, no seed
        parsed = c.post("/product-sets/parse-csv", files={"file": ("smoke.csv", CSV.encode(), "text/csv")})
        check(parsed.status_code == 200 and parsed.json()["total"] == 8, "CSV of 8 products parsed", parsed.status_code)
        saved = c.post("/product-sets", json={"name": "smoke", "products": parsed.json()["products"]}).json()
        r = c.post("/sessions", json={"rule": 4, "strategy": "b1", "horizon_ticks": 200000, "product_set_id": saved["id"]})
        check(r.status_code == 201, "session rule 4 / b1 with the set", r.status_code)
        info = r.json()
        sid, seed = info["session_id"], info["parameters"]["seed"]
        check(info["seed_source"] == "random", "random seed drawn and kept", seed)
        t0 = time.monotonic()
        c.post(f"/sessions/{sid}/run", json={"mode": "fast"}).raise_for_status()
        info = wait_state(c, sid, ("finished", "failed"), timeout_s=900)
        check(info["run_state"] == "finished" and info["run_reason"] == "all_products_done", "fast run ended",
              f"{info['run_reason']} at tick {info['ticks']} in {time.monotonic() - t0:.0f} s")
        kpis = c.get(f"/sessions/{sid}/kpis").json()
        check(kpis["all_done"] and kpis["products_total"] == 8 and kpis["makespan_time"] is not None, "makespan",
              f"{kpis['makespan_time']} u.t. ({kpis['makespan_ticks']} ticks)")
        decisions = c.get(f"/sessions/{sid}/metrics").json()["decisions"]
        check(decisions["applied"] > 0 and decisions["late"] == 0, "decisions applied",
              f"{decisions['applied']} ({decisions['by_level']}), sources {decisions['sources']}")
        run_id = c.get(f"/sessions/{sid}").json()["last_run_id"]
        deadline = time.monotonic() + 15
        runs = []
        while time.monotonic() < deadline and not runs:
            runs = [x for x in c.get("/runs", params={"seed": seed}).json()["runs"] if x["run_id"] == run_id]
            time.sleep(0.5)
        check(bool(runs) and runs[0]["status"] == "finished" and runs[0]["seed_source"] == "random",
              "run saved in DynamoDB Local (/runs)", run_id)
        stored = c.get(f"/runs/{run_id}/decisions").json()
        check(len(stored) == decisions["applied"], "decisions saved", len(stored))
        c.delete(f"/sessions/{sid}")

        # 2. rule 4 / agent, live 30 s
        sid = c.post("/sessions", json={"rule": 4, "strategy": "agent", "seed": 42, "horizon_ticks": 10000}).json()["session_id"]
        ws_url = args.url.replace("http", "ws", 1) + f"/ws/sessions/{sid}"
        c.post(f"/sessions/{sid}/run", json={"mode": "live", "speed": 1}).raise_for_status()
        ticks, decided = asyncio.run(watch_live(ws_url, 30.0))
        steady = [x for x in ticks if x[0] - ticks[0][0] >= 2.0] if ticks else []
        rate = (steady[-1][1] - steady[0][1]) / (steady[-1][0] - steady[0][0]) if len(steady) > 1 else 0.0
        check(abs(rate - 32.0) <= 32.0 * 0.05, "live pace", f"{rate:.2f} ticks/s")
        check(len(decided) >= 1, "decisions over WebSocket", [(d["level"], d["late"]) for d in decided])
        c.delete(f"/sessions/{sid}")

        # 3. agent in /health
        agent = c.get("/health").json()["agent"]
        check(agent["configured"] and agent["status"] == "ok", "agent in /health", agent["status"])
    print("smoke test passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
