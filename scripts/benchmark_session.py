"""Benchmarks for SimulationSession.

--part clone : what-if cost at tick 3000 (per rule): export_world and import_world measured hot
               (2 warm-up + 10 timed repetitions, mean and max), and the time to advance a clone
               300 and 1000 ticks in a single step (5 repetitions each, from a fresh import).
--part blocks: full 10,000-tick run with step blocks of 1, 10, 32, 100 and 1000 ticks, and a
               100,000-tick run in a single block (with its KPIs).

Usage (from the repository root, with the venv active):
    python scripts/benchmark_session.py --part clone
    python scripts/benchmark_session.py --part blocks
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

from aclopi.sim import SimulationSession

REPO_ROOT = Path(__file__).resolve().parents[1]
RESULTS_DIR = REPO_ROOT / "results"
SESSIONS_ROOT = RESULTS_DIR / "sessions" / "benchmark"

logger = logging.getLogger("benchmark_session")


def stats(samples: list[float]) -> dict[str, float]:
    return {"mean_ms": round(1000 * statistics.mean(samples), 1), "max_ms": round(1000 * max(samples), 1)}


def bench_clone(rules: list[int], seed: int, clone_tick: int) -> list[dict[str, Any]]:
    rows = []
    with SimulationSession("clone_src", results_root=SESSIONS_ROOT) as src, SimulationSession(
        "clone_dst", results_root=SESSIONS_ROOT
    ) as dst:
        for rule in rules:
            src.setup(seed=seed, rule=rule)
            src.step(clone_tick)
            exports, imports = [], []
            path = None
            for i in range(12):
                t0 = time.perf_counter()
                new_path = src.export_world()
                t1 = time.perf_counter()
                dst.import_world(new_path, seed=seed)
                t2 = time.perf_counter()
                if path is not None:
                    path.unlink()
                path = new_path
                if i >= 2:  # first two are warm-up
                    exports.append(t1 - t0)
                    imports.append(t2 - t1)
            assert path is not None
            size_kib = round(path.stat().st_size / 1024)
            advance: dict[int, list[float]] = {300: [], 1000: []}
            for n in advance:
                for _ in range(5):
                    dst.import_world(path, seed=seed)
                    t0 = time.perf_counter()
                    dst.step(n)
                    advance[n].append(time.perf_counter() - t0)
            path.unlink()
            row = {
                "rule": rule,
                "tick": clone_tick,
                "world_kib": size_kib,
                "export": stats(exports),
                "import": stats(imports),
                "advance_300": stats(advance[300]),
                "advance_1000": stats(advance[1000]),
            }
            logger.info("Rule %d clone: %s", rule, row)
            rows.append(row)
    return rows


def run_blocks(session: SimulationSession, block: int) -> float:
    start = time.perf_counter()
    while not session.step(block).finished:
        pass
    return time.perf_counter() - start


def bench_blocks(rules: list[int], seed: int, blocks: list[int], long_horizon: int) -> list[dict[str, Any]]:
    rows = []
    with SimulationSession("blocks", results_root=SESSIONS_ROOT) as session:
        for rule in rules:
            session.setup(seed=seed, rule=rule)
            session.run_to_end()  # warm-up
            row: dict[str, Any] = {"rule": rule}
            reference = None
            for block in blocks:
                session.setup(seed=seed, rule=rule)
                row[f"block_{block}_s"] = round(run_blocks(session, block), 2)
                kpis = session.kpis()
                reference = reference or kpis
                if kpis != reference:
                    raise RuntimeError(f"Rule {rule}: block size {block} changed the KPIs")
                logger.info("Rule %d, block %d: %.2f s", rule, block, row[f"block_{block}_s"])
            session.setup(seed=seed, rule=rule, horizon_ticks=long_horizon)
            row[f"horizon_{long_horizon}_one_block_s"] = round(run_blocks(session, long_horizon), 2)
            row["long_run_kpis"] = session.kpis().as_dict()
            logger.info("Rule %d, %d ticks: %.2f s", rule, long_horizon, row[f"horizon_{long_horizon}_one_block_s"])
            rows.append(row)
    return rows


def print_clone(rows: list[dict[str, Any]]) -> None:
    print(f"\nClone at tick {rows[0]['tick']} (hot: 10 reps after 2 warm-up; advance: 5 reps), ms mean / max")
    print("rule  world_KiB        export        import   advance_300  advance_1000")
    for r in rows:
        cells = [f"{r[k]['mean_ms']:>6} / {r[k]['max_ms']:<6}" for k in ("export", "import", "advance_300", "advance_1000")]
        print(f"{r['rule']:>4}  {r['world_kib']:>9}  " + "  ".join(cells))


def print_blocks(rows: list[dict[str, Any]]) -> None:
    keys = [k for k in rows[0] if k.endswith("_s")]
    print("\nFull run wall time (s)")
    print("rule  " + "  ".join(k.removesuffix("_s") for k in keys))
    for r in rows:
        print(f"{r['rule']:>4}  " + "  ".join(f"{r[k]:>{len(k) - 2}}" for k in keys))
    print("\nKPIs of the long run")
    for r in rows:
        k = r["long_run_kpis"]
        util = " ".join(f"{m}={u:.3f}" for m, u in k["utilization"].items())
        flow = "n/a" if k["mean_flow_time"] is None else f"{k['mean_flow_time']:.1f}"
        print(f"rule {r['rule']}: ticks={k['ticks']} finished={k['finished']} wip={k['wip']} "
              f"throughput={k['throughput']:.5f} mean_flow={flow} {util}")


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--part", choices=("clone", "blocks"), required=True)
    parser.add_argument("--rules", type=int, nargs="+", default=[1, 2, 3])
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--clone-tick", type=int, default=3000)
    parser.add_argument("--blocks", type=int, nargs="+", default=[1, 10, 32, 100, 1000])
    parser.add_argument("--long-horizon", type=int, default=100000)
    args = parser.parse_args()

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    if args.part == "clone":
        rows = bench_clone(args.rules, args.seed, args.clone_tick)
        print_clone(rows)
    else:
        rows = bench_blocks(args.rules, args.seed, args.blocks, args.long_horizon)
        print_blocks(rows)
    out = RESULTS_DIR / f"benchmark_session_{args.part}.json"
    out.write_text(json.dumps({"seed": args.seed, "rows": rows}, indent=2), encoding="utf-8")
    print(f"Saved: {out.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
