"""L5.4 measurements (rule 4 without a decider = rule 3; Stochastic).

1. What-ifs with 5 live sessions at 1x running: an agent-like client takes pending decisions
   (products in a machine, candidates from GET /candidates) of the live sessions and asks
   POST /what-if with the first two candidates, one after the other, for --duration seconds.
   Reports: duration of the whole what-if (2 options) and of the first option alone (one copy:
   import + advance), mean/p95/max; ticks each copy advanced until the product entered; how often
   the cap, a stall, pruning or the timeout happened; and the live rate meanwhile.
2. Bandwidth of the fast mode with platform-state once a second (one fast run, one WebSocket client).

The API runs in this process (as in bench_live.py); WebSocket clients run in a child process.

    python scripts/l5/bench_whatif.py [--duration 120] [--fast-ticks 30000]
Results: results/l5/bench_whatif.json
"""

from __future__ import annotations

import argparse
import json
import logging
import statistics
import sys
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = REPO_ROOT / "results" / "l5"
sys.path.insert(0, str(REPO_ROOT / "tests"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

logger = logging.getLogger("bench_whatif")


def stats(values: list[float]) -> dict[str, float] | None:
    if not values:
        return None
    s = sorted(values)
    return {"mean": round(statistics.fmean(s), 1), "p95": round(s[min(len(s) - 1, int(round(0.95 * (len(s) - 1))))], 1),
            "max": round(s[-1], 1), "n": len(s)}


def pending(http: Any, sid: str) -> list[tuple[int, int, list[str]]]:
    state = http.get(f"/sessions/{sid}/state").json()
    busy = {m.get("product") for m in state["machines"]}
    out = []
    for p in state["products"]:
        seq = int(p["sequence_order"]) + 1
        if p["id"] in busy and seq < len(p["operations"]):
            c = http.get(f"/sessions/{sid}/candidates", params={"product": p["id"], "seq": seq}).json()
            if c["valid"] and len(c["candidates"]) >= 2:
                out.append((p["id"], seq, [x["machine"] for x in c["candidates"]]))
    return out


def whatif_load(http: Any, live: list[str], duration: float) -> dict[str, Any]:
    t_ticks0 = {sid: (time.monotonic(), http.get(f"/sessions/{sid}").json()["ticks"]) for sid in live}
    used: set[tuple[str, int, int]] = set()
    results, errors = [], []
    start = time.monotonic()
    i = 0
    while time.monotonic() - start < duration:
        sid = live[i % len(live)]
        i += 1
        for product, seq, cands in pending(http, sid):
            if (sid, product, seq) in used:
                continue
            used.add((sid, product, seq))
            r = http.post(f"/sessions/{sid}/what-if", json={"product": product, "seq": seq, "options": cands[:2]})
            if r.status_code == 200:
                results.append(r.json())
            else:
                errors.append((r.status_code, r.json().get("code")))
            break
        else:
            time.sleep(0.2)
    rates = {}
    for sid in live:
        t0, k0 = t_ticks0[sid]
        rates[sid] = round((http.get(f"/sessions/{sid}").json()["ticks"] - k0) / (time.monotonic() - t0), 2)
    ran = [r for r in results if r["status"] in ("ok", "timeout")]
    options = [o for r in ran for o in r["options"] if not o.get("skipped") and o.get("stop_reason") != "error"]
    firsts = [next(o for o in r["options"] if o["machine"] == r["run_order"][0]) for r in ran]
    return {
        "requests": len(results) + len(errors),
        "status": {s: sum(r["status"] == s for r in results) for s in ("ok", "timeout", "skipped", "error")},
        "skipped_reasons": {k: sum(r.get("skipped_reason") == k for r in results)
                            for k in ("no-free-worker", "already-used", "plant-saturated")},
        "http_errors": errors,
        "duration_2_options_ms": stats([r["timings_ms"]["total"] for r in ran]),
        "duration_first_option_ms": stats([o["duration_ms"] for o in firsts if o.get("duration_ms")]),
        "export_ms": stats([r["timings_ms"]["export"] for r in ran]),
        "import_ms_per_option": stats([o["import_ms"] for o in options if o.get("import_ms")]),
        "ticks_to_entry": stats([o["entry_tick"] - (o["stop_tick"] - o["ticks_simulated"]) for o in options
                                 if o["entered"]]),
        "first_copy_entered_share": round(sum(o["entered"] for o in firsts) / len(firsts), 3) if firsts else None,
        "options": len(options),
        "cap_reached": sum(o["cap_reached"] for o in options),
        "stalled": sum(o["stalled"] for o in options),
        "pruned": sum(o["pruned"] for o in options),
        "timed_out": sum(o["timed_out"] for o in options),
        "would_skip_saturated": sum(bool(r.get("would_skip_saturated")) for r in ran),
        "live_ticks_per_s": {"min": min(rates.values()), "max": max(rates.values()),
                             "mean": round(statistics.fmean(rates.values()), 2)},
    }


def main() -> int:
    import httpx
    from apiserver import start_server
    from bench_live import run_clients

    parser = argparse.ArgumentParser()
    parser.add_argument("--duration", type=float, default=120.0)
    parser.add_argument("--fast-ticks", type=int, default=30000)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
    for name in ("httpx", "aclopi", "uvicorn"):
        logging.getLogger(name).setLevel(logging.WARNING)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    server = start_server(OUT_DIR / "bench_whatif_work", 5, 2, warm=True, idle_s=3600)
    logger.info("API ready in %.1f s", server.startup["ready_s"])
    results: dict[str, Any] = {}
    try:
        with httpx.Client(base_url=server.url, timeout=120) as http:
            live = [http.post("/sessions", json={"seed": 42 + i, "rule": 4}).json()["session_id"] for i in range(5)]
            for sid in live:
                http.post(f"/sessions/{sid}/run", json={"mode": "live", "speed": 1}).raise_for_status()
            time.sleep(5.0)
            results["whatif_with_5_live"] = whatif_load(http, live, args.duration)
            logger.info("what-if: %s", results["whatif_with_5_live"])
            for sid in live:
                http.delete(f"/sessions/{sid}")
            # fast mode bandwidth with the state about once a second
            fast = http.post("/sessions", json={"seed": 99, "rule": 3, "horizon_ticks": args.fast_ticks}).json()["session_id"]
            proc = run_clients(server.ws_url, [fast], 900.0, until_finished=fast)
            time.sleep(3.0)
            http.post(f"/sessions/{fast}/run", json={"mode": "fast"}).raise_for_status()
            out, _ = proc.communicate(timeout=900)
            client = json.loads(out)[fast]
            results["fast_bandwidth"] = {"ticks": args.fast_ticks, **client}
            logger.info("fast: %s", results["fast_bandwidth"])
            http.delete(f"/sessions/{fast}")
    finally:
        server.stop()
    path = OUT_DIR / "bench_whatif.json"
    path.write_text(json.dumps(results, indent=1), encoding="utf-8")
    print(json.dumps(results, indent=1))
    print(f"Saved: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
