#!/usr/bin/env bash
set -euo pipefail

VERSION="${1:-0.1.0}"
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ARTIFACT_DIR="$ROOT_DIR/dist/release/$VERSION"

mkdir -p "$ARTIFACT_DIR"

PLUGIN_ID="$(python3 - <<'PY'
import json
from pathlib import Path

plugin = json.loads(Path("frontend/plugin.json").read_text())
print(plugin["id"])
PY
)"

PLUGIN_ZIP="$ARTIFACT_DIR/${PLUGIN_ID}-${VERSION}.zip"

echo "Building Grafana plugin artifact"
echo "Version:   $VERSION"
echo "Plugin ID: $PLUGIN_ID"
echo

(
  cd "$ROOT_DIR/frontend"
  npm ci
  npm run build:grafana
)

rm -f "$PLUGIN_ZIP"
(
  cd "$ROOT_DIR/frontend/dist"
  zip -qr "$PLUGIN_ZIP" .
)

SHA1="$(shasum -a 1 "$PLUGIN_ZIP" | awk '{print $1}')"

echo
echo "Grafana plugin artifact:"
echo "  $PLUGIN_ZIP"
echo
echo "SHA1 for Grafana plugin submission:"
echo "  $SHA1"
echo
echo "Local Grafana plugin install path:"
echo "  /var/lib/grafana/plugins/$PLUGIN_ID"
echo
echo "Local Docker Compose development stack:"
echo "  npm --prefix frontend run build:grafana"
echo "  docker compose up -d grafana"
echo
echo "Grafana catalog/marketplace submission uses:"
echo "  URL:  <public URL to $PLUGIN_ZIP>"
echo "  SHA1: $SHA1"
echo "  Source code URL: <public source repository URL>"
