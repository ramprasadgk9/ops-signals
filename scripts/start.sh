#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
VENV_DIR="${ROOT_DIR}/.venv"

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
for attempt in {1..30}; do
  if curl -fsS http://localhost:6333/readyz >/dev/null 2>&1 || curl -fsS http://localhost:6333/healthz >/dev/null 2>&1; then
    break
  fi
  if [[ "$attempt" -eq 30 ]]; then
    echo "qdrant did not become ready in time"
    exit 1
  fi
  sleep 2
done

if [[ "${1:-}" == "frontend" ]]; then
  cd frontend
  npm run dev
else
  exec "$VENV_DIR/bin/python" -m intelligence.cli run --config config.yaml
fi
