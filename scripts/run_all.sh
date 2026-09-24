#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
VENV_DIR="${ROOT_DIR}/.venv"
BACKEND_PORT="${BACKEND_PORT:-8001}"
FRONTEND_PORT="${FRONTEND_PORT:-5174}"

if [[ -f "$ROOT_DIR/.env" ]]; then
  echo "Loading $ROOT_DIR/.env"
  set -a
  # shellcheck disable=SC1091
  source "$ROOT_DIR/.env"
  set +a
fi

if [[ ! -x "$VENV_DIR/bin/python" ]]; then
  echo ".venv is missing. Run scripts/setup.sh first."
  exit 1
fi

cd "$ROOT_DIR"

if ! command -v docker >/dev/null 2>&1; then
  echo "docker is required"
  exit 1
fi

if ! command -v curl >/dev/null 2>&1; then
  echo "curl is required"
  exit 1
fi

if ! command -v npm >/dev/null 2>&1; then
  echo "npm is required"
  exit 1
fi

# Alert enrichment (docs/alert-enrichment-plan.md): when enabled, also run a local Alertmanager and
# demo alert rules (docker-compose.alerting.yml), wired to this script's backend port. When disabled,
# the plain compose file brings Prometheus back to its normal config.
alerting_enabled=false
case "$(echo "${OPS_SIGNALS_ALERT_ENRICHMENT_ENABLED:-false}" | tr '[:upper:]' '[:lower:]')" in
  1|true|yes|on) alerting_enabled=true ;;
esac

compose=(docker compose)
services=(postgres qdrant prometheus mock-metrics)
if [[ "$alerting_enabled" == "true" ]]; then
  mkdir -p "$ROOT_DIR/tmp"
  export OPS_SIGNALS_ALERTMANAGER_CONFIG="$ROOT_DIR/tmp/alertmanager.generated.yml"
  sed "s#host.docker.internal:[0-9]*/#host.docker.internal:${BACKEND_PORT}/#" \
    "$ROOT_DIR/grafana/alertmanager/alertmanager.yml" >"$OPS_SIGNALS_ALERTMANAGER_CONFIG"
  compose=(docker compose -f docker-compose.yml -f docker-compose.alerting.yml)
  services+=(alertmanager)
  echo "Alert enrichment enabled: starting Alertmanager (receiver -> :${BACKEND_PORT})"
fi

"${compose[@]}" up -d "${services[@]}"

echo "Waiting for postgres to become ready..."
for attempt in {1..30}; do
  if docker compose exec -T postgres pg_isready -U ops_signals -d ops_signals >/dev/null 2>&1; then
    break
  fi
  if [[ "$attempt" -eq 30 ]]; then
    echo "postgres did not become ready in time"
    exit 1
  fi
  sleep 2
done

echo "Waiting for qdrant to become ready..."
for attempt in {1..60}; do
  if curl -fsS http://localhost:6333/readyz >/dev/null 2>&1 || curl -fsS http://localhost:6333/healthz >/dev/null 2>&1 || curl -fsS http://localhost:6333/health >/dev/null 2>&1; then
    break
  fi
  if [[ "$attempt" -eq 60 ]]; then
    echo "qdrant did not become ready in time"
    echo "Try: docker compose logs qdrant"
    exit 1
  fi
  sleep 2
done

echo "Waiting for prometheus to become ready..."
for attempt in {1..60}; do
  if curl -fsS http://localhost:9090/-/ready >/dev/null 2>&1; then
    break
  fi
  if [[ "$attempt" -eq 60 ]]; then
    echo "prometheus did not become ready in time"
    echo "Try: docker compose logs prometheus"
    exit 1
  fi
  sleep 2
done

if [[ "$alerting_enabled" == "true" ]]; then
  echo "Waiting for alertmanager to become ready..."
  for attempt in {1..30}; do
    if curl -fsS http://localhost:9093/-/ready >/dev/null 2>&1; then
      break
    fi
    if [[ "$attempt" -eq 30 ]]; then
      echo "alertmanager did not become ready in time"
      echo "Try: docker compose -f docker-compose.yml -f docker-compose.alerting.yml logs alertmanager"
      exit 1
    fi
    sleep 2
  done
fi

"$VENV_DIR/bin/python" -m intelligence.cli init-db --config config.yaml

api_log="${ROOT_DIR}/.tmp_ops_signals_api.log"
ui_log="${ROOT_DIR}/.tmp_ops_signals_ui.log"

echo "Starting backend API on :${BACKEND_PORT}..."
OPS_SIGNALS_PROMETHEUS_URL="${OPS_SIGNALS_PROMETHEUS_URL:-http://localhost:9090}" \
  OPS_SIGNALS_UI_BASE_URL="${OPS_SIGNALS_UI_BASE_URL:-http://localhost:${FRONTEND_PORT}}" \
  BACKEND_PORT="$BACKEND_PORT" "$VENV_DIR/bin/python" -m uvicorn backend.app.main:app --reload --reload-dir "$ROOT_DIR/backend" --port "$BACKEND_PORT" >"$api_log" 2>&1 &
api_pid=$!

echo "Starting frontend on :${FRONTEND_PORT}..."
(cd frontend && VITE_API_PORT="$BACKEND_PORT" VITE_FRONTEND_PORT="$FRONTEND_PORT" npm run dev -- --host 127.0.0.1 --port "$FRONTEND_PORT" >"$ui_log" 2>&1) &
ui_pid=$!

cleanup() {
  kill "$api_pid" "$ui_pid" >/dev/null 2>&1 || true
}
trap cleanup EXIT INT TERM

echo "Backend log: $api_log"
echo "Frontend log: $ui_log"
echo "Backend:      http://localhost:${BACKEND_PORT}"
echo "Frontend:     http://localhost:${FRONTEND_PORT}"
if [[ "$alerting_enabled" == "true" ]]; then
  echo "Alertmanager: http://localhost:9093  (demo rules post within ~1-2 min)"
  echo "Test alert:   BACKEND_PORT=${BACKEND_PORT} ./scripts/send_test_alert.py"
fi
echo "MCP server:   ./.venv/bin/python -m intelligence.cli mcp"
echo "MCP write:    ./.venv/bin/python -m intelligence.cli mcp-write"
echo "Press Ctrl+C to stop the services started by this script."

wait
