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
# shellcheck source=lib/local_prometheus.sh
source "$ROOT_DIR/scripts/lib/local_prometheus.sh"

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

# Test sign-in (docs/web-ui-sign-in.md#try-sign-in-before-onboarding): a local OpenID Connect provider with
# test accounts, for trying the web UI's sign-in and roles before a company provider is set up. Its
# settings are exported for this script's backend only and never written to .env, so
# run_grafana_stack.sh and the plugin are not affected. Company sign-in needs an API token: without one
# in .env, a local one is made and kept in tmp/test-sign-in.token for scripts.
test_sign_in=false
case "$(echo "${OPS_SIGNALS_TEST_SIGN_IN:-false}" | tr '[:upper:]' '[:lower:]')" in
  1|true|yes|on) test_sign_in=true ;;
esac
TEST_SIGN_IN_PORT="${TEST_SIGN_IN_PORT:-9400}"
test_sign_in_token_file=""
if [[ "$test_sign_in" == "true" ]]; then
  if [[ -n "${OPS_SIGNALS_OIDC_ISSUER_URL:-}${OPS_SIGNALS_OIDC_CLIENT_ID:-}${OPS_SIGNALS_OIDC_CLIENT_SECRET:-}" ]]; then
    echo "OPS_SIGNALS_TEST_SIGN_IN=true, but .env also sets a company provider (OPS_SIGNALS_OIDC_ISSUER_URL, _CLIENT_ID or _CLIENT_SECRET)."
    echo "Remove one of them: the test provider is for trying sign-in before a company provider is set up."
    exit 1
  fi
  mkdir -p "$ROOT_DIR/tmp"
  if [[ -z "${OPS_SIGNALS_API_TOKEN:-}" ]]; then
    test_sign_in_token_file="$ROOT_DIR/tmp/test-sign-in.token"
    if [[ ! -s "$test_sign_in_token_file" ]]; then
      "$VENV_DIR/bin/python" -c "import secrets; print(secrets.token_hex(32))" >"$test_sign_in_token_file"
    fi
    OPS_SIGNALS_API_TOKEN="$(cat "$test_sign_in_token_file")"
  fi
  export OPS_SIGNALS_API_TOKEN
  while IFS= read -r setting; do
    export "$setting"
  done < <("$VENV_DIR/bin/python" -c "from backend.devtools.test_sign_in_provider import env_lines; print('\n'.join(env_lines('http://127.0.0.1:${TEST_SIGN_IN_PORT}')))")
  export OPS_SIGNALS_PUBLIC_URL="http://localhost:${FRONTEND_PORT}"
fi

# Alert enrichment (docs/design/alert-enrichment-plan.md): when enabled, also run a local Alertmanager and
# demo alert rules (docker-compose.alerting.yml), wired to this script's backend port. When disabled,
# the plain compose file brings Prometheus back to its normal config.
alerting_enabled=false
case "$(echo "${OPS_SIGNALS_ALERT_ENRICHMENT_ENABLED:-false}" | tr '[:upper:]' '[:lower:]')" in
  1|true|yes|on) alerting_enabled=true ;;
esac

compose=(docker compose)
services=(postgres qdrant)
local_prometheus=false
if wants_local_prometheus; then
  local_prometheus=true
  services+=(prometheus mock-metrics)
else
  echo "Reading your own Prometheus (.env), so the bundled Prometheus and mock metrics are not started."
  echo "OPS_SIGNALS_LOCAL_PROMETHEUS=true starts them anyway."
fi
if [[ "$alerting_enabled" == "true" ]]; then
  mkdir -p "$ROOT_DIR/tmp"
  export OPS_SIGNALS_ALERTMANAGER_CONFIG="$ROOT_DIR/tmp/alertmanager.generated.yml"
  sed "s#host.docker.internal:[0-9]*/#host.docker.internal:${BACKEND_PORT}/#" \
    "$ROOT_DIR/grafana/alertmanager/alertmanager.yml" >"$OPS_SIGNALS_ALERTMANAGER_CONFIG"
  # Test sign-in turned the API token on: the receiver then needs it too.
  if [[ "$test_sign_in" == "true" && -z "${OPS_SIGNALS_ALERT_RECEIVER_TOKEN:-}" ]]; then
    sed -i.bak -e 's/^        # http_config:/        http_config:/' -e 's/^        #   authorization:/          authorization:/' \
      -e "s/^        #     credentials: <same token>/            credentials: ${OPS_SIGNALS_API_TOKEN}/" "$OPS_SIGNALS_ALERTMANAGER_CONFIG"
    rm -f "$OPS_SIGNALS_ALERTMANAGER_CONFIG.bak"
  fi
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

if [[ "$local_prometheus" == "true" ]]; then
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
fi

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
test_sign_in_pid=""

if [[ "$test_sign_in" == "true" ]]; then
  test_sign_in_log="${ROOT_DIR}/.tmp_ops_signals_test_sign_in.log"
  echo "Test sign-in: starting the local test provider on :${TEST_SIGN_IN_PORT}"
  "$VENV_DIR/bin/python" -m backend.devtools.test_sign_in_provider --port "$TEST_SIGN_IN_PORT" >"$test_sign_in_log" 2>&1 &
  test_sign_in_pid=$!
  echo "Waiting for the test provider to become ready..."
  for attempt in $(seq 1 30); do
    if curl -fsS "http://127.0.0.1:${TEST_SIGN_IN_PORT}/.well-known/openid-configuration" >/dev/null 2>&1; then
      break
    fi
    if [[ "$attempt" -eq 30 ]]; then
      echo "the test provider did not become ready in time; see $test_sign_in_log"
      kill "$test_sign_in_pid" >/dev/null 2>&1 || true
      exit 1
    fi
    sleep 1
  done
fi

echo "Starting backend API on :${BACKEND_PORT}..."
OPS_SIGNALS_PROMETHEUS_URL="${OPS_SIGNALS_PROMETHEUS_URL:-http://localhost:9090}" \
  OPS_SIGNALS_UI_BASE_URL="${OPS_SIGNALS_UI_BASE_URL:-http://localhost:${FRONTEND_PORT}}" \
  BACKEND_PORT="$BACKEND_PORT" OPS_SIGNALS_ALLOW_FILE_WRITES="${OPS_SIGNALS_ALLOW_FILE_WRITES:-true}" OPS_SIGNALS_ENABLE_TESTING_API="${OPS_SIGNALS_ENABLE_TESTING_API:-true}" \
  "$VENV_DIR/bin/python" -m uvicorn backend.app.main:app --reload --reload-dir "$ROOT_DIR/backend" --port "$BACKEND_PORT" >"$api_log" 2>&1 &
api_pid=$!

echo "Starting frontend on :${FRONTEND_PORT}..."
(cd frontend && VITE_API_PORT="$BACKEND_PORT" VITE_FRONTEND_PORT="$FRONTEND_PORT" npm run dev -- --host 127.0.0.1 --port "$FRONTEND_PORT" >"$ui_log" 2>&1) &
ui_pid=$!

cleanup() {
  kill "$api_pid" "$ui_pid" ${test_sign_in_pid:+"$test_sign_in_pid"} >/dev/null 2>&1 || true
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
if [[ "$test_sign_in" == "true" ]]; then
  echo "Test sign-in: http://127.0.0.1:${TEST_SIGN_IN_PORT}  (for trying sign-in on this computer only)"
  echo "              sam = Viewer · priya = Editor · ada = Admin · lee = no groups (Viewer)"
  echo "              Open http://localhost:${FRONTEND_PORT} and sign in. Remove OPS_SIGNALS_TEST_SIGN_IN from .env to turn it off."
  if [[ -n "$test_sign_in_token_file" ]]; then
    echo "              API token for scripts: $test_sign_in_token_file"
  fi
fi
echo "MCP write:    ./.venv/bin/python -m intelligence.cli mcp-write"
echo "Press Ctrl+C to stop the services started by this script."

wait
