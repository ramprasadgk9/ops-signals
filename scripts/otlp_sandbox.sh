#!/usr/bin/env bash
# An empty, throwaway copy of Ops Signals for trying OTLP on its own: its own Postgres and Qdrant,
# and a backend that inherits none of your settings, so no Prometheus or Alertmanager - what a new
# user who only sends OpenTelemetry sees. Your run_all.sh stack and the demo are not touched.
#
#   ./scripts/otlp_sandbox.sh up          start it (empty), then open the UI
#   ./scripts/otlp_sandbox.sh collector   start a real OTel Collector sending to it (host + Docker stats)
#   ./scripts/otlp_sandbox.sh sample      send one day of a synthetic series in one go (gives a finding)
#   ./scripts/otlp_sandbox.sh status      what is running, data received, findings so far
#   ./scripts/otlp_sandbox.sh down        stop and remove all of it, data included
#
# Ports: UI 5184, backend 8100, Postgres 5440, Qdrant 6340. Override with SANDBOX_UI_PORT,
# SANDBOX_BACKEND_PORT, SANDBOX_POSTGRES_PORT, SANDBOX_QDRANT_PORT. Logs and PIDs: tmp/otlp-sandbox/.
# A second copy next to the first: a different SANDBOX_NAME (default ossandbox) and ports.
# SANDBOX_PROMETHEUS_URL configures a Prometheus (one that is down, to see how that looks).

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
NAME="${SANDBOX_NAME:-ossandbox}"
STATE_DIR="$ROOT_DIR/tmp/otlp-sandbox${SANDBOX_NAME:+-$SANDBOX_NAME}"
UI_PORT="${SANDBOX_UI_PORT:-5184}"
BACKEND_PORT="${SANDBOX_BACKEND_PORT:-8100}"
POSTGRES_PORT="${SANDBOX_POSTGRES_PORT:-5440}"
QDRANT_PORT="${SANDBOX_QDRANT_PORT:-6340}"
PROMETHEUS_URL="${SANDBOX_PROMETHEUS_URL:-}"
POSTGRES_CONTAINER="${NAME}-postgres"
QDRANT_CONTAINER="${NAME}-qdrant"
COLLECTOR_CONTAINER="${NAME}-otel"
PYTHON="$ROOT_DIR/.venv/bin/python"

backend_url() { echo "http://localhost:${BACKEND_PORT}"; }

backend_up() { curl -sf -m 3 "$(backend_url)/api/health" >/dev/null 2>&1; }

wait_for() {
  local what="$1" attempts="$2"
  shift 2
  for ((i = 1; i <= attempts; i++)); do
    if "$@" >/dev/null 2>&1; then
      return 0
    fi
    sleep 2
  done
  echo "$what did not become ready. Logs: $STATE_DIR"
  exit 1
}

start_process() {
  local name="$1"
  shift
  local pid_file="$STATE_DIR/$name.pid"
  if [[ -f "$pid_file" ]] && kill -0 "$(cat "$pid_file")" 2>/dev/null; then
    echo "$name already running."
    return
  fi
  nohup "$@" >"$STATE_DIR/$name.log" 2>&1 &
  echo $! >"$pid_file"
}

stop_process() {
  local pid_file="$STATE_DIR/$1.pid"
  [[ -f "$pid_file" ]] || return 0
  local pid
  pid="$(cat "$pid_file")"
  # npm starts vite as a child, so stop the children too.
  pkill -P "$pid" 2>/dev/null || true
  kill "$pid" 2>/dev/null || true
  # uvicorn can hang waiting for open connections to close.
  for _ in {1..10}; do
    kill -0 "$pid" 2>/dev/null || break
    sleep 1
  done
  kill -9 "$pid" 2>/dev/null || true
  rm -f "$pid_file"
}

cmd_up() {
  [[ -x "$PYTHON" ]] || { echo ".venv is missing. Run scripts/setup.sh first."; exit 1; }
  mkdir -p "$STATE_DIR"

  if ! docker ps --format '{{.Names}}' | grep -qx "$POSTGRES_CONTAINER"; then
    docker rm -f "$POSTGRES_CONTAINER" >/dev/null 2>&1 || true
    # The schema comes from sql/init.sql, as in docker-compose.yml.
    docker run -d --name "$POSTGRES_CONTAINER" -p "${POSTGRES_PORT}:5432" \
      -e POSTGRES_USER=ops_signals -e POSTGRES_PASSWORD=ops_signals -e POSTGRES_DB=ops_signals \
      -v "$ROOT_DIR/sql/init.sql:/docker-entrypoint-initdb.d/init.sql:ro" \
      postgres:16 >/dev/null
  fi
  if ! docker ps --format '{{.Names}}' | grep -qx "$QDRANT_CONTAINER"; then
    docker rm -f "$QDRANT_CONTAINER" >/dev/null 2>&1 || true
    docker run -d --name "$QDRANT_CONTAINER" -p "${QDRANT_PORT}:6333" qdrant/qdrant:latest >/dev/null
  fi
  echo "Waiting for Postgres and Qdrant..."
  wait_for Postgres 30 docker exec "$POSTGRES_CONTAINER" pg_isready -U ops_signals -d ops_signals
  wait_for Qdrant 30 curl -sf "http://localhost:${QDRANT_PORT}/readyz"

  echo "Starting backend on :${BACKEND_PORT}..."
  # env -i: no .env, no real Prometheus, Grafana or Slack. No --reload, so editing backend code
  # doesn't restart it under you.
  local prometheus=()
  [[ -n "$PROMETHEUS_URL" ]] && prometheus=(OPS_SIGNALS_PROMETHEUS_URL="$PROMETHEUS_URL")
  start_process backend env -i PATH="$PATH" HOME="$HOME" \
    OPS_SIGNALS_DATABASE_URL="postgresql+psycopg://ops_signals:ops_signals@localhost:${POSTGRES_PORT}/ops_signals" \
    OPS_SIGNALS_QDRANT_URL="http://localhost:${QDRANT_PORT}" \
    ${prometheus[@]+"${prometheus[@]}"} \
    OPS_SIGNALS_UI_BASE_URL="http://localhost:${UI_PORT}" \
    OPS_SIGNALS_ALLOW_FILE_WRITES=true \
    "$PYTHON" -m uvicorn backend.app.main:app --port "$BACKEND_PORT"
  wait_for Backend 60 backend_up

  echo "Starting UI on :${UI_PORT}..."
  (cd "$ROOT_DIR/frontend" && start_process ui env VITE_API_PORT="$BACKEND_PORT" VITE_FRONTEND_PORT="$UI_PORT" \
    npm run dev -- --host 127.0.0.1 --port "$UI_PORT")
  wait_for UI 30 curl -sf "http://localhost:${UI_PORT}"

  echo
  echo "Sandbox running: http://localhost:${UI_PORT}"
  if [[ -n "$PROMETHEUS_URL" ]]; then
    echo "Prometheus: ${PROMETHEUS_URL}. No Alertmanager."
  else
    echo "OTLP only: no Prometheus, no Alertmanager."
  fi
  echo "Next: $0 collector   (live data)   or   $0 sample   (a day of data, gives a finding)"
}

cmd_collector() {
  backend_up || { echo "Sandbox isn't running. Start it first: $0 up"; exit 1; }
  BACKEND_PORT="$BACKEND_PORT" OTEL_COLLECTOR_CONTAINER="$COLLECTOR_CONTAINER" \
    OTEL_COLLECTOR_CONFIG="$STATE_DIR/otelcol.yaml" OPS_SIGNALS_API_TOKEN="" \
    "$ROOT_DIR/scripts/otel_collector.sh" start
}

cmd_sample() {
  backend_up || { echo "Sandbox isn't running. Start it first: $0 up"; exit 1; }
  "$PYTHON" "$ROOT_DIR/scripts/send_test_otlp_metrics.py" --endpoint "$(backend_url)/api/otlp" --service "${SANDBOX_SERVICE:-checkout}"
  echo "Waiting for the next analysis cycle (up to ~60s)..."
  for _ in {1..45}; do
    if [[ "$(findings_count)" != "0" ]]; then
      break
    fi
    sleep 2
  done
  echo "Findings: $(findings_count). Open http://localhost:${UI_PORT}/findings"
}

findings_count() {
  curl -s -m 5 "$(backend_url)/api/findings?window=24h" | "$PYTHON" -c 'import json, sys; print(len(json.load(sys.stdin)))' 2>/dev/null || echo "?"
}

cmd_status() {
  for container in "$POSTGRES_CONTAINER" "$QDRANT_CONTAINER" "$COLLECTOR_CONTAINER"; do
    if docker ps --format '{{.Names}}' | grep -qx "$container"; then echo "$container: running"; else echo "$container: not running"; fi
  done
  for name in backend ui; do
    local pid_file="$STATE_DIR/$name.pid"
    if [[ -f "$pid_file" ]] && kill -0 "$(cat "$pid_file")" 2>/dev/null; then echo "$name: running"; else echo "$name: not running"; fi
  done
  if backend_up; then
    curl -s -m 5 "$(backend_url)/api/otlp/status" \
      | "$PYTHON" -c 'import json, sys; d = json.load(sys.stdin); print("OTLP: %d points received, %d awaiting analysis" % (d["points_received_total"], d["backlog_size"]))'
    echo "Findings (24h): $(findings_count)"
    echo "UI: http://localhost:${UI_PORT}"
  fi
}

cmd_down() {
  docker rm -f "$COLLECTOR_CONTAINER" "$POSTGRES_CONTAINER" "$QDRANT_CONTAINER" >/dev/null 2>&1 || true
  stop_process ui
  stop_process backend
  echo "Sandbox removed (containers, data and processes). Logs stay in tmp/otlp-sandbox/."
}

case "${1:-}" in
  up) cmd_up ;;
  collector) cmd_collector ;;
  sample) cmd_sample ;;
  status) cmd_status ;;
  down) cmd_down ;;
  *)
    sed -n '2,15p' "$0" | sed 's/^# \{0,1\}//'
    exit 1
    ;;
esac
