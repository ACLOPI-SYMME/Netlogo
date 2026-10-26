#!/usr/bin/env bash
# Long-run regression inside the container (slow tests, 100,000 ticks per case).
set -u
cd /app
python -m pytest -m slow -v -rf 2>&1 | grep -E "::|passed|failed|assert"
