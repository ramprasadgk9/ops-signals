# Release Packaging Commands

Ops Signals has four release artifacts:

1. Grafana plugin ZIP for Grafana Catalog or Marketplace.
2. Backend API Docker image.
3. Web UI Docker image.
4. MCP server Docker image.

## Build Grafana Plugin

```bash
./scripts/release/build_grafana_plugin_artifact.sh 0.5.0
```

Output (the zip is named after the plugin's own version, `info.version` in `frontend/plugin.json`):

```text
dist/release/0.5.0/<plugin-id>-1.0.34.zip
dist/release/0.5.0/<plugin-id>-1.0.34.zip.sha1
```

The zip holds one folder named after the plugin id, as Grafana expects, so it can be unzipped
straight into Grafana's plugins folder. The script prints the SHA1 needed for Grafana plugin
submission and the command that checks the zip with Grafana's plugin validator.

To sign the plugin, set `GRAFANA_ACCESS_POLICY_TOKEN` (a grafana.com access policy token with the
`plugins:write` scope) before running the script. A private signature also needs
`GRAFANA_SIGN_ROOT_URLS`, the Grafana address(es) the plugin may run on. Without the token the zip is
unsigned and Grafana loads it only with `allow_loading_unsigned_plugins`.

On every `v*` tag the Grafana plugin workflow (`.github/workflows/plugin.yml`) runs the same script.
It signs when the `GRAFANA_ACCESS_POLICY_TOKEN` repository secret is set and attaches the zip to the
tag's GitHub Release, if there is one.

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
IMAGE_REGISTRY=ghcr.io/ramprasadgk9 ./scripts/release/build_deployment_images.sh 0.1.0
```

Push images:

```bash
docker push ghcr.io/ramprasadgk9/ops-signals-backend:0.1.0
docker push ghcr.io/ramprasadgk9/ops-signals-web:0.1.0
docker push ghcr.io/ramprasadgk9/ops-signals-mcp:0.1.0
```

## Build Everything

```bash
IMAGE_REGISTRY=ghcr.io/ramprasadgk9 ./scripts/release/package_release_artifacts.sh 0.1.0
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

Point it at your Prometheus with `OPS_SIGNALS_PROMETHEUS_URL` in `.env` next to the compose file (or
in the shell). From inside the backend container, a Prometheus on the same machine is
`http://host.docker.internal:9090`:

```bash
echo 'OPS_SIGNALS_PROMETHEUS_URL=http://host.docker.internal:9090' >> .env
docker compose -f docker-compose.packaged.yml up -d
```

### Several Mimir tenants with Docker Compose

Add [`docker-compose.connections.yml`](../docker-compose.connections.yml), which mounts a
connections file into the backend:

```bash
cp examples/prometheus-connections.yaml prometheus-connections.yaml   # edit: URLs, tenants, match_labels
printf 'MIMIR_TEAM_A_TOKEN=...\nMIMIR_TEAM_B_TOKEN=...\n' > prometheus-connections.env
docker compose -f docker-compose.packaged.yml -f docker-compose.connections.yml up -d
```

`prometheus-connections.env` holds the values of the `${...}` references in the file (it's optional
when nothing needs a token). Both files are git-ignored. To keep the file elsewhere, set
`OPS_SIGNALS_PROMETHEUS_CONNECTIONS_PATH=/path/to/connections.yaml`.

## Kubernetes Deployment

The chart's defaults pull `ghcr.io/ramprasadgk9/ops-signals-{backend,web,mcp}` at the chart's
`appVersion`, so a plain install uses the matching release:

```bash
kubectl create secret generic ops-signals-db \
  --from-literal=database-url='postgresql+psycopg://USER:PASSWORD@HOST:5432/ops_signals'

helm upgrade --install ops-signals ./helm/ops-signals \
  --set database.urlSecret.name=ops-signals-db
```

Without `database.urlSecret.name`, the chart uses `database.url`, which defaults to local-testing
credentials. Configure these values for a real environment:

```yaml
database:
  urlSecret:
    name: ops-signals-db
    key: database-url

backend:
  env:
    OPS_SIGNALS_QDRANT_URL: http://...
    OPS_SIGNALS_PROMETHEUS_URL: http://...

mcp:
  env:
    OPS_SIGNALS_QDRANT_URL: http://...
```

### Several Mimir tenants with Helm

Put the connections file in `prometheusConnections.config` and the tokens it references in an
existing Secret. The chart renders the file into a ConfigMap, mounts it into the backend and sets
`OPS_SIGNALS_PROMETHEUS_CONNECTIONS_FILE`; each key of the Secret becomes an environment variable:

```bash
kubectl create secret generic mimir-tokens \
  --from-literal=MIMIR_TEAM_A_TOKEN=... --from-literal=MIMIR_TEAM_B_TOKEN=...
```

```yaml
prometheusConnections:
  secretName: mimir-tokens
  config:
    default: team-a
    connections:
      - id: team-a
        name: Mimir team A
        base_url: http://mimir-query-frontend.mimir:8080/prometheus
        bearer_token: ${MIMIR_TEAM_A_TOKEN}
        headers:
          X-Scope-OrgID: team-a
        match_labels:
          tenant: team-a
      - id: team-b
        name: Mimir team B
        base_url: http://mimir-query-frontend.mimir:8080/prometheus
        bearer_token: ${MIMIR_TEAM_B_TOKEN}
        headers:
          X-Scope-OrgID: team-b
        match_labels:
          tenant: team-b
```

With `prometheusConnections.config` set, `OPS_SIGNALS_PROMETHEUS_URL` is ignored. Changes to the
ConfigMap reach the running backend without a restart (after the kubelet syncs the volume).

To pin a different image version, set `backend.image.tag`, `web.image.tag` and `mcp.image.tag`.
See [`security-model.md`](security-model.md) for the API token (`security.apiTokenSecret`).

## Artifact Roles

```text
Grafana plugin ZIP -> installed in Grafana or submitted to Marketplace/Catalog
Backend image      -> FastAPI analysis and application API
Web image          -> standalone React Web UI
MCP image          -> stdio MCP server for agent/tool access
Postgres/Qdrant    -> external stateful dependencies
```
