#!/usr/bin/env bash
set -euo pipefail

VERSION="${1:-0.6.0}"
IMAGE_REGISTRY="${IMAGE_REGISTRY:-ghcr.io/your-org}"
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ARTIFACT_DIR="$ROOT_DIR/dist/release/$VERSION"

mkdir -p "$ARTIFACT_DIR"

echo "Building Grafana plugin..."
"$ROOT_DIR/scripts/release/build_grafana_plugin_artifact.sh" "$VERSION"

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
