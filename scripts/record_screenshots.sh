#!/usr/bin/env bash
# Re-record the documentation screenshots (docs/screenshots/images/{web,grafana-plugin,slack}) from a
# running demo, so they always show the current UI with realistic data:
#
#   docker compose -f docker-compose.demo.yml up -d
#   ./scripts/demo_smoke_test.py            # waits until the enriched alert has landed
#   ./scripts/record_screenshots.sh
#
# Grafana plugin screens need the development stack's Grafana and mock metrics as well
# (`docker compose up -d grafana prometheus mock-metrics`); this script builds the plugin into
# frontend/dist (which that Grafana mounts) pointed at the demo backend, and restarts Grafana to
# load it. Set SKIP_GRAFANA=1 to capture only the web and Slack screens.
#
# Needs the frontend's Playwright browsers (cd frontend && npx playwright install chromium).

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
OUTPUT="${1:-$ROOT_DIR/docs/screenshots/images}"
DEMO_WEB_URL="${DEMO_WEB_URL:-http://localhost:8080}"
GRAFANA_URL="${GRAFANA_URL:-http://localhost:3000}"
GRAFANA_CONTAINER="${GRAFANA_CONTAINER:-ops-signals-grafana}"

cd "$ROOT_DIR"

if ! curl -fsS "$DEMO_WEB_URL/api/health" >/dev/null 2>&1; then
  echo "The demo isn't reachable at $DEMO_WEB_URL - start it first (see docs/demo.md)." >&2
  exit 1
fi

python3 demo/screenshots/seed_showcase.py

if [[ "${SKIP_GRAFANA:-0}" != "1" ]]; then
  if ! curl -fsS "$GRAFANA_URL/api/health" >/dev/null 2>&1; then
    echo "Grafana isn't reachable at $GRAFANA_URL. Start it with 'docker compose up -d grafana prometheus mock-metrics', or set SKIP_GRAFANA=1." >&2
    exit 1
  fi
  echo "Building the Grafana plugin against $DEMO_WEB_URL..."
  (cd frontend && VITE_OPS_SIGNALS_BACKEND_URL="$DEMO_WEB_URL" npm run build:grafana >/dev/null)
  if docker ps --format '{{.Names}}' | grep -qx "$GRAFANA_CONTAINER"; then
    docker restart "$GRAFANA_CONTAINER" >/dev/null
    for _ in {1..60}; do
      curl -fsS "$GRAFANA_URL/api/health" >/dev/null 2>&1 && break
      sleep 2
    done
  fi
else
  export SKIP_GRAFANA=1
fi

node demo/screenshots/capture.cjs "$OUTPUT"
echo "Screenshots written under ${OUTPUT#$ROOT_DIR/}."
