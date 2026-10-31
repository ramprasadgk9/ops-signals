#!/usr/bin/env bash
# Re-record the "who can use Ops Signals" walkthrough that Setup check → Login plays: the three steps
# of docs/access.md on a real, throwaway install.
#
#   ./scripts/record_access_walkthrough.sh
#   ./scripts/record_access_walkthrough.sh down   remove a sandbox left running with KEEP=1
#
# Starts its own sandbox and removes it at the end: Postgres and Qdrant, a throwaway Keycloak (through
# scripts/try_keycloak_sign_in.sh, as a second copy), and three backends on one database, one per
# step: no token, a token, company sign-in. Steps 2 and 3 share one web UI address, so the redirect
# address it shows is the one registered in Keycloak: the recorder moves it from the token backend to
# the sign-in backend while the video is on Keycloak's pages. Your run_all.sh stack, the demo and a Keycloak you
# started yourself are not touched. Set KEEP=1 to leave the sandbox running afterwards.
#
# Writes into frontend/public/walkthroughs/:
#   access.webm         the captioned screen recording (about two minutes)
#   access-poster.png   its title card, shown before the video starts
#   access.mp4          only when ffmpeg is on PATH (brew install ffmpeg)
#
# Needs Docker, the project virtualenv and the frontend's Playwright browsers
# (cd frontend && npx playwright install chromium).

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
OUTPUT_DIR="$ROOT_DIR/frontend/public/walkthroughs"
STATE_DIR="$ROOT_DIR/tmp/access-walkthrough"
PYTHON="$ROOT_DIR/.venv/bin/python"
NAME=osaccess
POSTGRES_PORT=5443
QDRANT_PORT=6343
KEYCLOAK_PORT=8181
# A backend per step; steps 2 and 3 share the second web UI.
OPEN_UI=5187 OPEN_API=8104
TOKEN_UI=5188 TOKEN_API=8105
SIGNIN_UI=5188 SIGNIN_API=8106
# The token the sandbox uses. Made up per run; it is never shown in the video.
TOKEN="$(openssl rand -hex 32)"

cd "$ROOT_DIR"
mkdir -p "$STATE_DIR"

keycloak() {
  KEYCLOAK_CONTAINER="$NAME-keycloak" KEYCLOAK_DIR="$STATE_DIR/keycloak" KEYCLOAK_PORT="$KEYCLOAK_PORT" \
    FRONTEND_PORT="$SIGNIN_UI" "$ROOT_DIR/scripts/try_keycloak_sign_in.sh" "$@"
}

start() {
  local name="$1"
  shift
  nohup "$@" >"$STATE_DIR/$name.log" 2>&1 &
  echo $! >"$STATE_DIR/$name.pid"
}

stop() {
  local pid_file="$1" pid
  [[ -f "$pid_file" ]] || return 0
  pid="$(cat "$pid_file")"
  # npm starts vite as a child, so stop the children too.
  pkill -P "$pid" 2>/dev/null || true
  kill "$pid" 2>/dev/null || true
  rm -f "$pid_file"
}

stop_all() {
  for pid_file in "$STATE_DIR"/*.pid; do
    stop "$pid_file"
  done
  docker rm -f "$NAME-postgres" "$NAME-qdrant" >/dev/null 2>&1 || true
  keycloak down >/dev/null 2>&1 || true
}

wait_for() {
  local what="$1" url="$2"
  for _ in {1..90}; do
    curl -fsS -m 3 "$url" >/dev/null 2>&1 && return 0
    sleep 2
  done
  echo "$what did not start. Logs: ${STATE_DIR#$ROOT_DIR/}" >&2
  exit 1
}

backend() {
  local name="$1" port="$2" ui="$3"
  shift 3
  # env -i: no .env, no Prometheus, Grafana or Slack. No --reload.
  start "$name-api" env -i PATH="$PATH" HOME="$HOME" \
    OPS_SIGNALS_DATABASE_URL="postgresql+psycopg://ops_signals:ops_signals@localhost:${POSTGRES_PORT}/ops_signals" \
    OPS_SIGNALS_QDRANT_URL="http://localhost:${QDRANT_PORT}" \
    OPS_SIGNALS_UI_BASE_URL="http://localhost:${ui}" \
    "$@" "$PYTHON" -m uvicorn backend.app.main:app --port "$port"
}

web_ui() {
  local name="$1" port="$2" api="$3"
  shift 3
  (cd "$ROOT_DIR/frontend" && start "$name-ui" env VITE_API_PORT="$api" VITE_FRONTEND_PORT="$port" "$@" \
    npm run dev -- --host 127.0.0.1 --port "$port" --strictPort)
}

# Called by the capture script: the shared web UI now talks to the sign-in backend, with no token
# added (as nginx does with company sign-in on).
if [[ "${1:-}" == "down" ]]; then
  stop_all
  echo "Sandbox removed."
  exit 0
fi

if [[ "${1:-}" == "_to-sign-in" ]]; then
  stop "$STATE_DIR/token-ui.pid"
  for _ in {1..20}; do
    curl -fsS -m 1 "http://localhost:${SIGNIN_UI}" >/dev/null 2>&1 || break
    sleep 0.5
  done
  web_ui signin "$SIGNIN_UI" "$SIGNIN_API"
  wait_for "The sign-in web UI" "http://localhost:${SIGNIN_UI}"
  exit 0
fi

if [[ "${KEEP:-}" != "1" ]]; then
  trap stop_all EXIT
fi
stop_all

echo "Starting Postgres, Qdrant and Keycloak for the sandbox..."
docker run -d --name "$NAME-postgres" -p "${POSTGRES_PORT}:5432" \
  -e POSTGRES_USER=ops_signals -e POSTGRES_PASSWORD=ops_signals -e POSTGRES_DB=ops_signals \
  -v "$ROOT_DIR/sql/init.sql:/docker-entrypoint-initdb.d/init.sql:ro" postgres:16 >/dev/null
docker run -d --name "$NAME-qdrant" -p "${QDRANT_PORT}:6333" qdrant/qdrant:latest >/dev/null
keycloak up --no-start >"$STATE_DIR/keycloak-up.log"
# Group names, not paths, so the Admin and Editor lists match.
keycloak path-off >/dev/null
for _ in {1..30}; do
  docker exec "$NAME-postgres" pg_isready -U ops_signals -d ops_signals >/dev/null 2>&1 && break
  sleep 2
done

SIGN_IN_ENV=()
while IFS= read -r line; do
  [[ -z "$line" || "$line" == \#* || "$line" == OPS_SIGNALS_API_TOKEN=* ]] && continue
  SIGN_IN_ENV+=("${line//\"/}")
done <"$STATE_DIR/keycloak/keycloak.env"

echo "Starting the three backends and web UIs..."
backend open "$OPEN_API" "$OPEN_UI"
wait_for "The first backend" "http://localhost:${OPEN_API}/api/health"
backend token "$TOKEN_API" "$TOKEN_UI" OPS_SIGNALS_API_TOKEN="$TOKEN"
backend signin "$SIGNIN_API" "$SIGNIN_UI" OPS_SIGNALS_API_TOKEN="$TOKEN" "${SIGN_IN_ENV[@]}"
web_ui open "$OPEN_UI" "$OPEN_API"
web_ui token "$TOKEN_UI" "$TOKEN_API" OPS_SIGNALS_DEV_PROXY_API_TOKEN="$TOKEN"
wait_for "The token backend" "http://localhost:${TOKEN_API}/api/health"
wait_for "The sign-in backend" "http://localhost:${SIGNIN_API}/api/health"
for port in "$OPEN_UI" "$TOKEN_UI"; do
  wait_for "The web UI on :$port" "http://localhost:${port}"
done

WORK_DIR="$STATE_DIR/work"
rm -rf "$WORK_DIR"
OPEN_URL="http://localhost:${OPEN_UI}" TOKEN_URL="http://localhost:${TOKEN_UI}" SIGNIN_URL="http://localhost:${SIGNIN_UI}" \
  KEYCLOAK_URL="http://127.0.0.1:${KEYCLOAK_PORT}" TO_SIGN_IN="$0 _to-sign-in" \
  node demo/access_walkthrough/capture.cjs "$WORK_DIR"

mkdir -p "$OUTPUT_DIR"
cp "$WORK_DIR/walkthrough.webm" "$OUTPUT_DIR/access.webm"
cp "$WORK_DIR/frames/00.png" "$OUTPUT_DIR/access-poster.png"
if command -v ffmpeg >/dev/null 2>&1; then
  ffmpeg -loglevel error -y -i "$WORK_DIR/walkthrough.webm" \
    -c:v libx264 -crf 23 -preset slow -pix_fmt yuv420p -movflags +faststart \
    "$OUTPUT_DIR/access.mp4"
else
  echo "ffmpeg not found - skipped the MP4 (the WebM plays in every current browser)."
fi

echo "Walkthrough written under ${OUTPUT_DIR#$ROOT_DIR/}."
if [[ "${KEEP:-}" == "1" ]]; then
  echo "Sandbox left running: :${OPEN_UI} (open) and :${SIGNIN_UI} (company sign-in). Run without KEEP to remove it."
fi
