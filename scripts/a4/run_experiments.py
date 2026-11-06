"""A4 experiments through the local API: strategies x cases, fast mode, one CSV per run.

    strategy  rule3 (rule 3) | b1 | b1b | agent (rule 4 + strategy; the platform calls the agent service)
    case      seed -> fixed list of N products generated with that seed (POST /product-sets/generate)
    scenario  --scenarios S0 S1 S2 S3 (default S0), with its default params (docs/scenarios.md)
The run ends when every product of the list is finished (or at --horizon). Per run it writes
results/a4/<strategy>_s<seed>_n<N>.csv (S0) or <strategy>_<scenario>_s<seed>_n<N>.csv with strategy,
scenario, seed, N, makespan_ticks, makespan_time, all_done, mean_flow_time, work_completed, scenario events
applied / skipped and the % of decisions per level. Resumable: runs whose CSV exists are
skipped. Prints progress at least every 30 s. With --events, the events of each run are also kept
(from the WebSocket) in <run>.events.jsonl, for scripts/a4/estimation_error.py.

Usage (platform API and agent already running):
    python scripts/a4/run_experiments.py --strategies rule3 b1 b1b agent --seeds 42 7 --n 30
    --parallel K runs K sessions at a time; --combined FILE also writes all the runs into one CSV.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import sys
import time
from pathlib import Path
from typing import Any

import httpx
import websockets

REPO_ROOT = Path(__file__).resolve().parents[2]
LEVELS = ("code-obvious", "code-fallback", "llm", "llm-what-if", "heuristic")
FIELDS = ["strategy", "scenario", "seed", "n", "session_id", "makespan_ticks", "makespan_time", "all_done",
          "mean_flow_time", "work_completed", "finished", "ticks", "run_state", "reason", "wall_s",
          "scenario_applied", "scenario_skipped", "decisions"] + [f"pct_{lv}" for lv in LEVELS]


def run_name(strategy: str, scenario: str, seed: int, n: int) -> str:
    return f"{strategy}_s{seed}_n{n}" if scenario == "S0" else f"{strategy}_{scenario}_s{seed}_n{n}"


async def collect_events(ws_url: str, path: Path, stop: asyncio.Event) -> None:
    with path.open("w", encoding="utf-8") as fh:
        async with websockets.connect(ws_url, max_size=None) as ws:
            while not stop.is_set():
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=1.0)
                except asyncio.TimeoutError:
                    continue
                except websockets.ConnectionClosed:
                    return
                msg = json.loads(raw)
                for ev in msg.get("events") or []:
                    fh.write(json.dumps(ev) + "\n")
                if msg.get("type") == "finished":
                    return


async def post_retrying(http: httpx.AsyncClient, url: str, body: dict[str, Any], tries: int = 60) -> dict[str, Any]:
    """POST, retrying while the API answers 503 (no free worker / starting) every 2 s."""
    for _ in range(tries - 1):
        r = await http.post(url, json=body)
        if r.status_code != 503:
            return r.raise_for_status().json()
        await asyncio.sleep(2)
    return (await http.post(url, json=body)).raise_for_status().json()


async def one_run(http: httpx.AsyncClient, api: str, strategy: str, scenario: str, seed: int, products: list[Any],
                  horizon: int, max_run_s: float, events_path: Path | None, progress: dict[str, Any]) -> dict[str, Any]:
    n = len(products)
    key = f"{strategy} {scenario} s{seed}"
    body: dict[str, Any] = {"seed": seed, "rule": 3 if strategy == "rule3" else 4, "horizon_ticks": horizon,
                            "products": products, "scenario": {"id": scenario}}
    if strategy != "rule3":
        body["strategy"] = strategy
    info = await post_retrying(http, "/sessions", body)
    sid = info["session_id"]
    stop, collector = asyncio.Event(), None
    try:
        if events_path is not None:
            ws_url = api.replace("http", "ws", 1) + f"/ws/sessions/{sid}"
            collector = asyncio.create_task(collect_events(ws_url, events_path, stop))
            await asyncio.sleep(0.3)
        start = time.monotonic()
        (await http.post(f"/sessions/{sid}/run", json={"mode": "fast"})).raise_for_status()
        while True:
            s = (await http.get(f"/sessions/{sid}")).json()
            progress["active"][key] = s.get("ticks")
            if s.get("run_state") in ("finished", "failed") or time.monotonic() - start > max_run_s:
                break
            await asyncio.sleep(0.5)
        wall = time.monotonic() - start
        kpis = (await http.get(f"/sessions/{sid}/kpis")).json()
        metrics = (await http.get(f"/sessions/{sid}/metrics")).json() if strategy != "rule3" else {}
        decisions = metrics.get("decisions") or {}
        pct = decisions.get("by_level_pct") or {}
        summary = s.get("scenario_summary") or {}
        row = {"strategy": strategy, "scenario": scenario, "seed": seed, "n": n, "session_id": sid,
               "makespan_ticks": kpis.get("makespan_ticks"), "makespan_time": kpis.get("makespan_time"),
               "all_done": kpis.get("all_done"), "mean_flow_time": kpis.get("mean_flow_time"),
               "work_completed": kpis.get("work_completed"), "finished": kpis.get("finished"), "ticks": kpis.get("ticks"),
               "run_state": s.get("run_state"), "reason": s.get("run_reason") or s.get("reason"),
               "wall_s": round(wall, 1), "scenario_applied": summary.get("applied"),
               "scenario_skipped": summary.get("skipped"), "decisions": decisions.get("applied", 0),
               **{f"pct_{lv}": pct.get(lv, 0.0) for lv in LEVELS}}
        if s.get("run_state") not in ("finished", "failed"):
            row["reason"] = f"cap {max_run_s:.0f} s reached"
        return row
    finally:
        progress["active"].pop(key, None)
        stop.set()
        if collector is not None:
            try:
                await asyncio.wait_for(collector, timeout=5)
            except (asyncio.TimeoutError, Exception):  # noqa: BLE001
                collector.cancel()
        await http.delete(f"/sessions/{sid}")


async def main_async(args: argparse.Namespace) -> int:
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    plan = [(st, sc, seed) for sc in args.scenarios for seed in args.seeds for st in args.strategies]
    progress: dict[str, Any] = {"done": 0, "ran": 0, "total": len(plan), "active": {}}
    t0 = time.monotonic()

    async def reporter() -> None:
        while True:
            await asyncio.sleep(30)
            el = time.monotonic() - t0
            done, ran = progress["done"], progress["ran"]
            # runs skipped (already done) cost nothing: the estimate uses only the runs made now
            eta = el / ran * (progress["total"] - done) if ran else float("nan")
            active = ", ".join(f"{k} tick {v}" for k, v in progress["active"].items()) or "-"
            print(f"[{el:6.0f} s] {done}/{progress['total']} runs done ({100 * done / progress['total']:.0f}%), "
                  f"now {active}, ~{eta:.0f} s left", flush=True)

    semaphore = asyncio.Semaphore(args.parallel)

    products: dict[int, list[Any]] = {}  # one list per seed, shared by its strategies

    async def run_one(http: httpx.AsyncClient, strategy: str, scenario: str, seed: int) -> None:
        name = run_name(strategy, scenario, seed, args.n)
        path = out / f"{name}.csv"
        if path.exists():
            print(f"skip {name} (done)")
            progress["done"] += 1
            return
        async with semaphore:
            events = out / f"{name}.events.jsonl" if args.events else None
            row = await one_run(http, args.api, strategy, scenario, seed, products[seed], args.horizon, args.max_run_s,
                                events, progress)
        with path.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=FIELDS)
            writer.writeheader()
            writer.writerow(row)
        progress["done"] += 1
        progress["ran"] += 1
        print(f"{name}: makespan_ticks {row['makespan_ticks']} all_done {row['all_done']} "
              f"decisions {row['decisions']} wall {row['wall_s']} s ({row['run_state']})", flush=True)

    rep = asyncio.create_task(reporter())
    async with httpx.AsyncClient(base_url=args.api, timeout=60) as http:
        # Generated before any run: generating needs a free worker, and the runs may take them all.
        for seed in dict.fromkeys(args.seeds):
            products[seed] = (await post_retrying(http, "/product-sets/generate", {"seed": seed, "count": args.n}))["products"]
        await asyncio.gather(*(run_one(http, strategy, scenario, seed) for strategy, scenario, seed in plan))
    rep.cancel()
    if args.combined:
        rows = []
        for strategy, scenario, seed in plan:
            with (out / f"{run_name(strategy, scenario, seed, args.n)}.csv").open(newline="", encoding="utf-8") as fh:
                rows += [{**r, "scenario": r.get("scenario") or "S0"} for r in csv.DictReader(fh)]
        with Path(args.combined).open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=FIELDS)
            writer.writeheader()
            writer.writerows(rows)
        print(f"written {args.combined} ({len(rows)} runs)")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--api", default="http://127.0.0.1:8000")
    parser.add_argument("--strategies", nargs="+", default=["rule3", "b1", "b1b", "agent"])
    parser.add_argument("--seeds", type=int, nargs="+", default=[42])
    parser.add_argument("--scenarios", nargs="+", default=["S0"], help="scenario ids, each with its default params")
    parser.add_argument("--n", type=int, default=30)
    parser.add_argument("--horizon", type=int, default=1_000_000)
    parser.add_argument("--max-run-s", type=float, default=180.0, help="wall-clock cap per run")
    parser.add_argument("--out", default=str(REPO_ROOT / "results" / "a4"))
    parser.add_argument("--events", action="store_true", help="keep the events of each run (WebSocket)")
    parser.add_argument("--parallel", type=int, default=1,
                        help="runs at the same time (the API needs as many session workers: ACLOPI_N_SESSION_WORKERS)")
    parser.add_argument("--combined", help="also write every run of the plan into this one CSV")
    return asyncio.run(main_async(parser.parse_args()))


if __name__ == "__main__":
    sys.exit(main())
