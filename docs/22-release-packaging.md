# Release Packaging Commands

Ops Signals has four release artifacts:

1. Grafana plugin ZIP for Grafana Catalog or Marketplace.
2. Backend API Docker image.
3. Web UI Docker image.
4. MCP server Docker image.

## Build Grafana Plugin

```bash
./scripts/release/build_grafana_plugin_artifact.sh 0.1.0
```

Output:

```text
dist/release/0.1.0/<plugin-id>-0.1.0.zip
```

The script also prints the SHA1 needed for Grafana plugin submission.

## Build Deployment Images

```bash
./scripts/release/build_deployment_images.sh 0.1.0
```

Default image names:

```text
ghcr.io/your-org/ops-signals-backend:0.1.0
ghcr.io/your-org/ops-signals-web:0.1.0
ghcr.io/your-org/ops-signals-mcp:0.1.0
```

Use your own registry:

```bash
IMAGE_REGISTRY=ghcr.io/ramprasad ./scripts/release/build_deployment_images.sh 0.1.0
```

Push images:

```bash
docker push ghcr.io/ramprasad/ops-signals-backend:0.1.0
docker push ghcr.io/ramprasad/ops-signals-web:0.1.0
docker push ghcr.io/ramprasad/ops-signals-mcp:0.1.0
```

## Build Everything

```bash
IMAGE_REGISTRY=ghcr.io/ramprasad ./scripts/release/package_release_artifacts.sh 0.1.0
```

This builds the Grafana plugin ZIP and all three deployment images.

## Local Deployment

```bash
docker compose -f docker-compose.packaged.yml up -d
```

Services:

```text
Backend API: http://localhost:8000
Web UI:      http://localhost:8080
Postgres:    localhost:5432
Qdrant:      http://localhost:6333
```

## Kubernetes Deployment

```bash
helm upgrade --install ops-signals ./helm/ops-signals \
  --set backend.image.repository=ghcr.io/ramprasad/ops-signals-backend \
  --set backend.image.tag=0.1.0 \
  --set web.image.repository=ghcr.io/ramprasad/ops-signals-web \
  --set web.image.tag=0.1.0 \
  --set mcp.image.repository=ghcr.io/ramprasad/ops-signals-mcp \
  --set mcp.image.tag=0.1.0
```

Configure these values for a real environment:

```yaml
backend:
  env:
    OPS_INTEL_DATABASE_URL: postgresql+psycopg://...
    OPS_SIGNALS_QDRANT_URL: http://...
    OPS_SIGNALS_PROMETHEUS_URL: http://...

mcp:
  env:
    OPS_INTEL_DATABASE_URL: postgresql+psycopg://...
    OPS_SIGNALS_QDRANT_URL: http://...
```

## Artifact Roles

```text
Grafana plugin ZIP -> installed in Grafana or submitted to Marketplace/Catalog
Backend image      -> FastAPI analysis and application API
Web image          -> standalone React Web UI
MCP image          -> stdio MCP server for agent/tool access
Postgres/Qdrant    -> external stateful dependencies
```
