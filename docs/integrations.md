# Integrations

Every way data moves between Ops Signals and something else: metrics coming in, context coming in,
alerts and notifications going out, and the two pluggable surfaces (your own detector, your own AI
provider). Each entry says what it's for and how the wiring actually works - push vs. pull, the
endpoint or setting, and where to read more. "Where you work" (Web UI, Grafana plugin, MCP server)
is listed too, since those are also integration points, just not data pipes.

This doc is the index. The linked pages are the source of truth for exact fields, defaults and
troubleshooting - when the two disagree, trust the linked page and fix this table.

## Data in: metrics

| Integration | What it's for | How it's wired |
|---|---|---|
| **Prometheus** | Your existing metrics, queried on a schedule (autonomous analysis) or on demand (direct/standalone analysis). | Pull. Ops Signals reads the Prometheus HTTP API (`query_range`, `series`, label values, `metadata`, `rules`) on `OPS_SIGNALS_PROMETHEUS_URL`, or on each named connection in `OPS_SIGNALS_PROMETHEUS_CONNECTIONS_FILE`. No agent to install. Every call, by page: [below](#which-prometheus-and-grafana-api-calls-does-ops-signals-make). See [`standalone-prometheus-analysis.md`](standalone-prometheus-analysis.md). |
| **Prometheus-compatible backends** (Grafana Mimir, Thanos, VictoriaMetrics) | Same as above when your "Prometheus" is actually a long-term-storage backend. | Same pull path. For Mimir, list one named connection per tenant (each with its own `X-Scope-OrgID`) in `OPS_SIGNALS_PROMETHEUS_CONNECTIONS_FILE`. Series from different clusters are told apart by the cluster label, and HA replica copies (`prometheus_replica`, `__replica__`) are counted once. See [`standalone-prometheus-analysis.md#mimir-thanos-and-other-multi-source-backends`](standalone-prometheus-analysis.md#mimir-thanos-and-other-multi-source-backends). |
| **OTLP metrics push** | An OpenTelemetry SDK or Collector pushes metrics instead of being scraped. | Push. `POST /api/otlp/v1/metrics` (point your OTel exporter at `<host>/api/otlp`, which appends `/v1/metrics`). Buffered, then analyzed every 10 minutes per series with its recent history; counters become per-second rates. What works with OTLP alone: [OTLP only](otlp.md#using-ops-signals-with-otlp-only). See [`design/otlp-metrics-ingestion-plan.md`](design/otlp-metrics-ingestion-plan.md). |
| **CSV upload** | One-off analysis of a metric you already have as a file, no live connection needed. | Upload. `POST /api/ingestion/csv-validate` to check it, then `POST /api/ingestion/csv-run` to analyze and save it - or, in the UI, **New Analysis** → **Validate Data** to preview and **Analyze and Save** to store the findings. |

### What each source turns on

You don't need every source. Findings, cases, operational memory, Slack notifications and the
assistant work with any metrics source, including OTLP or CSV alone. These need a particular one:

| Feature | Needs | Without it |
|---|---|---|
| Autonomous analysis | A Prometheus-compatible source | It finds and pulls metrics with PromQL |
| Drill-down by pod | A Prometheus-compatible source | It re-runs the finding's query grouped by pod |
| Alert enrichment | Alertmanager and a Prometheus-compatible source | It re-runs the alert's PromQL to see what changed |
| Metric Usage | A Prometheus-compatible source; Grafana makes it complete | Without Grafana it reads Prometheus alert and recording rules only, not dashboards |
| Deploy correlation | Deploy events (`POST /api/events`), or a Prometheus-compatible source with `*_build_info` metrics or kube-state-metrics ([deploy-discovery.md](deploy-discovery.md)) | Findings can't say which deploy came just before |
| Latency percentiles from OTLP | Not yet | OTLP histograms are rejected; percentiles come from Prometheus or CSV |

The app works this out from what is connected and adapts. Features a source can't run yet move to
a "More with Prometheus / Grafana" menu group, and opening one explains what it needs. Each tile on
the **Integrations** page ends with what that source unlocks, and **What works with my data?**
lists every feature with its status. Each finding says where its data came from ("via OTLP"). The
same list is in `GET /api/ingestion/status` under `features`. A configured source that is briefly
unreachable still counts as connected, so the menu doesn't reshuffle when a backend blips.

## Data in: context and history

| Integration | What it's for | How it's wired |
|---|---|---|
| **Alertmanager** | Enrich a firing alert with what happened, what changed, and whether it's been seen before, before anyone opens a dashboard. | Push (webhook). Add Ops Signals as an extra receiver with `continue: true` so your existing routes are untouched: `POST /api/integrations/alertmanager`. Needs `OPS_SIGNALS_ALERT_ENRICHMENT_ENABLED=true` and a matching Prometheus connection. See [`alert-enrichment.md`](alert-enrichment.md). |
| **Generic alert webhook** | The same enrichment for a non-Alertmanager source. | Push. `POST /api/alerts`, a simple JSON shape. See [`alert-enrichment.md`](alert-enrichment.md#how-it-fits-the-architecture). |
| **CI deploy / change events** | Lets findings and alerts say "started N min after deploy `v2.3.1`", and lets pod drill-down credit a rollout to the deploy that started it. | Push. Your pipeline calls `POST /api/events` once per deploy, config change, feature flag, scale event or rollback (`{"service": "...", "type": "deploy", "version": "...", "timestamp": "..."}`, plus `"cluster": "..."` when several clusters share one Prometheus or Mimir, so a deploy is only credited to its own cluster's findings). Optional `Authorization: Bearer <OPS_SIGNALS_EVENTS_TOKEN>`. See [`finding-drilldown.md#how-is-deploy-data-received-from-ci-the-webhook`](finding-drilldown.md#how-is-deploy-data-received-from-ci-the-webhook). |
| **Incident history import** (Jira CSV, PagerDuty CSV, Markdown, or a `.zip` of them) | Backfills operational memory on day one, so "have we seen this before?" has something to match against immediately instead of starting empty. | File upload or CLI, not a live connection. UI: **Recurring problems → Import past incidents**, or the **Integrations** page's Incident history card. CLI: `ops-signals import-cases ./exports`. API: `POST /api/case-imports`. Re-importing the same export changes nothing; every import batch can be undone. See [`importing-incident-history.md`](importing-incident-history.md). |

## Data out: notifications and decision support

| Integration | What it's for | How it's wired |
|---|---|---|
| **Slack - finding notifications** | Push a high-importance finding (from autonomous, manual or OTLP analysis) to the channel your team already watches. | Outgoing webhook. `OPS_SIGNALS_SLACK_ENABLED=true` + `OPS_SIGNALS_SLACK_WEBHOOK_URL`. Posts when importance ≥ `OPS_SIGNALS_SLACK_MIN_IMPORTANCE`. Best-effort: a broken webhook is logged, never fails analysis. See [`alert-enrichment.md#1-finding-notifications`](alert-enrichment.md#1-finding-notifications). |
| **Slack - alert enrichment messages** | The "what happened / what changed / seen before" message for a firing alert (see Alertmanager, above). | Same outgoing-webhook mechanism, separate toggle: `OPS_SIGNALS_ALERT_ENRICHMENT_ENABLED=true`, optionally a separate `OPS_SIGNALS_ALERT_SLACK_WEBHOOK_URL`. See [`alert-enrichment.md#2-alert-enrichment-alertmanager--analyzers--slack`](alert-enrichment.md). |
| **Alert-context API** | Lets an *external* alert manager or script ask "has this happened before, was it real, how was it resolved" before it pages anyone. | Pull, by them. `GET /api/alert-context?metric_name=&service=&message=` returns outcome history, a `likely_real`/`likely_noise`/`insufficient_history` recommendation, and similar resolved cases. Alert Enrichment above calls this same lookup internally. See [`architecture.md`](architecture.md#6-consume). |

## Extending detection and reasoning

| Integration | What it's for | How it's wired |
|---|---|---|
| **HTTP analyzer adapter** | Bring your own model or detection service (a forecasting model, an internal ML service, a vendor API) and have its findings appear next to the built-in analyzers'. | Ops Signals calls out. Register an analyzer with an `analyze_url` (UI: **Experiments → Add Analyzer → I have a hosted API or model**, or a YAML file in `config/analyzer_registry.d/`). The router sends it `POST <analyze_url>` with the series in the analysis window; your service replies with a `findings` list. You host and run the service - Ops Signals never installs or downloads a model. See [`http-analyzer-contract.md`](http-analyzer-contract.md). |
| **AI providers** (Ollama, OpenAI-compatible, Anthropic) | An optional AI second opinion on findings and the "Ask Ops Signals" assistant. Off by default; when on, it can flag disagreement with the router but never overrides its pick. | Ops Signals calls out. `OPS_SIGNALS_AI_ENABLED=1` + `OPS_SIGNALS_AI_PROVIDER=ollama\|openai_compatible\|anthropic`. `openai_compatible` covers vLLM, Azure OpenAI, Bedrock gateways, LiteLLM and OpenAI itself via `OPS_SIGNALS_OPENAI_BASE_URL`/`_MODEL`/`_API_KEY`; `anthropic` via `OPS_SIGNALS_ANTHROPIC_API_KEY`/`_MODEL`. Connection status and a test button live on the **Integrations** page. See [`ask-ops-signals-assistant.md#other-ai-providers`](ask-ops-signals-assistant.md#other-ai-providers). |

## Where you work

| Integration | What it's for | How it's wired |
|---|---|---|
| **Web UI** | The primary surface: findings, cases, operational memory, integrations, experiments. | Self-hosted React app, talks to the backend's `/api`. |
| **Grafana plugin** | Run analysis and see findings without leaving Grafana. | Grafana queries its existing Prometheus datasource, then sends samples to `POST /api/ingestion/prometheus-run` on the Ops Signals backend. See [`grafana-plugin-architecture.md`](grafana-plugin-architecture.md). |
| **MCP server** | Lets an AI assistant or IDE read (and, in write mode, update) findings, cases and analysis runs directly. | Runs over stdio, not a network port: `python -m intelligence.cli mcp` (read-only) or `mcp-write`. See [`mcp-server.md`](mcp-server.md). |

## Which Prometheus and Grafana API calls does Ops Signals make?

Only reads. Ops Signals calls these Prometheus and Grafana HTTP API endpoints, listed by the page
that triggers them, and changes nothing in Prometheus or Grafana. The one write is the plugin saving
its own settings in Grafana. Use the list to set up firewall rules, a gateway allow-list or a
read-only token.

### Prometheus (and Mimir, Thanos, VictoriaMetrics)

Every call goes to the connection's `base_url` with its auth and tenant headers. `query`,
`query_range`, `series` and `labels` are sent as a POST form instead of a GET when the URL would be
too long, so a gateway in front of Prometheus has to allow POST on those four paths.

| Page | When | Endpoint |
|---|---|---|
| **New Analysis** (web UI) and **Interactive Analysis** (plugin, through an Ops Signals connection) | Test Connection | `GET /api/v1/status/buildinfo`; if the backend doesn't serve it, `GET /api/v1/query?query=vector(1)` |
| | Service, Metrics, Cluster and pod lists | `GET /api/v1/label/<name>/values`, with `match[]` to narrow it |
| | Recording rule tag and note on a metric | `GET /api/v1/rules?type=record`, then `GET /api/v1/rules?type=alert` for the alerts that use a rule |
| | Which recording rules have no `service` label | `GET /api/v1/label/__name__/values?match[]={__name__=~"<rules>",service=""}` |
| | Preview Data, Run Analysis, per-pod split and drill-down | `GET /api/v1/query_range` |
| | The result's alert line, alert text and runbook | `GET /api/v1/rules?type=alert` |
| **Autonomous Analysis** | Environment, Services, Namespaces and Clusters lists | `GET /api/v1/label/<label>/values` |
| | Preview, Run once and scheduled runs: finding the metrics | `GET /api/v1/series?match[]=<scope>` in one call; with no scope, or a scope too large for one call, `GET /api/v1/label/__name__/values` then `GET /api/v1/series` in chunks of 80 metric names ([details](autonomous-analysis-preview.md#push-down-scoping-and-anti-starvation-discovery)) |
| | Metric types (counter, gauge, histogram) | `GET /api/v1/metadata` |
| | Analyzing each planned metric, drill-down | `GET /api/v1/query_range` |
| **Findings** (list and View details, both builds) | Alert line, alert text and runbook on findings from a Prometheus connection; never OTLP or CSV. Asked with a 2-second timeout and kept a minute per connection | `GET /api/v1/rules?type=alert` |
| **Findings → View details** | How this was measured (runs from a Prometheus connection only; never OTLP or CSV) | `GET /api/v1/rules?type=record` |
| | Investigate | `GET /api/v1/query_range`, `GET /api/v1/label/<name>/values`, `GET /api/v1/series` |
| **Metric Usage** | Scan | `GET /api/v1/rules`, `GET /api/v1/label/__name__/values`, `GET /api/v1/query` (series per metric and job), `GET /api/v1/metadata` |
| **Setup check**, **Integrations** | Connection check | `GET /api/v1/status/buildinfo`, or `GET /api/v1/query?query=vector(1)` |
| No page: alert enrichment | Alertmanager sends an alert | `GET /api/v1/query_range` |
| No page: deploy discovery | In the background | `GET /api/v1/query`, `GET /api/v1/query_range` ([deploy-discovery.md](deploy-discovery.md)) |

### Grafana

The backend calls Grafana only for Metric Usage and the connection check, with the token set up in
[Metric Usage](metric-usage.md#set-it-up) (Viewer role). The plugin itself uses Grafana's own
services in the browser.

| Page | When | Endpoint |
|---|---|---|
| **Metric Usage** | Scan dashboards and alerts | `GET /api/search`, `GET /api/dashboards/uid/<uid>`, `GET /api/folders`, `GET /api/library-elements/<uid>`, `GET /api/v1/provisioning/alert-rules`, `GET /api/datasources` |
| **Metric Usage**, **Setup check**, **Integrations** | Grafana connection check | `GET /api/health` |
| **Plugin: Interactive Analysis** (Grafana data source) | Service and Metric lists, Run Analysis | Grafana's data source service (`label_values(...)` and range queries); Grafana calls Prometheus itself |
| **Plugin: Configuration** | Saving the backend address | `POST /api/plugins/<plugin-id>/settings` |
| **Plugin: every page** | Reaching the Ops Signals backend | The plugin's proxy route `backend/*`, declared in `plugin.json` |

## Planned, not built yet

- **Jira** (create/sync a Jira issue from a case) - a design only, no code: [`design/proposals/jira-integration-plan.md`](design/proposals/jira-integration-plan.md).

---

Every webhook endpoint above sits behind the same token model: a receiver without its own token
(`OPS_SIGNALS_ALERT_RECEIVER_TOKEN`, `OPS_SIGNALS_EVENTS_TOKEN`) falls back to `OPS_SIGNALS_API_TOKEN`,
and is open only when neither is set. See [`security-model.md`](security-model.md) before exposing
any of these off of a trusted network.
