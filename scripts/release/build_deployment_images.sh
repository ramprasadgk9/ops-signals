#!/usr/bin/env bash
set -euo pipefail

VERSION="${1:-0.6.4}"
IMAGE_REGISTRY="${IMAGE_REGISTRY:-ghcr.io/your-org}"
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

BACKEND_IMAGE="$IMAGE_REGISTRY/ops-signals-backend:$VERSION"
WEB_IMAGE="$IMAGE_REGISTRY/ops-signals-web:$VERSION"
MCP_IMAGE="$IMAGE_REGISTRY/ops-signals-mcp:$VERSION"

echo "Building Ops Signals deployment images"
echo "Version:        $VERSION"
echo "Image registry: $IMAGE_REGISTRY"
echo

docker build \
  -f "$ROOT_DIR/docker/backend.Dockerfile" \
  -t "$BACKEND_IMAGE" \
  "$ROOT_DIR"

docker build \
  -f "$ROOT_DIR/docker/web.Dockerfile" \
  -t "$WEB_IMAGE" \
  "$ROOT_DIR"

docker build \
  -f "$ROOT_DIR/docker/mcp.Dockerfile" \
  -t "$MCP_IMAGE" \
  "$ROOT_DIR"

echo
echo "Built images:"
echo "  $BACKEND_IMAGE"
echo "  $WEB_IMAGE"
echo "  $MCP_IMAGE"
echo
echo "Local Docker Compose deployment:"
echo "  docker compose -f docker-compose.packaged.yml up -d"
echo
echo "Kubernetes Helm deployment:"
echo "  helm upgrade --install ops-signals ./helm/ops-signals \\"
echo "    --set backend.image.repository=$IMAGE_REGISTRY/ops-signals-backend \\"
echo "    --set backend.image.tag=$VERSION \\"
echo "    --set web.image.repository=$IMAGE_REGISTRY/ops-signals-web \\"
echo "    --set web.image.tag=$VERSION \\"
echo "    --set mcp.image.repository=$IMAGE_REGISTRY/ops-signals-mcp \\"
echo "    --set mcp.image.tag=$VERSION"
echo
echo "To push images:"
echo "  docker push $BACKEND_IMAGE"
echo "  docker push $WEB_IMAGE"
echo "  docker push $MCP_IMAGE"
