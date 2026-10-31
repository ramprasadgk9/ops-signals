# Getting started

What to do after the [README Quick Start](../README.md#quick-start) (`./scripts/setup.sh`, then
`./scripts/run_all.sh`): point the install at your own data, connect sources, and fix what doesn't
start. Running it for a team instead of on your laptop is in [`deploy.md`](deploy.md).

## Point It at Your Own Prometheus (Optional)

Skip this to start with the bundled Prometheus and mock metrics. You can do it any time later; see
[Switching later](data-sources.md#switching-later).

```bash
cp .env.example .env
```

`run_all.sh` reads `.env` itself. Then, in `.env`, pick the line that fits:

- **One Prometheus, or Mimir/Thanos/VictoriaMetrics with one tenant** (clusters are told apart by
  their `cluster` label):

  ```bash
  OPS_SIGNALS_PROMETHEUS_URL=https://prometheus.example.com
  ```

  Add `OPS_SIGNALS_PROMETHEUS_BEARER_TOKEN` (or `_USERNAME`/`_PASSWORD`) for auth, and
  `OPS_SIGNALS_PROMETHEUS_HEADERS=X-Scope-OrgID:your-tenant` for a Mimir tenant.

- **Several Mimir tenants, or several separate Prometheus servers**: list them in a connections file.

  ```bash
  cp examples/prometheus-connections.yaml prometheus-connections.yaml
  ```

  Edit it (one entry per tenant or server; tokens stay in `.env` as `${VARIABLES}`), then set:

  ```bash
  OPS_SIGNALS_PROMETHEUS_CONNECTIONS_FILE=prometheus-connections.yaml
  ```

The [Prometheus](data-sources.md#prometheus) section has the details. With either set, `run_all.sh`
doesn't start the bundled Prometheus and mock metrics (`OPS_SIGNALS_LOCAL_PROMETHEUS=true` starts
them anyway).

## Connect a Data Source

Findings will be empty on a fresh install - that's expected, nothing has been analyzed yet. Until
the first data arrives, the Overview shows a **Get data in** panel with every way in:

- **OTLP** - the endpoint to point an OTel Collector or SDK at, with a config snippet (see
  [`otlp.md`](otlp.md)).
- **Alertmanager** - the webhook URL and a `receivers:` snippet; **Send test alert** proves the
  whole path once alert enrichment is on (see [`alert-enrichment.md`](alert-enrichment.md)).
- **Prometheus** - pulled on a schedule once `OPS_SIGNALS_PROMETHEUS_URL` is set in `.env`, or
  `OPS_SIGNALS_PROMETHEUS_CONNECTIONS_FILE` for several Mimir tenants (see
  [Prometheus](data-sources.md#prometheus)).
- **Deploy events** - the URL and a `curl` step for your CI pipeline, so alerts and findings can say
  which deploy came just before a change (see
  [Deploy and change events](data-sources.md#deploy-and-change-events)).
- **Load demo data** - analyzes a bundled checkout series in seconds, or upload your own CSV from
  **New Analysis**: **Validate Data** previews it, **Analyze and Save** stores the findings so you can
  create cases from them (see [CSV Input](data-sources.md#csv-input)).

The same sources, with whether each is receiving, live on the **Integrations** page
(`/integrations`) afterwards; received alerts are on the **Alerts** page (`/alerts`). The APIs behind
them are `GET /api/ingestion/status` and `GET /api/alerts`.

## Optional: Enable Local AI

By default everything runs on deterministic retrieval and templates - no AI, no API key, no network
calls out. To add local LLM-assisted answers on top of that (never instead of it):

```bash
docker compose --profile ai up -d
```

This starts a local Ollama container and pulls a small default model (`qwen2.5:3b`, ~2GB, once).
Then point the backend at it:

```bash
OPS_SIGNALS_AI_ENABLED=1 OPS_SIGNALS_AI_PROVIDER=ollama ./scripts/run_all.sh
```

For other providers (vLLM, Azure OpenAI, Bedrock gateways, LiteLLM, Anthropic) see
[Other AI Providers](ask-ops-signals-assistant.md#other-ai-providers); [`ai-features.md`](ai-features.md)
lists what each feature adds.

## Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| `docker is required` | Docker isn't installed, or the daemon isn't running | Install/start Docker Desktop (or Docker Engine on Linux) |
| `Unsupported Python version selected: 3.13` | System Python is 3.13, which `setup.sh` rejects | Install 3.12 (recommended), 3.11 or 3.14, then run `PYTHON_BIN=python3.12 ./scripts/setup.sh` |
| `npm is required to install frontend dependencies` | Node.js/npm isn't installed | Install Node.js 20+ |
| `postgres did not become ready in time` or `qdrant did not become ready in time` | Docker is still starting, or the port is already taken | `docker compose ps` and `docker compose logs postgres` (or `qdrant`); confirm ports `5432`/`6333` are free |
| A port (`8001`, `5174`, `9090`) is already in use | Another process is bound to it | Stop that process, or see `scripts/run_all.sh` for the ports it uses |
| `permission denied` running a script | The script isn't marked executable | `chmod +x scripts/*.sh` |
| It starts, but something doesn't work | A connection, token or setting is wrong | Open **Setup check** in the web UI: each red or yellow row has **How to fix**. **Copy report** gives a text summary (without secrets) to paste into an issue |

## Scripts Reference

| Script | What it does | When to use it | Ports |
| --- | --- | --- | --- |
| `./scripts/setup.sh` | Installs Python and frontend deps, starts Postgres and Qdrant, and initializes the database. | First-time setup or after a clean checkout. | Postgres `5432`, Qdrant `6333` |
| `./scripts/run_all.sh` | Starts the standalone backend, frontend, Postgres, Qdrant, and - until `.env` points at your own Prometheus - a bundled Prometheus with mock metrics. | Daily local development outside Grafana. | Backend `8001`, frontend `5174`, Prometheus `9090` |
| `./scripts/multicluster.sh up`, then `app` | Starts a local Grafana Mimir with several clusters, an HA pair and two tenants, then the app with one connection per tenant. | Testing multi-cluster and multi-tenant behaviour; not for real deployments. See [`testing-multicluster-locally.md`](testing-multicluster-locally.md). | Mimir `9009`, plus the `run_all.sh` ports |
| `./scripts/try_keycloak_sign_in.sh up` | Starts a throwaway Keycloak (open-source identity provider) with test users and groups, sets the web UI's company sign-in up against it, then starts the app. | Seeing sign-in and roles work with a real provider before onboarding a team; for this computer only. See [`try-company-sign-in.md`](try-company-sign-in.md). | Keycloak `8180`, plus the `run_all.sh` ports |
| `./scripts/run_grafana_stack.sh` | Builds the Grafana plugin, starts Grafana, Prometheus, mock metrics, and the plugin backend. | Testing the Grafana plugin experience. See [`grafana-plugin-local-setup.md`](grafana-plugin-local-setup.md). | Grafana `3000`, Prometheus `9090`, backend `8002` |
| `./scripts/test_mcp.sh` | Starts the MCP server and verifies `initialize` and `tools/list`. | Checking MCP locally without Codex. See [`mcp-server.md`](mcp-server.md). | None; stdio only |
| `MCP_MODE=mcp-write ./scripts/test_mcp.sh` | Verifies the write-enabled MCP tool list. | Confirming write-capable tools are exposed. | None; stdio only |

`3000` is reserved for Grafana, `8002` for the Grafana/plugin backend - they don't conflict with the standalone app's `8001`/`5174`.
