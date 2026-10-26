"""Rule 4 (AI Agent) checks: equivalence with rule 3 and a random decider.

1. Rule 4 with nobody answering the requests must reproduce rule 3 exactly: same KPIs, same
   Events CSV (hash with normalized line endings) and the same Data CSV except column 2
   (block 0, Reactivity.rule), which holds the rule name.
2. Rule 4 with a decider that picks a capable machine at random (Python's random, not
   NetLogo's) must run to the end; the decision log tells how many assignments came from the
   agent and how many from the rule 3 fallback.

Usage (from the repository root):
    python scripts/rule4_checks.py --horizons 10000 100000 --seeds 42 7
    python scripts/rule4_checks.py --skip-equivalence --decider-horizon 100000
"""

from __future__ import annotations

import argparse
import logging
import random
import sys
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from compare_baseline import compare_data_columns, sha256 as content_sha256

from aclopi.sim import SimulationSession
from aclopi.sim.decisions import (
    DecisionRequest,
    clear_decisions,
    decision_log,
    pending_decisions,
    run_until_decision,
    set_next_machine,
)

RULE_NAME_COLUMN = 2  # Data CSV, block 0: [time, Reactivity.rule, Modeling.Type, ...]

Decider = Callable[[DecisionRequest], str]


@dataclass
class RunOutput:
    rule: int
    seed: int
    horizon: int
    kpis: dict[str, Any]
    events_csv: Path
    data_csv: Path
    wall_s: float
    requests: int = 0
    answers: Counter = field(default_factory=Counter)  # set_next_machine result -> count
    sources: Counter = field(default_factory=Counter)  # decision log source -> count
    fallback_with_request: int = 0  # fallbacks for operations that had a request (several machines)


@dataclass
class Equivalence:
    kpi_differences: dict[str, tuple[Any, Any]]
    events_identical: bool
    data_rows: tuple[int, int]
    data_column_differences: dict[int, int]

    @property
    def ok(self) -> bool:
        return (
            not self.kpi_differences
            and self.events_identical
            and self.data_rows[0] == self.data_rows[1]
            and set(self.data_column_differences) <= {RULE_NAME_COLUMN}
        )


def exported(session: SimulationSession, rule: int) -> tuple[Path, Path]:
    """(Events, Data) CSVs written by ExportData for a rule ("R 3", "R 4", ...)."""
    results = session.directory / "Results"
    return results / "Events" / f"Event_100_Sto_R {rule}_0.csv", results / "Data" / f"Data_100_Sto_R {rule}_0.csv"


def run(
    session: SimulationSession,
    rule: int,
    seed: int,
    horizon: int,
    decider: Decider | None = None,
    poll: bool = True,
) -> RunOutput:
    """Run to the horizon.

    Rule 4: with poll, advance with run_until_decision, read every request, answer it with
    decider (if any) and clear the queue; without poll, run straight to the end (requests pile
    up unanswered). Rules 1-3 always run straight to the end.
    """
    session.setup(seed=seed, rule=rule, horizon_ticks=horizon)
    start = time.perf_counter()
    requests, answers = 0, Counter()
    if rule == 4 and poll:
        while True:
            result = run_until_decision(session, horizon)
            if result.pending:
                for request in pending_decisions(session):
                    requests += 1
                    if decider is not None:
                        answers[set_next_machine(session, request.who, decider(request), request.seq)] += 1
                clear_decisions(session)
            if result.finished:
                break
    else:
        session.run_to_end()
    wall = time.perf_counter() - start

    events, data = exported(session, rule)
    out = RunOutput(rule, seed, horizon, session.kpis().as_dict(), events, data, wall, requests, answers)
    if rule == 4:
        log = decision_log(session, clear=True)
        out.sources = Counter(d.source for d in log)
        out.fallback_with_request = sum(
            1 for d in log if d.source == "rule3-fallback" and d.operation not in SINGLE_MACHINE_OPERATIONS
        )
    return out


# Operations that only one machine can do (operations table in Set.operations): never requested.
SINGLE_MACHINE_OPERATIONS = {"O6", "O7", "O8", "O9"}


def random_decider(seed: int) -> Decider:
    rng = random.Random(seed)
    return lambda request: rng.choice(request.candidates)


def compare(reference: RunOutput, other: RunOutput) -> Equivalence:
    keys = sorted(set(reference.kpis) | set(other.kpis))
    kpi_differences = {k: (reference.kpis.get(k), other.kpis.get(k)) for k in keys if reference.kpis.get(k) != other.kpis.get(k)}
    rows, columns = compare_data_columns(reference.data_csv, other.data_csv)
    return Equivalence(
        kpi_differences=kpi_differences,
        events_identical=content_sha256(reference.events_csv) == content_sha256(other.events_csv),
        data_rows=rows,
        data_column_differences=columns,
    )


def report_equivalence(label: str, eq: Equivalence) -> None:
    print(f"  {label}:")
    print(f"    KPIs: {'identical' if not eq.kpi_differences else eq.kpi_differences}")
    print(f"    Events SHA-256: {'identical' if eq.events_identical else 'DIFFERENT'}")
    print(f"    Data rows: {eq.data_rows[0]} vs {eq.data_rows[1]}")
    for col, n in sorted(eq.data_column_differences.items()):
        tag = "rule name, expected" if col == RULE_NAME_COLUMN else "UNEXPECTED"
        print(f"    Data column {col}: {n} rows differ ({tag})")
    if not eq.data_column_differences:
        print("    Data: all columns identical")
    print(f"    Result: {'OK' if eq.ok else 'FAILED'}")


def main() -> int:
    logging.basicConfig(level=logging.WARNING)
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--seeds", type=int, nargs="+", default=[42, 7])
    parser.add_argument("--horizons", type=int, nargs="+", default=[10000, 100000])
    parser.add_argument("--skip-equivalence", action="store_true")
    parser.add_argument("--decider-horizon", type=int, default=100000)
    parser.add_argument("--decider-seed", type=int, default=42, help="model seed of the random-decider run")
    parser.add_argument("--skip-decider", action="store_true")
    args = parser.parse_args()

    ok = True
    with SimulationSession("rule4_checks") as session:
        rule3_wall: dict[tuple[int, int], float] = {}
        if not args.skip_equivalence:
            print("Rule 4 without decider vs rule 3")
            for horizon in args.horizons:
                for seed in args.seeds:
                    ref = run(session, 3, seed, horizon)
                    rule3_wall[(seed, horizon)] = ref.wall_s
                    print(f" seed {seed}, {horizon} ticks (rule 3: {ref.wall_s:.1f} s, finished {ref.kpis['finished']}):")
                    polled = run(session, 4, seed, horizon, poll=True)
                    eq = compare(ref, polled)
                    report_equivalence(
                        f"rule 4 polled with run_until_decision, {polled.requests} requests never answered "
                        f"({polled.wall_s:.1f} s, sources {dict(polled.sources)})", eq)
                    ok &= eq.ok
                    if horizon <= 10000:
                        plain = run(session, 4, seed, horizon, poll=False)
                        eq = compare(ref, plain)
                        report_equivalence(f"rule 4 run_to_end, requests never read ({plain.wall_s:.1f} s)", eq)
                        ok &= eq.ok

        if not args.skip_decider:
            seed, horizon = args.decider_seed, args.decider_horizon
            print(f"\nRule 4 with a random decider (Python random), seed {seed}, {horizon} ticks")
            out = run(session, 4, seed, horizon, decider=random_decider(seed))
            total = sum(out.sources.values())
            print(f"  finished run: ticks={out.kpis['ticks']} finished={out.kpis['finished']} wip={out.kpis['wip']} "
                  f"mean_flow={out.kpis['mean_flow_time']}")
            print(f"  requests: {out.requests}; answers: {dict(out.answers)}")
            print(f"  assignments: {total}; by source: {dict(out.sources)}; "
                  f"fallbacks on operations with a request: {out.fallback_with_request}")
            print(f"  wall: {out.wall_s:.1f} s", end="")
            if (seed, horizon) not in rule3_wall:
                ref = run(session, 3, seed, horizon)
                rule3_wall[(seed, horizon)] = ref.wall_s
            print(f" (rule 3, same seed and horizon: {rule3_wall[(seed, horizon)]:.1f} s)")
            ok &= out.kpis["ticks"] == horizon and out.answers.get("ok", 0) == out.requests
            ok &= out.fallback_with_request == 0

    print(f"\nOverall: {'OK' if ok else 'FAILED'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
