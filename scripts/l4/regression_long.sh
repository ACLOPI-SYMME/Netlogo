#!/usr/bin/env bash
# Slow tests inside the container: long-run regression (100,000 ticks) and the slow worker tests.
set -u
cd /app
python -m pytest -m slow -v -s -rf 2>&1 | grep -E "::|passed|failed|speed-up|assert|Error"
