#!/usr/bin/env bash
set -euo pipefail

VERSION="${1:-0.1.0}"
IMAGE_REGISTRY="${IMAGE_REGISTRY:-ghcr.io/your-org}"
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ARTIFACT_DIR="$ROOT_DIR/dist/release/$VERSION"

mkdir -p "$ARTIFACT_DIR"

echo "Building Grafana plugin..."
(
  cd "$ROOT_DIR/frontend"
  npm ci
  npm run build:grafana
)

PLUGIN_ID="$(python3 - <<'PY'
import json
from pathlib import Path
plugin = json.loads(Path("frontend/plugin.json").read_text())
print(plugin["id"])
PY
)"
PLUGIN_ZIP="$ARTIFACT_DIR/${PLUGIN_ID}-${VERSION}.zip"
(
  cd "$ROOT_DIR/frontend/dist"
  zip -qr "$PLUGIN_ZIP" .
)
echo "Plugin ZIP: $PLUGIN_ZIP"

echo "Building Docker images..."
docker build -f "$ROOT_DIR/docker/backend.Dockerfile" -t "$IMAGE_REGISTRY/ops-signals-backend:$VERSION" "$ROOT_DIR"
docker build -f "$ROOT_DIR/docker/web.Dockerfile" -t "$IMAGE_REGISTRY/ops-signals-web:$VERSION" "$ROOT_DIR"
docker build -f "$ROOT_DIR/docker/mcp.Dockerfile" -t "$IMAGE_REGISTRY/ops-signals-mcp:$VERSION" "$ROOT_DIR"

cat > "$ARTIFACT_DIR/images.txt" <<EOF
$IMAGE_REGISTRY/ops-signals-backend:$VERSION
$IMAGE_REGISTRY/ops-signals-web:$VERSION
$IMAGE_REGISTRY/ops-signals-mcp:$VERSION
EOF

echo "Release artifacts written to $ARTIFACT_DIR"
