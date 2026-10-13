#!/usr/bin/env bash
# Re-record the README's "OTLP only" walkthrough: a one-minute captioned video and the GIF made from
# it. Needs two sandboxes, one empty and one a real Collector has been sending to for about an hour:
#
#   SANDBOX_NAME=osempty SANDBOX_UI_PORT=5185 SANDBOX_BACKEND_PORT=8102 SANDBOX_POSTGRES_PORT=5441 SANDBOX_QDRANT_PORT=6341 ./scripts/otlp_sandbox.sh up
#   ./scripts/otlp_sandbox.sh up
#   ./scripts/otlp_sandbox.sh collector
#   ./scripts/record_otlp_walkthrough.sh
#
# Writes docs/screenshots/images/web/otlp-only.gif and docs/screenshots/videos/otlp-only.webm
# (and .mp4 when ffmpeg is on PATH). Needs the frontend's Playwright browsers
# (cd frontend && npx playwright install chromium) and the project virtualenv (for Pillow).

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
EMPTY_URL="${EMPTY_URL:-http://localhost:5185}"
LIVE_URL="${LIVE_URL:-http://localhost:5184}"
PYTHON="${PYTHON_BIN:-$ROOT_DIR/.venv/bin/python}"
GIF="$ROOT_DIR/docs/screenshots/images/web/otlp-only.gif"
VIDEO_DIR="$ROOT_DIR/docs/screenshots/videos"
WORK_DIR="$(mktemp -d)"
trap 'rm -rf "$WORK_DIR"' EXIT

cd "$ROOT_DIR"

for url in "$EMPTY_URL" "$LIVE_URL"; do
  if ! curl -fsS "$url/api/health" >/dev/null 2>&1; then
    echo "No sandbox answers at $url - start both first (see the top of this script)." >&2
    exit 1
  fi
done

EMPTY_URL="$EMPTY_URL" LIVE_URL="$LIVE_URL" node demo/otlp_walkthrough/capture.cjs "$WORK_DIR"
"$PYTHON" demo/gif/build_gif.py "$WORK_DIR/frames" "$GIF"

mkdir -p "$VIDEO_DIR"
cp "$WORK_DIR/walkthrough.webm" "$VIDEO_DIR/otlp-only.webm"
if command -v ffmpeg >/dev/null 2>&1; then
  ffmpeg -loglevel error -y -i "$WORK_DIR/walkthrough.webm" \
    -c:v libx264 -crf 23 -preset slow -pix_fmt yuv420p -movflags +faststart \
    "$VIDEO_DIR/otlp-only.mp4"
else
  echo "ffmpeg not found - skipped the MP4 (the WebM plays in every current browser)."
fi

echo "Walkthrough written: ${GIF#$ROOT_DIR/} and ${VIDEO_DIR#$ROOT_DIR/}/."
