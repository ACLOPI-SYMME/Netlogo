"""Validate that the original Paper.nlogo model runs deterministically in headless mode.

For a given rule, seed and modeling type, the model is run --runs times with the same
seed. Each run goes until ExportData has written its CSVs (tick 10000). KPIs and the
SHA-256 of the exported CSVs must be identical across runs.

Optionally (--compare-csv) the exported CSVs are compared against those of a GUI run.

Usage (from the repository root, with the venv active):
    python scripts/validate_headless.py --rule 1 --seed 42
    python scripts/validate_headless.py --rule 1 --seed 42 --compare-csv <gui_results_dir>
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import shutil
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from aclopi.sim.kpis import compute_kpis

REPO_ROOT = Path(__file__).resolve().parents[1]
MODEL_DIR = REPO_ROOT / "model"
MODEL_PATH = MODEL_DIR / "Paper.nlogo"
RESULTS_DIR = REPO_ROOT / "results"
VALIDATION_DIR = RESULTS_DIR / "validation"

# Exact values of the model choosers (Paper.nlogo interface section).
RULES = {
    1: "Rule 1 - Random Machine",
    2: "Rule 2 - Nearest Machine",
    3: "Rule 3 - Potential Fields",
}
MODELING_TYPES = ("Deterministic", "Stochastic")

FINAL_TICKS = 10000
# go stops (and exports) on the call made with ticks = 10000, i.e. call number 10001.
# The cap only prevents an endless loop if the model never sets terminado to "Si".
GO_CALL_CAP = FINAL_TICKS + 10
TICK_DURATION = 0.31

# Same file-name expression used by ExportData (Paper.nlogo, lines 160-161).
CSV_NAME_REPORTER = (
    '(word "_" Interval.Logs "_" substring Modeling.type 0 3 "_R" '
    'substring Reactivity.Rule 4 6 "_" behaviorspace-run-number ".csv")'
)

logger = logging.getLogger("validate_headless")


@dataclass
class RunResult:
    run: int
    ticks: int
    simulated_time: float
    finished: int
    wip: int
    throughput: float
    mean_flow_time: float | None
    utilization: dict[str, float]
    wall_seconds: float
    csv_files: dict[str, str]
    csv_sha256: dict[str, str] = field(default_factory=dict)

    def kpis(self) -> dict[str, Any]:
        """Values that must be identical across runs with the same seed."""
        return {
            "ticks": self.ticks,
            "simulated_time": self.simulated_time,
            "finished": self.finished,
            "wip": self.wip,
            "throughput": self.throughput,
            "mean_flow_time": self.mean_flow_time,
            **{f"util_{m}": u for m, u in self.utilization.items()},
            **{f"sha256_{k}": h for k, h in self.csv_sha256.items()},
        }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--rule", type=int, choices=sorted(RULES), required=True)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--modeling-type", choices=MODELING_TYPES, default="Stochastic")
    parser.add_argument("--runs", type=int, default=2, help="repetitions with the same seed (default: 2)")
    parser.add_argument(
        "--compare-csv",
        type=Path,
        help="folder with the Data/Events CSVs of a GUI run (same rule, seed and modeling type)",
    )
    args = parser.parse_args()
    if args.runs < 1:
        parser.error("--runs must be >= 1")
    return args


def require_path(var_name: str) -> Path:
    value = os.environ.get(var_name)
    if not value:
        raise SystemExit(f"ERROR: {var_name} is not set. Copy .env.example to .env and set {var_name}.")
    path = Path(value)
    if not path.exists():
        raise SystemExit(f"ERROR: {var_name} points to a path that does not exist: {path}")
    return path


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_once(netlogo: Any, args: argparse.Namespace, run_index: int) -> RunResult:
    rule_name = RULES[args.rule]
    netlogo.command(f"random-seed {args.seed}")
    netlogo.command(f'set Reactivity.rule "{rule_name}"')
    netlogo.command(f'set Modeling.Type "{args.modeling_type}"')
    netlogo.command("setup")

    started_at = time.time()
    start = time.perf_counter()
    netlogo.command(f'repeat {GO_CALL_CAP} [ if terminado = "No" [ go ] ]')
    wall_seconds = time.perf_counter() - start

    terminado = str(netlogo.report("terminado"))
    ticks = int(netlogo.report("ticks"))
    if terminado != "Si" or ticks != FINAL_TICKS:
        raise RuntimeError(
            f"Run {run_index}: ExportData was not reached (terminado={terminado!r}, ticks={ticks})"
        )

    kpis = compute_kpis(netlogo)
    csv_files, csv_hashes = collect_csvs(netlogo, args, run_index, started_at)

    return RunResult(
        run=run_index,
        ticks=kpis.ticks,
        simulated_time=kpis.simulated_time,
        finished=kpis.finished,
        wip=kpis.wip,
        throughput=kpis.throughput,
        mean_flow_time=kpis.mean_flow_time,
        utilization=kpis.utilization,
        wall_seconds=wall_seconds,
        csv_files=csv_files,
        csv_sha256=csv_hashes,
    )


def collect_csvs(
    netlogo: Any, args: argparse.Namespace, run_index: int, started_at: float
) -> tuple[dict[str, str], dict[str, str]]:
    """Copy the CSVs written by ExportData to results/validation/<rule>_<seed>_run<k>/."""
    suffix = str(netlogo.report(CSV_NAME_REPORTER))
    target_dir = VALIDATION_DIR / f"{args.rule}_{args.seed}_run{run_index}"
    files: dict[str, str] = {}
    hashes: dict[str, str] = {}
    for kind, prefix in (("Data", "Data"), ("Events", "Event")):
        source = MODEL_DIR / "Results" / kind / f"{prefix}{suffix}"
        if not source.exists():
            raise RuntimeError(f"Exported CSV not found where expected: {source}")
        if source.stat().st_mtime < started_at:
            raise RuntimeError(f"Exported CSV was not rewritten by this run: {source}")
        destination = target_dir / kind / source.name
        destination.parent.mkdir(parents=True, exist_ok=True)
        # copyfile, not copy2: copying timestamps fails on bind mounts (Docker on Windows).
        shutil.copyfile(source, destination)
        files[kind] = destination.relative_to(REPO_ROOT).as_posix()
        hashes[kind] = sha256(destination)
    return files, hashes


def first_difference(a: Path, b: Path) -> dict[str, Any] | None:
    """Compare two CSVs line by line. Return None if identical, else a description."""
    lines_a = a.read_text(encoding="utf-8").splitlines()
    lines_b = b.read_text(encoding="utf-8").splitlines()
    differing = [i for i, (x, y) in enumerate(zip(lines_a, lines_b)) if x != y]
    if not differing and len(lines_a) == len(lines_b):
        return None
    first = differing[0] if differing else min(len(lines_a), len(lines_b))
    line_a = lines_a[first] if first < len(lines_a) else "<missing>"
    line_b = lines_b[first] if first < len(lines_b) else "<missing>"
    approx_tick: int | None = None
    try:
        approx_tick = round(float(line_a.split(",")[0]) / TICK_DURATION)
    except ValueError:
        pass
    return {
        "first_line": first + 1,
        "approx_tick": approx_tick,
        "line_a": line_a,
        "line_b": line_b,
        "differing_lines": len(differing),
        "line_count_a": len(lines_a),
        "line_count_b": len(lines_b),
    }


def check_determinism(results: list[RunResult]) -> dict[str, list[Any]]:
    """Return {kpi: [value per run]} for every KPI that is not identical across runs."""
    reference = results[0].kpis()
    differences: dict[str, list[Any]] = {}
    for key in reference:
        values = [r.kpis().get(key) for r in results]
        if any(v != values[0] for v in values[1:]):
            differences[key] = values
    return differences


def find_gui_csv(folder: Path, kind: str, name: str) -> Path | None:
    for candidate in (folder / kind / name, folder / name, folder / "Results" / kind / name):
        if candidate.exists():
            return candidate
    return None


def compare_with_gui(folder: Path, reference: RunResult) -> dict[str, Any]:
    report: dict[str, Any] = {"folder": str(folder)}
    for kind, rel_path in reference.csv_files.items():
        headless = REPO_ROOT / rel_path
        gui = find_gui_csv(folder, kind, headless.name)
        if gui is None:
            report[kind] = {"status": "missing", "expected_name": headless.name}
            continue
        diff = first_difference(gui, headless)
        report[kind] = {"status": "identical" if diff is None else "different", "gui_file": str(gui)}
        if diff is not None:
            report[kind].update(diff)
    return report


def format_table(results: list[RunResult]) -> str:
    machines = list(results[0].utilization)
    headers = ["run", "ticks", "finished", "WIP", "throughput", "mean_flow", "wall_s"] + [f"U_{m}" for m in machines]
    rows = []
    for r in results:
        flow = "n/a" if r.mean_flow_time is None else f"{r.mean_flow_time:.3f}"
        rows.append(
            [str(r.run), str(r.ticks), str(r.finished), str(r.wip), f"{r.throughput:.5f}", flow, f"{r.wall_seconds:.1f}"]
            + [f"{r.utilization[m]:.3f}" for m in machines]
        )
    widths = [max(len(h), *(len(row[i]) for row in rows)) for i, h in enumerate(headers)]
    line = lambda cells: "  ".join(c.rjust(w) for c, w in zip(cells, widths))  # noqa: E731
    return "\n".join([line(headers), line(["-" * w for w in widths]), *(line(row) for row in rows)])


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
    args = parse_args()

    # .env is optional: in the container the paths come from environment variables.
    load_dotenv(REPO_ROOT / ".env")
    netlogo_home = require_path("NETLOGO_HOME")
    jvm_path = require_path("JVM_PATH")
    if not MODEL_PATH.exists():
        raise SystemExit(f"ERROR: Model not found: {MODEL_PATH}")
    if args.compare_csv is not None and not args.compare_csv.is_dir():
        raise SystemExit(f"ERROR: --compare-csv folder does not exist: {args.compare_csv}")

    for kind in ("Data", "Events"):
        (MODEL_DIR / "Results" / kind).mkdir(parents=True, exist_ok=True)

    import pynetlogo

    netlogo = pynetlogo.NetLogoLink(gui=False, netlogo_home=str(netlogo_home), jvm_path=str(jvm_path))
    results: list[RunResult] = []
    try:
        start = time.perf_counter()
        netlogo.load_model(str(MODEL_PATH))
        logger.info("Model loaded in %.2f s", time.perf_counter() - start)
        interval_logs = int(netlogo.report("Interval.logs"))

        for k in range(1, args.runs + 1):
            logger.info("Run %d/%d: rule=%d seed=%d type=%s", k, args.runs, args.rule, args.seed, args.modeling_type)
            result = run_once(netlogo, args, k)
            logger.info("Run %d finished in %.1f s", k, result.wall_seconds)
            results.append(result)
    finally:
        netlogo.kill_workspace()

    differences = check_determinism(results)
    csv_diffs: dict[str, Any] = {}
    for kind in ("Data", "Events"):
        if f"sha256_{kind}" in differences:
            csv_diffs[kind] = first_difference(REPO_ROOT / results[0].csv_files[kind], REPO_ROOT / results[1].csv_files[kind])

    gui_report = compare_with_gui(args.compare_csv, results[0]) if args.compare_csv else None

    summary = {
        "rule": args.rule,
        "rule_name": RULES[args.rule],
        "seed": args.seed,
        "modeling_type": args.modeling_type,
        "interval_logs": interval_logs,
        "runs": [asdict(r) for r in results],
        "deterministic": not differences,
        "differences": differences,
        "csv_differences": csv_diffs,
        "gui_comparison": gui_report,
    }
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out_file = RESULTS_DIR / f"validation_{args.rule}_{args.seed}.json"
    out_file.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")

    print()
    print(f"Rule {args.rule} ({RULES[args.rule]}) | seed {args.seed} | {args.modeling_type} | Interval.logs {interval_logs}")
    print(format_table(results))
    for kind, path in results[0].csv_files.items():
        print(f"CSV {kind:6s} (run 1): {path}")
    if len(results) < 2:
        print("Determinism: not checked (only 1 run)")
    elif differences:
        print("Determinism: FAILED - runs with the same seed differ:")
        for key, values in differences.items():
            print(f"  {key}: {values}")
        for kind, diff in csv_diffs.items():
            print(f"  {kind} CSV first difference: {diff}")
    else:
        print(f"Determinism: OK - {len(results)} runs identical (KPIs and CSV SHA-256)")
    if gui_report is not None:
        for kind in ("Data", "Events"):
            print(f"GUI comparison {kind}: {gui_report[kind]}")
    print(f"Summary: {out_file.relative_to(REPO_ROOT)}")

    gui_ok = gui_report is None or all(gui_report[k]["status"] == "identical" for k in ("Data", "Events"))
    return 0 if not differences and gui_ok else 1


if __name__ == "__main__":
    sys.exit(main())
