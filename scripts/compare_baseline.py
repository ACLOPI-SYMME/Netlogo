"""Compare a headless validation run against the committed baseline (tests/fixtures/baseline).

Checks, per rule:
- KPIs (same keys as validate_headless.py) must be identical.
- Events CSV must have the same SHA-256.
- Data CSV is compared column by column; only the columns in --allowed-data-columns may differ.

Usage (after scripts/run_all_rules.ps1):
    python scripts/compare_baseline.py
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BASELINE = REPO_ROOT / "tests" / "fixtures" / "baseline"
DEFAULT_RESULTS = REPO_ROOT / "results"

# Run fields that describe the execution, not the simulation outcome.
NON_KPI_FIELDS = {"run", "wall_seconds", "csv_files", "csv_sha256"}


@dataclass
class RuleComparison:
    rule: int
    baseline_kpis: dict[str, Any]
    current_kpis: dict[str, Any]
    kpi_differences: dict[str, tuple[Any, Any]]
    events_sha_baseline: str
    events_sha_current: str
    data_rows: tuple[int, int]
    data_column_differences: dict[int, int] = field(default_factory=dict)  # 1-based column -> differing rows
    data_allowed_columns: set[int] = field(default_factory=set)

    @property
    def events_identical(self) -> bool:
        return self.events_sha_baseline == self.events_sha_current

    @property
    def data_ok(self) -> bool:
        return self.data_rows[0] == self.data_rows[1] and set(self.data_column_differences) <= self.data_allowed_columns

    @property
    def ok(self) -> bool:
        return not self.kpi_differences and self.events_identical and self.data_ok


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def flatten_kpis(run: dict[str, Any]) -> dict[str, Any]:
    kpis = {k: v for k, v in run.items() if k not in NON_KPI_FIELDS and k != "utilization"}
    kpis.update({f"util_{m}": u for m, u in run["utilization"].items()})
    return kpis


def read_rows(path: Path) -> list[list[str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.reader(handle))


def compare_data_columns(baseline: Path, current: Path) -> tuple[tuple[int, int], dict[int, int]]:
    """Return ((rows baseline, rows current), {1-based column: number of rows that differ})."""
    rows_a, rows_b = read_rows(baseline), read_rows(current)
    differences: dict[int, int] = {}
    for row_a, row_b in zip(rows_a, rows_b):
        for col in range(max(len(row_a), len(row_b))):
            a = row_a[col] if col < len(row_a) else None
            b = row_b[col] if col < len(row_b) else None
            if a != b:
                differences[col + 1] = differences.get(col + 1, 0) + 1
    return (len(rows_a), len(rows_b)), differences


def compare_rule(
    rule: int,
    seed: int,
    baseline_dir: Path,
    current_summary: Path,
    allowed_data_columns: set[int],
) -> RuleComparison:
    current_run = json.loads(current_summary.read_text(encoding="utf-8"))["runs"][0]
    return compare_run(rule, seed, baseline_dir, current_run, allowed_data_columns)


def compare_run(
    rule: int,
    seed: int,
    baseline_dir: Path,
    current_run: dict[str, Any],
    allowed_data_columns: set[int],
) -> RuleComparison:
    """Compare one run (a validate_headless RunResult as dict) against the baseline of its rule."""
    base_dir = baseline_dir / f"rule{rule}"
    baseline_run = json.loads((base_dir / f"validation_{rule}_{seed}.json").read_text(encoding="utf-8"))["runs"][0]

    baseline_kpis, current_kpis = flatten_kpis(baseline_run), flatten_kpis(current_run)
    keys = sorted(set(baseline_kpis) | set(current_kpis))
    kpi_differences = {
        k: (baseline_kpis.get(k), current_kpis.get(k)) for k in keys if baseline_kpis.get(k) != current_kpis.get(k)
    }

    current_data = REPO_ROOT / current_run["csv_files"]["Data"]
    current_events = REPO_ROOT / current_run["csv_files"]["Events"]
    baseline_data = base_dir / current_data.name
    baseline_events = base_dir / current_events.name

    data_rows, column_differences = compare_data_columns(baseline_data, current_data)
    return RuleComparison(
        rule=rule,
        baseline_kpis=baseline_kpis,
        current_kpis=current_kpis,
        kpi_differences=kpi_differences,
        events_sha_baseline=sha256(baseline_events),
        events_sha_current=sha256(current_events),
        data_rows=data_rows,
        data_column_differences=column_differences,
        data_allowed_columns=allowed_data_columns,
    )


def format_kpi_table(comparisons: list[RuleComparison]) -> str:
    keys = ["ticks", "finished", "wip", "throughput", "mean_flow_time"] + sorted(
        k for k in comparisons[0].baseline_kpis if k.startswith("util_")
    )
    headers = ["rule", "source"] + [k.replace("util_", "U_").replace("mean_flow_time", "mean_flow") for k in keys] + ["equal"]
    rows = []
    for c in comparisons:
        for source, kpis in (("baseline", c.baseline_kpis), ("current", c.current_kpis)):
            cells = []
            for k in keys:
                v = kpis.get(k)
                cells.append("n/a" if v is None else f"{v:.5f}" if k == "throughput" else f"{v:.3f}" if isinstance(v, float) else str(v))
            rows.append([str(c.rule), source] + cells + ["" if source == "baseline" else ("yes" if not c.kpi_differences else "NO")])
    widths = [max(len(h), *(len(r[i]) for r in rows)) for i, h in enumerate(headers)]
    fmt = lambda cells: "  ".join(x.rjust(w) for x, w in zip(cells, widths))  # noqa: E731
    return "\n".join([fmt(headers), fmt(["-" * w for w in widths]), *(fmt(r) for r in rows)])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    parser.add_argument("--results", type=Path, default=DEFAULT_RESULTS)
    parser.add_argument("--rules", type=int, nargs="+", default=[1, 2, 3])
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--allowed-data-columns", type=int, nargs="*", default=[14])
    args = parser.parse_args()

    comparisons = [
        compare_rule(r, args.seed, args.baseline, args.results / f"validation_{r}_{args.seed}.json", set(args.allowed_data_columns))
        for r in args.rules
    ]

    print("KPIs: baseline vs current")
    print(format_kpi_table(comparisons))
    print()
    for c in comparisons:
        print(f"Rule {c.rule}:")
        if c.kpi_differences:
            print(f"  KPI differences: {c.kpi_differences}")
        status = "identical" if c.events_identical else "DIFFERENT"
        print(f"  Events SHA-256: {status} (baseline {c.events_sha_baseline[:16]}, current {c.events_sha_current[:16]})")
        print(f"  Data rows: baseline {c.data_rows[0]}, current {c.data_rows[1]}")
        if c.data_column_differences:
            for col, n in sorted(c.data_column_differences.items()):
                tag = "allowed" if col in c.data_allowed_columns else "NOT ALLOWED"
                print(f"  Data column {col}: {n} rows differ ({tag})")
        else:
            print("  Data: all columns identical")
        print(f"  Result: {'OK' if c.ok else 'FAILED'}")
    return 0 if all(c.ok for c in comparisons) else 1


if __name__ == "__main__":
    sys.exit(main())
