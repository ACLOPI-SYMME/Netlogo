"""Point 7 (problem P6): slowdown of a 100,000-tick run, rule 3, seed 42. Measurement only.

Every 5000 ticks: ticks/s of the interval, products (total, alive, "death"), and the length of
EventFrameInfo and DataFrameInfo. Then: correlation of the time per tick with each variable, and
linear vs quadratic fits of the time per tick against the number of "death" products.
All readings are counts/lengths (no random numbers consumed).

Usage (inside the container):
    python scripts/l4/long_run_profile.py
"""

from __future__ import annotations

import argparse
import sys
import time
from typing import Any

import numpy as np

from common import RULE, SESSIONS_ROOT, configure_logging, environment_info, logger, save_json

from aclopi.sim import SimulationSession

VARIABLES = ("products_total", "products_alive", "products_death", "event_rows", "data_rows")


def snapshot(link: Any) -> dict[str, int]:
    return {
        "products_total": int(link.report("count products")),
        "products_alive": int(link.report('count products with [Product.State != "death"]')),
        "products_death": int(link.report('count products with [Product.State = "death"]')),
        "event_rows": int(link.report("length EventFrameInfo")),
        "data_rows": int(link.report("length DataFrameInfo")),
    }


def r_squared(y: np.ndarray, fitted: np.ndarray) -> float:
    ss_res = float(np.sum((y - fitted) ** 2))
    ss_tot = float(np.sum((y - y.mean()) ** 2))
    return 1 - ss_res / ss_tot if ss_tot else 0.0


def main() -> int:
    configure_logging()
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--horizon", type=int, default=100000)
    parser.add_argument("--interval", type=int, default=5000)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    rows: list[dict[str, Any]] = []
    with SimulationSession("long_run", results_root=SESSIONS_ROOT) as s:
        s.setup(seed=args.seed, rule=RULE, horizon_ticks=args.horizon)
        prev = snapshot(s.link)
        while True:
            wall0, cpu0 = time.perf_counter(), time.process_time()
            result = s.step(args.interval)
            wall, cpu = time.perf_counter() - wall0, time.process_time() - cpu0
            snap = snapshot(s.link)
            row = {
                "tick": result.ticks,
                "ticks_in_interval": result.advanced,
                "wall_s": round(wall, 2),
                "cpu_s": round(cpu, 2),
                "ticks_per_s": round(result.advanced / wall, 1) if result.advanced else None,
                "ms_per_tick": round(1000 * wall / result.advanced, 3) if result.advanced else None,
                **snap,
                # Interval averages, used for the fits.
                **{f"avg_{k}": (prev[k] + snap[k]) / 2 for k in VARIABLES},
            }
            if result.advanced and wall > 2 and cpu < 0.5 * wall:
                row["possibly_interrupted"] = True
                logger.warning("Interval ending at tick %d: wall %.1f s but CPU %.1f s", result.ticks, wall, cpu)
            rows.append(row)
            logger.info("tick %d: %.1f ticks/s, death=%d, events=%d", result.ticks, row["ticks_per_s"] or 0,
                        snap["products_death"], snap["event_rows"])
            prev = snap
            if result.finished:
                break
        stacked = int(s.link.report('count products with [Product.State = "death" and xcor = 2 and ycor = 2]'))

    data = [r for r in rows if r["ticks_in_interval"] == args.interval]
    y = np.array([r["ms_per_tick"] for r in data])
    correlations = {k: round(float(np.corrcoef([r[f"avg_{k}"] for r in data], y)[0, 1]), 3) for k in VARIABLES}
    death = np.array([r["avg_products_death"] for r in data])
    lin = np.polyfit(death, y, 1)
    quad = np.polyfit(death, y, 2)
    fits = {
        "linear": {"coef": [round(float(c), 6) for c in lin], "r2": round(r_squared(y, np.polyval(lin, death)), 4)},
        "quadratic": {"coef": [round(float(c), 8) for c in quad], "r2": round(r_squared(y, np.polyval(quad, death)), 4)},
    }

    print(f"\nLong run: {args.horizon} ticks, rule 3, seed {args.seed}, every {args.interval} ticks")
    print(f"{'tick':>7} {'ticks/s':>8} {'ms/tick':>8} {'total':>6} {'alive':>6} {'death':>6} {'EventFrameInfo':>14} {'DataFrameInfo':>13}")
    for r in rows:
        flag = "  (interrupted?)" if r.get("possibly_interrupted") else ""
        print(f"{r['tick']:>7} {r['ticks_per_s']!s:>8} {r['ms_per_tick']!s:>8} {r['products_total']:>6} {r['products_alive']:>6} "
              f"{r['products_death']:>6} {r['event_rows']:>14} {r['data_rows']:>13}{flag}")
    print("correlation of ms/tick with:", correlations)
    print("ms/tick vs death products:", fits)
    print(f"death products stacked at (2,2): {stacked} of {rows[-1]['products_death']}")
    path = save_json("long_run_profile", {"env": environment_info(), "rows": rows, "correlations": correlations,
                                          "fits_vs_death": fits, "death_stacked_at_2_2": stacked})
    print("Saved:", path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
