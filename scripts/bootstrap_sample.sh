#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
VENV_DIR="${ROOT_DIR}/.venv"

pick_python() {
  if [[ -n "${PYTHON_BIN:-}" ]]; then
    echo "$PYTHON_BIN"
    return
  fi

  for candidate in python3.14 python3.12 python3.11 python3; do
    if command -v "$candidate" >/dev/null 2>&1; then
      echo "$candidate"
      return
    fi
  done

  echo "python3"
}

PYTHON_BIN="$(pick_python)"

cd "$ROOT_DIR"

if ! command -v docker >/dev/null 2>&1; then
  echo "docker is required"
  exit 1
fi

if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  echo "$PYTHON_BIN is required"
  exit 1
fi

venv_python_version=""
if [[ -x "$VENV_DIR/bin/python" ]]; then
  venv_python_version="$($VENV_DIR/bin/python -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
fi

selected_python_version="$($PYTHON_BIN -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"

if [[ "$selected_python_version" != "3.14" && "$selected_python_version" != "3.12" && "$selected_python_version" != "3.11" ]]; then
  echo "Unsupported Python version selected: $selected_python_version"
  echo "Use PYTHON_BIN to point to python3.14, python3.12, or python3.11."
  exit 1
fi

if [[ -d "$VENV_DIR" && "$venv_python_version" != "$selected_python_version" ]]; then
  rm -rf "$VENV_DIR"
fi

if [[ ! -d "$VENV_DIR" ]]; then
  "$PYTHON_BIN" -m venv "$VENV_DIR"
fi

"$VENV_DIR/bin/python" -m pip install --upgrade pip
"$VENV_DIR/bin/pip" install -r requirements.txt

docker compose up -d postgres

echo "Waiting for postgres to become ready..."
for attempt in {1..30}; do
  if docker compose exec -T postgres pg_isready -U ops_signals -d ops_signals >/dev/null 2>&1; then
    break
  fi
  if [[ "$attempt" -eq 30 ]]; then
    echo "postgres did not become ready in time"
    exit 1
  fi
  echo "  attempt ${attempt}/30"
  sleep 2
done

"$VENV_DIR/bin/python" -m ops_signals.cli init-db --config config.yaml
"$VENV_DIR/bin/python" -m ops_signals.cli run --config config.yaml

echo
echo "Verifying inserted rows..."
docker compose exec -T postgres psql -U ops_signals -d ops_signals -c "select count(*) as normalized_points from ops_normalized_timeseries_points;"
docker compose exec -T postgres psql -U ops_signals -d ops_signals -c "select count(*) as signals from ops_operational_signals;"
docker compose exec -T postgres psql -U ops_signals -d ops_signals -c "select id, signal_type, metric_name, severity, status from ops_operational_signals order by id limit 10;"