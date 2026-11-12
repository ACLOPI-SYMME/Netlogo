"""Smoke test of the Docker Compose stack (docker-compose.yml; docs/deploy-local.md).

With the stack up (docker compose up -d --build), or starting it with --up:
1. upload a CSV of 8 products, save it as a set, run rule 4 / b1 in fast mode with that set and no
   seed; check all_products_done, makespan, decisions, the random seed kept, and the run in
   DynamoDB Local (GET /runs);
2. run rule 4 / agent live for 30 s; check decisions over WebSocket and a pace of ~32 ticks/s;
3. check that /health shows Línea A's agent (kind real, http://agent:8100) answering;
4. "Optimize order" with a list of 8 varied products (rule 3): at least one round of the AI;
5. with --down: stop the whole stack (docker compose down) and check that no container of the project is left.

    python scripts/l5/smoke_compose.py [--url http://localhost:8000] [--up] [--down]
The token is ACLOPI_AGENT_TOKEN from the environment or from .env. Prints one line per check.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
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
    t0 = time.monotonic()
    last = t0
    while time.monotonic() - t0 < timeout_s:
        try:
            if c.get("/health/ready").status_code == 200:
                return
        except httpx.HTTPError:
            pass
        if time.monotonic() - last >= 30:
            last = time.monotonic()
            print(f"  waiting for the platform: {last - t0:.0f} s of at most {timeout_s:.0f} s", flush=True)
        time.sleep(2)
    check(False, "platform ready")


def stack(action: str) -> None:
    """docker compose up -d --build / docker compose down --remove-orphans."""
    cmd = ["docker", "compose", "up", "-d", "--build"] if action == "up" else ["docker", "compose", "down", "--remove-orphans"]
    t0 = time.monotonic()
    done = subprocess.run(cmd, cwd=REPO_ROOT, capture_output=True, text=True)
    check(done.returncode == 0, f"docker compose {action}",
          f"{time.monotonic() - t0:.0f} s" + ("" if done.returncode == 0 else f": {done.stderr[-500:]}"))


def project_containers() -> list[str]:
    out = subprocess.run(["docker", "ps", "-a", "--filter", "label=com.docker.compose.project=aclopi",
                          "--format", "{{.Names}}"], capture_output=True, text=True, check=True).stdout
    listed = subprocess.run(["docker", "compose", "ps", "-a", "-q"], cwd=REPO_ROOT,
                            capture_output=True, text=True, check=True).stdout
    return sorted(set(out.split()) | set(listed.split()))


def optimize_order(c: httpx.Client) -> None:
    products = [{"type": t, "priority": 80} for t in "AEIBTLPA"]  # 8 products, every type
    r = c.post("/sessions", json={"rule": 3, "seed": 42, "horizon_ticks": 200000, "products": products})
    check(r.status_code == 201, "session for optimize order (rule 3, 8 products)", r.status_code)
    sid = r.json()["session_id"]
    r = c.post(f"/sessions/{sid}/optimize-order", json={})
    check(r.status_code == 202, "optimize order started", r.status_code)
    t0 = last = time.monotonic()
    while (o := c.get(f"/sessions/{sid}/optimize-order").json())["status"] not in ("done", "cancelled", "failed"):
        if time.monotonic() - t0 > 600:
            check(False, "optimize order ends in 10 min", o["status"])
        if time.monotonic() - last >= 30:
            last = time.monotonic()
            print(f"  optimize order: {o['status']}, round {o['round']} of {o['rounds']}, {o['progress_pct']} % "
                  f"({last - t0:.0f} s)", flush=True)
        time.sleep(2)
    ai = [e for e in o["evaluated"] if e["origin"] == "ai"]
    check(o["status"] == "done" and o["warning"] is None and len(o["rounds_info"]) >= 1 and ai,
          "optimize order: at least one round of the AI",
          f"{len(o['rounds_info'])} round(s), {len(o['evaluated'])} orders, best {o['evaluated'][o['best']]['label']} "
          f"({o['evaluated'][o['best']]['makespan_ticks']} ticks) in {time.monotonic() - t0:.0f} s; warning {o['warning']}")
    c.delete(f"/sessions/{sid}")


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
    parser.add_argument("--up", action="store_true", help="start the stack with docker compose up -d --build first")
    parser.add_argument("--down", action="store_true", help="stop the whole stack at the end and check that nothing is left")
    args = parser.parse_args()
    if args.up:
        stack("up")
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

        # 3. agent in /health: which one (kind, from the URL) and where
        agent = c.get("/health").json()["agent"]
        check(agent["configured"] and agent["status"] == "ok", "agent in /health", agent["status"])
        check(agent["kind"] == "real" and agent["url"] == "http://agent:8100", "Línea A's agent in /health",
              f"{agent['kind']} at {agent['url']}")

        # 4. optimize order: at least one round of the AI (POST /sequence/propose answers)
        optimize_order(c)
    if args.down:
        stack("down")
        left = project_containers()
        check(not left, "nothing of the project left after down (docker compose ps -a)", left)
    print("smoke test passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
