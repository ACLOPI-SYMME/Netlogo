"""Cross-platform equivalent of run_all_rules.ps1: validate rules 1, 2 and 3 with seed 42 (Stochastic).

Usage (from the repository root):
    python scripts/run_all_rules.py
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent / "validate_headless.py"
SEED = 42


def main() -> int:
    failed = []
    for rule in (1, 2, 3):
        print(f"=== Rule {rule}, seed {SEED}, Stochastic ===", flush=True)
        cmd = [sys.executable, str(SCRIPT), "--rule", str(rule), "--seed", str(SEED), "--modeling-type", "Stochastic"]
        if subprocess.run(cmd).returncode != 0:
            failed.append(rule)
    if failed:
        print(f"Validation FAILED for rules: {', '.join(map(str, failed))}")
        return 1
    print("Validation OK for rules 1, 2, 3")
    return 0


if __name__ == "__main__":
    sys.exit(main())
