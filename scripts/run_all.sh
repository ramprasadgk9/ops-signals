#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
VENV_DIR="${ROOT_DIR}/.venv"
BACKEND_PORT="${BACKEND_PORT:-8001}"
FRONTEND_PORT="${FRONTEND_PORT:-5174}"

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

docker compose up -d postgres qdrant

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

"$VENV_DIR/bin/python" -m intelligence.cli init-db --config config.yaml

api_log="${ROOT_DIR}/.tmp_ops_signals_api.log"
ui_log="${ROOT_DIR}/.tmp_ops_signals_ui.log"

echo "Starting backend API on :${BACKEND_PORT}..."
BACKEND_PORT="$BACKEND_PORT" "$VENV_DIR/bin/python" -m uvicorn backend.app.main:app --reload --port "$BACKEND_PORT" >"$api_log" 2>&1 &
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
echo "MCP server:   ./.venv/bin/python -m intelligence.cli mcp"
echo "MCP write:    ./.venv/bin/python -m intelligence.cli mcp-write"
echo "Press Ctrl+C to stop the services started by this script."

wait
