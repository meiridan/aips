#!/usr/bin/env bash
set -euo pipefail

PORT=8001
cd "$(dirname "$0")"

echo "Stopping server on :${PORT}..."
lsof -ti:${PORT} | xargs kill -9 2>/dev/null || true
sleep 1

echo "Starting phase2 runner..."
uv run python -m tests.phase2_runner.server &
PID=$!

echo "Waiting for :${PORT}..."
for i in $(seq 1 15); do
  if curl -s http://localhost:${PORT}/api/scenarios >/dev/null 2>&1; then
    echo "Up (pid ${PID}) → http://localhost:${PORT}"
    exit 0
  fi
  sleep 1
done

echo "ERROR: server did not come up in 15s" >&2
exit 1
