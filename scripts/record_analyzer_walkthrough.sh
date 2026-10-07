#!/usr/bin/env bash
# Re-record the "add an analyzer" walkthrough video that the Add Analyzer page plays from its
# "Watch how" button, from a running demo stack:
#
#   docker compose -f docker-compose.demo.yml up -d
#   ./scripts/record_analyzer_walkthrough.sh
#
# Writes into frontend/public/walkthroughs/ (served as static files by every frontend build):
#   add-analyzer.webm         the captioned screen recording (about a minute)
#   add-analyzer-poster.png   its title card, shown before the video starts
#   add-analyzer.mp4          only when ffmpeg is on PATH (brew install ffmpeg)
#
# Rebuild the web image afterwards to see the new video in the demo. The analyzer it creates is
# deleted again at the end. Needs the frontend's Playwright browsers
# (cd frontend && npx playwright install chromium).

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
OUTPUT_DIR="${1:-$ROOT_DIR/frontend/public/walkthroughs}"
DEMO_WEB_URL="${DEMO_WEB_URL:-http://localhost:8080}"
WORK_DIR="$(mktemp -d)"
trap 'rm -rf "$WORK_DIR"' EXIT

cd "$ROOT_DIR"

if ! curl -fsS "$DEMO_WEB_URL/api/health" >/dev/null 2>&1; then
  echo "The demo isn't reachable at $DEMO_WEB_URL - start it first (see docs/demo.md)." >&2
  exit 1
fi

DEMO_WEB_URL="$DEMO_WEB_URL" node demo/analyzer_walkthrough/capture.cjs "$WORK_DIR"

mkdir -p "$OUTPUT_DIR"
cp "$WORK_DIR/walkthrough.webm" "$OUTPUT_DIR/add-analyzer.webm"
cp "$WORK_DIR/frames/00.png" "$OUTPUT_DIR/add-analyzer-poster.png"

if command -v ffmpeg >/dev/null 2>&1; then
  ffmpeg -loglevel error -y -i "$WORK_DIR/walkthrough.webm" \
    -c:v libx264 -crf 23 -preset slow -pix_fmt yuv420p -movflags +faststart \
    "$OUTPUT_DIR/add-analyzer.mp4"
else
  echo "ffmpeg not found - skipped the MP4 (the WebM plays in every current browser)."
fi

echo "Walkthrough written under ${OUTPUT_DIR#$ROOT_DIR/}."
