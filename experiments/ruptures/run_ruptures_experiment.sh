#!/usr/bin/env bash

set -euo pipefail
export PYTHONUNBUFFERED=1

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
CONFIG_PATH="${ROOT_DIR}/experiments/ruptures/configs/default.yaml"
CSV_PATH="${ROOT_DIR}/experiments/datasets/rds_cpu_utilization_cc0c53.csv"
VALIDATE_ONLY="${VALIDATE_ONLY:-0}"

usage() {
  cat <<'EOF'
Usage:
  ./experiments/ruptures/run_ruptures_experiment.sh [csv_path] [config_path]

Environment:
  VALIDATE_ONLY=1  Only run syntax/config validation, do not execute the experiment

Examples:
  ./experiments/ruptures/run_ruptures_experiment.sh
  ./experiments/ruptures/run_ruptures_experiment.sh experiments/datasets/my_series.csv
  VALIDATE_ONLY=1 ./experiments/ruptures/run_ruptures_experiment.sh
EOF
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

if [[ -n "${1:-}" ]]; then
  CSV_PATH="$ROOT_DIR/$1"
fi

if [[ -n "${2:-}" ]]; then
  CONFIG_PATH="$ROOT_DIR/$2"
fi

if [[ ! -f "$CSV_PATH" ]]; then
  echo "CSV not found: $CSV_PATH" >&2
  exit 1
fi

if [[ ! -f "$CONFIG_PATH" ]]; then
  echo "Config not found: $CONFIG_PATH" >&2
  exit 1
fi

python3 - <<PY
from pathlib import Path
config_path = Path(r"$CONFIG_PATH")
text = config_path.read_text()
csv_path = r"$CSV_PATH"
if 'csv_path: ""' in text:
    text = text.replace('  csv_path: ""', f'  csv_path: "{csv_path}"')
elif 'csv_path:' in text:
    import re
    text = re.sub(r'(^\\s*csv_path:\\s*).*$',
                  lambda m: f'{m.group(1)}"{csv_path}"',
                  text,
                  flags=re.MULTILINE)
else:
    raise SystemExit("Could not find dataset.csv_path in config")
config_path.write_text(text)
print(f"Updated {config_path} with csv_path={csv_path}")
PY

echo "[1/4] Validating Python syntax..."
python3 -m compileall "$ROOT_DIR/experiments/ruptures/src" "$ROOT_DIR/experiments/ruptures/run_experiment.py" >/dev/null

if [[ "$VALIDATE_ONLY" == "1" ]]; then
  echo "Validation only complete."
  exit 0
fi

echo "[2/4] Checking Python dependencies..."
python3 - <<'PY'
missing = []
for module in ("pandas", "numpy", "yaml", "matplotlib", "ruptures"):
    try:
        __import__(module)
    except ModuleNotFoundError:
        missing.append(module)
if missing:
    print("Missing Python dependencies:", ", ".join(missing))
    print("Install them with: python3 -m pip install -r requirements.txt")
    raise SystemExit(1)
PY

echo "[3/4] Running Ruptures experiment..."
python3 "$ROOT_DIR/experiments/ruptures/run_experiment.py" --config "$CONFIG_PATH"
echo "[4/4] Done."
