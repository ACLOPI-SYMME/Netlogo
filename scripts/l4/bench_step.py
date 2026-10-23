"""Point 2: cost of SimulationSession.step before (4 NetLogo calls) and after (1 call, platform-step).

Full 10,000-tick run, rule 3, seed 42, with blocks of 1, 3, 10 and 32 ticks. The "before" variant
reproduces the previous implementation (ticks, command, ticks, terminado) on the same workspace.
Both variants must end with identical KPIs.
"""

from __future__ import annotations

import argparse
import sys
import time

from common import RULE, SESSIONS_ROOT, Monitor, configure_logging, environment_info, logger, looks_interrupted, save_json

from aclopi.sim import SimulationSession

LEGACY_COMMAND = (
    "let target ticks + {n} "
    'while [terminado = "No" and ticks < target] [ go ] '
    'if (terminado = "No" and ticks >= horizon-ticks) [ go ]'
)


def legacy_step(session: SimulationSession, n: int) -> bool:
    link = session.link
    before = int(link.report("ticks"))
    link.command(LEGACY_COMMAND.format(n=n))
    after = int(link.report("ticks"))
    del before, after  # values were returned to the caller in the previous implementation
    return str(link.report("terminado")) == "Si"


def timed_run(session: SimulationSession, block: int, legacy: bool, seed: int) -> tuple[float, dict, object]:
    session.setup(seed=seed, rule=RULE)
    with Monitor() as mon:
        if legacy:
            while not legacy_step(session, block):
                pass
        else:
            while not session.step(block).finished:
                pass
    return mon.result.wall_s, session.kpis().as_dict(), mon.result


def main() -> int:
    configure_logging()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--blocks", type=int, nargs="+", default=[1, 3, 10, 32])
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    rows = []
    with SimulationSession("bench_step", results_root=SESSIONS_ROOT) as session:
        timed_run(session, 1000, legacy=False, seed=args.seed)  # warm-up
        for block in args.blocks:
            row = {"block": block}
            kpis_seen = []
            for variant, legacy in (("before_4_calls", True), ("after_1_call", False)):
                for attempt in range(2):
                    wall, kpis, mon = timed_run(session, block, legacy, args.seed)
                    if not looks_interrupted(mon, expected_busy_cpus=1):
                        break
                    logger.warning("Block %d %s looked interrupted (cpu/wall=%.2f), repeating", block, variant, mon.cpu_per_wall)
                    row[f"{variant}_interrupted_retry"] = True
                row[f"{variant}_s"] = round(wall, 2)
                row[f"{variant}_cpu_per_wall"] = round(mon.cpu_per_wall, 2)
                kpis_seen.append(kpis)
                logger.info("block %d %s: %.2f s", block, variant, wall)
            row["speedup"] = round(row["before_4_calls_s"] / row["after_1_call_s"], 2)
            row["kpis_identical"] = kpis_seen[0] == kpis_seen[1]
            rows.append(row)

    print("\nstep(): full 10,000-tick run, rule 3, seed", args.seed)
    print(f"{'block':>5}  {'before (4 calls) s':>18}  {'after (1 call) s':>16}  {'speedup':>7}  KPIs equal")
    for r in rows:
        print(f"{r['block']:>5}  {r['before_4_calls_s']:>18}  {r['after_1_call_s']:>16}  {r['speedup']:>7}  {r['kpis_identical']}")
    path = save_json("bench_step", {"env": environment_info(), "rows": rows})
    print(f"Saved: {path}")
    return 0 if all(r["kpis_identical"] for r in rows) else 1


if __name__ == "__main__":
    sys.exit(main())
