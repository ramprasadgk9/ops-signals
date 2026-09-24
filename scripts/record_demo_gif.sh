#!/usr/bin/env bash
# Re-record the README demo GIF from a running demo stack:
#
#   docker compose -f docker-compose.demo.yml up -d
#   ./scripts/demo_smoke_test.py          # waits until the enriched alert has landed
#   ./scripts/record_demo_gif.sh
#
# Needs the frontend's Playwright browsers (cd frontend && npx playwright install chromium) and
# the project virtualenv (for Pillow).

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
OUTPUT="${1:-$ROOT_DIR/docs/screenshots/images/demo/ops-signals-demo.gif}"
PYTHON="${PYTHON_BIN:-$ROOT_DIR/.venv/bin/python}"
WORK_DIR="$(mktemp -d)"
trap 'rm -rf "$WORK_DIR"' EXIT

cd "$ROOT_DIR"
docker compose -f docker-compose.demo.yml logs --no-log-prefix --no-color demo-seeder > "$WORK_DIR/seeder.log"
if ! grep -q "done\." "$WORK_DIR/seeder.log"; then
  echo "The demo seeder hasn't finished - start the demo and wait for it first." >&2
  exit 1
fi

node demo/gif/capture.cjs "$WORK_DIR/frames" "$WORK_DIR/seeder.log"
"$PYTHON" demo/gif/build_gif.py "$WORK_DIR/frames" "$OUTPUT"
