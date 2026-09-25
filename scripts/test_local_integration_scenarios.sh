#!/usr/bin/env bash
set -euo pipefail
set -m # job control: each background `&` job gets its own process group, so cleanup() can kill
       # the whole group (e.g. `npm run dev` -> vite) instead of just the immediate child PID,
       # which left orphaned vite processes behind on repeated local runs (confirmed: a later run's
       # own vite instance silently fell back to a different port because an earlier run's orphan
       # was still holding :5174, and the readiness check passed against that stale process instead
       # of the current run's own server).

# Runs the real-stack integration suite (tests/scenarios/integration, Playwright) against both
# surfaces: web-ui (frontend :5174 -> backend :8001) and the Grafana plugin (Grafana :3000 ->
# backend :8002), mirroring scripts/run_all.sh and scripts/run_grafana_stack.sh combined into one
# run-to-completion script instead of two long-lived dev servers.

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
VENV_DIR="${ROOT_DIR}/.venv"
WEB_UI_BACKEND_PORT="${WEB_UI_BACKEND_PORT:-8001}"
PLUGIN_BACKEND_PORT="${PLUGIN_BACKEND_PORT:-8002}"
WEB_UI_FRONTEND_PORT="${WEB_UI_FRONTEND_PORT:-5174}"
OPS_SIGNALS_PROMETHEUS_URL="${OPS_SIGNALS_PROMETHEUS_URL:-http://localhost:9090}"
PLAYWRIGHT_PROJECT="${1:-}"

if [[ -x "$VENV_DIR/bin/python" ]]; then
  PYTHON_BIN="$VENV_DIR/bin/python"
else
  PYTHON_BIN="${PYTHON_BIN:-python3}"
fi

cd "$ROOT_DIR"

for bin in docker curl npm; do
  if ! command -v "$bin" >/dev/null 2>&1; then
    echo "$bin is required for the integration suite"
    exit 1
  fi
done

echo "Building the Grafana plugin bundle..."
(cd frontend && VITE_OPS_SIGNALS_BACKEND_URL="http://localhost:${PLUGIN_BACKEND_PORT}" npm run build:grafana)

docker compose up -d postgres qdrant prometheus mock-metrics grafana

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
    exit 1
  fi
  sleep 2
done

echo "Waiting for prometheus to become ready..."
for attempt in {1..60}; do
  if curl -fsS "${OPS_SIGNALS_PROMETHEUS_URL}/-/ready" >/dev/null 2>&1; then
    break
  fi
  if [[ "$attempt" -eq 60 ]]; then
    echo "prometheus did not become ready in time"
    exit 1
  fi
  sleep 2
done

echo "Waiting for Grafana to become ready..."
for attempt in {1..60}; do
  if curl -fsS -u admin:admin http://localhost:3000/api/health >/dev/null 2>&1; then
    break
  fi
  if [[ "$attempt" -eq 60 ]]; then
    echo "grafana did not become ready in time"
    echo "Try: docker compose logs grafana"
    exit 1
  fi
  sleep 2
done

"$PYTHON_BIN" -m intelligence.cli init-db --config config.yaml

web_ui_backend_log="${ROOT_DIR}/.tmp_ops_signals_integration_web_ui_backend.log"
plugin_backend_log="${ROOT_DIR}/.tmp_ops_signals_integration_plugin_backend.log"
web_ui_frontend_log="${ROOT_DIR}/.tmp_ops_signals_integration_web_ui_frontend.log"

test_exit_code=0
web_ui_backend_pid=""
plugin_backend_pid=""
web_ui_frontend_pid=""
cleanup() {
  echo "Stopping backends and frontend dev server..."
  # Process-group kill (kill -- -$pid, relying on `set -m`) isn't enough on its own: npm's own
  # process spawning escapes the parent's process group when it forks vite, so the vite child
  # survives as an orphan (confirmed: repeated runs left multiple stray vite processes behind,
  # and a later run's own vite instance silently rebound to a different port because an earlier
  # orphan still held :5174, with the readiness check passing against that stale process instead
  # of the current run's server). Belt-and-suspenders: also kill whatever's actually bound to each
  # port directly, regardless of process-tree topology.
  for pid in "$web_ui_backend_pid" "$plugin_backend_pid" "$web_ui_frontend_pid"; do
    [[ -n "$pid" ]] && kill -- "-$pid" >/dev/null 2>&1
  done
  for port in "$WEB_UI_BACKEND_PORT" "$PLUGIN_BACKEND_PORT" "$WEB_UI_FRONTEND_PORT"; do
    port_pids="$(lsof -ti "tcp:$port" 2>/dev/null || true)"
    [[ -n "$port_pids" ]] && kill -9 $port_pids 2>/dev/null
  done
  true
}
trap cleanup EXIT INT TERM

# The two backends point at the same fresh Postgres database, and backend.app.main's app creation
# runs its own Base.metadata.create_all() on startup (redundant with init-db above). Starting both
# uvicorn processes at once races that DDL: both see "table doesn't exist" and both issue
# CREATE TABLE, and the second fails with a duplicate-key error on the table's sequence/index
# (confirmed against a genuinely fresh database — this only ever raced with an empty DB, hence
# invisible in normal single-backend dev usage). Starting them sequentially, waiting for the first
# to be fully up before starting the second, avoids the race entirely.
echo "Starting web-ui backend on :${WEB_UI_BACKEND_PORT}..."
BACKEND_PORT="$WEB_UI_BACKEND_PORT" OPS_SIGNALS_PROMETHEUS_URL="$OPS_SIGNALS_PROMETHEUS_URL" \
  OPS_SIGNALS_ALLOW_FILE_WRITES=true OPS_SIGNALS_ENABLE_TESTING_API=true \
  "$PYTHON_BIN" -m uvicorn backend.app.main:app --port "$WEB_UI_BACKEND_PORT" >"$web_ui_backend_log" 2>&1 &
web_ui_backend_pid=$!

echo "Waiting for web-ui backend to become ready..."
for attempt in {1..30}; do
  if curl -fsS "http://localhost:${WEB_UI_BACKEND_PORT}/api/health" >/dev/null 2>&1; then
    break
  fi
  if [[ "$attempt" -eq 30 ]]; then
    echo "web-ui backend did not become ready in time; see $web_ui_backend_log"
    exit 1
  fi
  sleep 2
done

echo "Starting plugin backend on :${PLUGIN_BACKEND_PORT}..."
BACKEND_PORT="$PLUGIN_BACKEND_PORT" OPS_SIGNALS_PROMETHEUS_URL="$OPS_SIGNALS_PROMETHEUS_URL" \
  OPS_SIGNALS_ALLOW_FILE_WRITES=true OPS_SIGNALS_ENABLE_TESTING_API=true \
  "$PYTHON_BIN" -m uvicorn backend.app.main:app --port "$PLUGIN_BACKEND_PORT" >"$plugin_backend_log" 2>&1 &
plugin_backend_pid=$!

echo "Waiting for plugin backend to become ready..."
for attempt in {1..30}; do
  if curl -fsS "http://localhost:${PLUGIN_BACKEND_PORT}/api/health" >/dev/null 2>&1; then
    break
  fi
  if [[ "$attempt" -eq 30 ]]; then
    echo "plugin backend did not become ready in time; see $plugin_backend_log"
    exit 1
  fi
  sleep 2
done

echo "Starting web-ui frontend on :${WEB_UI_FRONTEND_PORT}..."
(cd frontend && VITE_API_PORT="$WEB_UI_BACKEND_PORT" VITE_FRONTEND_PORT="$WEB_UI_FRONTEND_PORT" npm run dev -- --host 127.0.0.1 --port "$WEB_UI_FRONTEND_PORT" >"$web_ui_frontend_log" 2>&1) &
web_ui_frontend_pid=$!

echo "Waiting for web-ui frontend to become ready..."
for attempt in {1..30}; do
  if curl -fsS "http://localhost:${WEB_UI_FRONTEND_PORT}" >/dev/null 2>&1; then
    break
  fi
  if [[ "$attempt" -eq 30 ]]; then
    echo "web-ui frontend did not become ready in time; see $web_ui_frontend_log"
    exit 1
  fi
  sleep 2
done

cd frontend
if [[ ! -d "node_modules/@playwright" ]]; then
  echo "Installing Playwright browsers..."
  npx playwright install --with-deps chromium
fi

echo "Running integration suite..."
OPS_SIGNALS_WEB_UI_URL="http://localhost:${WEB_UI_FRONTEND_PORT}" \
OPS_SIGNALS_GRAFANA_URL="http://localhost:3000" \
OPS_SIGNALS_WEB_UI_BACKEND_URL="http://localhost:${WEB_UI_BACKEND_PORT}" \
OPS_SIGNALS_PLUGIN_BACKEND_URL="http://localhost:${PLUGIN_BACKEND_PORT}" \
OPS_SIGNALS_PROMETHEUS_URL="$OPS_SIGNALS_PROMETHEUS_URL" \
OPS_SIGNALS_DATABASE_URL="${OPS_SIGNALS_DATABASE_URL:-postgresql+psycopg://ops_signals:ops_signals@localhost:5432/ops_signals}" \
NODE_PATH=./node_modules \
  npx playwright test ${PLAYWRIGHT_PROJECT:+--project="$PLAYWRIGHT_PROJECT"} || test_exit_code=$?

exit "$test_exit_code"
