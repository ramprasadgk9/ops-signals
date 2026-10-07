#!/usr/bin/env bash
# Re-record the "track a case in Jira" walkthrough video, from a running demo stack with ticketing
# on and connected to a Jira Cloud project you can write to (a free site is enough):
#
#   ./scripts/record_jira_walkthrough.sh --login    # once: log in to Jira so the video can show it
#   ./scripts/record_jira_walkthrough.sh
#
# Jira settings are read from $JIRA_ENV_FILE (default ~/.ops-signals-jira.env): the
# OPS_SIGNALS_TICKETING_* and OPS_SIGNALS_JIRA_* variables from docs/configuration.md. The same file
# goes to the demo backend, e.g. with a compose override that adds it as the backend's env_file.
# The saved Jira login goes to $JIRA_BROWSER_STATE (default ~/.ops-signals-jira-browser.json).
# Keep both outside the repository.
#
# Each run opens a fresh demo case and creates one real ticket in the Jira project (it is resolved
# by the end of the video). Writes into frontend/public/walkthroughs/:
#   jira-ticketing.webm         the captioned screen recording (about a minute)
#   jira-ticketing-poster.png   its title card, shown before the video starts
#   jira-ticketing.mp4          only when ffmpeg is on PATH (brew install ffmpeg)
#
# Needs the frontend's Playwright browsers (cd frontend && npx playwright install chromium).

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
OUTPUT_DIR="$ROOT_DIR/frontend/public/walkthroughs"
DEMO_WEB_URL="${DEMO_WEB_URL:-http://localhost:8080}"
JIRA_ENV_FILE="${JIRA_ENV_FILE:-$HOME/.ops-signals-jira.env}"
export JIRA_BROWSER_STATE="${JIRA_BROWSER_STATE:-$HOME/.ops-signals-jira-browser.json}"

cd "$ROOT_DIR"

if [[ ! -f "$JIRA_ENV_FILE" ]]; then
  echo "No Jira settings at $JIRA_ENV_FILE (see the header of this script)." >&2
  exit 1
fi
set -a
source "$JIRA_ENV_FILE"
set +a

if [[ "${1:-}" == "--login" ]]; then
  node demo/jira_walkthrough/login.cjs "$OPS_SIGNALS_JIRA_BASE_URL" "$JIRA_BROWSER_STATE"
  exit 0
fi

if ! curl -fsS "$DEMO_WEB_URL/api/integrations/ticketing/status" 2>/dev/null | grep -q '"provider_configured":true'; then
  echo "Ticketing isn't on in the demo at $DEMO_WEB_URL - start it with the Jira settings (see the header of this script)." >&2
  exit 1
fi
if [[ ! -f "$JIRA_BROWSER_STATE" ]]; then
  echo "No saved Jira login at $JIRA_BROWSER_STATE - recording without the Jira pages (run with --login to include them)."
fi

WORK_DIR="$(mktemp -d)"
trap 'rm -rf "$WORK_DIR"' EXIT

CASE_ID="$(DEMO_WEB_URL="$DEMO_WEB_URL" python3 demo/jira_walkthrough/new_case.py)"
echo "Recording on demo case #$CASE_ID"
DEMO_WEB_URL="$DEMO_WEB_URL" node demo/jira_walkthrough/capture.cjs "$WORK_DIR" "$CASE_ID"

mkdir -p "$OUTPUT_DIR"
cp "$WORK_DIR/walkthrough.webm" "$OUTPUT_DIR/jira-ticketing.webm"
cp "$WORK_DIR/frames/00.png" "$OUTPUT_DIR/jira-ticketing-poster.png"

if command -v ffmpeg >/dev/null 2>&1; then
  ffmpeg -loglevel error -y -i "$WORK_DIR/walkthrough.webm" \
    -c:v libx264 -crf 23 -preset slow -pix_fmt yuv420p -movflags +faststart \
    "$OUTPUT_DIR/jira-ticketing.mp4"
else
  echo "ffmpeg not found - skipped the MP4 (the WebM plays in every current browser)."
fi

echo "Walkthrough written under ${OUTPUT_DIR#$ROOT_DIR/}."
