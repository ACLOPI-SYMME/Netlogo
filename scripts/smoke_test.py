"""Smoke test: open NetLogo headless via pynetlogo, load Paper.nlogo and run a few ticks.

Usage (from the repository root, with the venv active):
    python scripts/smoke_test.py
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[1]
MODEL_DIR = REPO_ROOT / "model"
MODEL_PATH = MODEL_DIR / "Paper.nlogo"
N_TICKS = 100

# Output folders written by ExportData, relative to the model's directory.
MODEL_OUTPUT_DIRS = (MODEL_DIR / "Results" / "Data", MODEL_DIR / "Results" / "Events")


def fail(message: str) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    sys.exit(1)


def require_path(var_name: str) -> Path:
    """Read a path from an environment variable and check that it exists."""
    value = os.environ.get(var_name)
    if not value:
        fail(f"{var_name} is not set. Copy .env.example to .env and set {var_name}.")
    path = Path(value)
    if not path.exists():
        fail(f"{var_name} points to a path that does not exist: {path}")
    return path


def main() -> None:
    # .env is optional: in the container the paths come from environment variables.
    load_dotenv(REPO_ROOT / ".env")

    netlogo_home = require_path("NETLOGO_HOME")
    jvm_path = require_path("JVM_PATH")
    if not MODEL_PATH.exists():
        fail(f"Model not found: {MODEL_PATH}")

    print(f"NETLOGO_HOME = {netlogo_home}")
    print(f"JVM_PATH     = {jvm_path}")
    print(f"Model        = {MODEL_PATH}")

    for directory in MODEL_OUTPUT_DIRS:
        directory.mkdir(parents=True, exist_ok=True)

    # Imported here so that configuration errors are reported before the JVM starts.
    import pynetlogo

    netlogo = pynetlogo.NetLogoLink(
        gui=False, netlogo_home=str(netlogo_home), jvm_path=str(jvm_path)
    )
    try:
        start = time.perf_counter()
        netlogo.load_model(str(MODEL_PATH))
        load_seconds = time.perf_counter() - start

        print(f"NetLogo version      : {netlogo.report('netlogo-version')}")
        print(f"Reactivity.rule      : {netlogo.report('Reactivity.rule')}")

        netlogo.command("setup")
        print(f"Nodes after setup    : {int(netlogo.report('count nodes'))}")
        print(f"Turtles after setup  : {int(netlogo.report('count turtles'))}")

        start = time.perf_counter()
        for _ in range(N_TICKS):
            netlogo.command("go")
        run_seconds = time.perf_counter() - start

        print(f"Ticks after {N_TICKS} go   : {int(netlogo.report('ticks'))}")
        print(f"Model load time      : {load_seconds:.2f} s")
        print(f"{N_TICKS} x go time        : {run_seconds:.2f} s")
    finally:
        netlogo.kill_workspace()


if __name__ == "__main__":
    main()
