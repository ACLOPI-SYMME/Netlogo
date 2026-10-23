#!/usr/bin/env bash
# Regression inside the container: 3 rules vs baseline, then the test suite.
set -u
cd /app
python scripts/run_all_rules.py 2>&1 | grep -E "Determinism|Validation|ERROR|Traceback"
python scripts/compare_baseline.py
echo "compare_baseline exit: $?"
python -m pytest -q -rf 2>&1 | grep -v "Picked up JAVA_TOOL_OPTIONS" | tail -12
