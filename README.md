# Ops Signals

[![CI](https://github.com/ramprasadgk9/ops-signals/actions/workflows/ci.yml/badge.svg)](https://github.com/ramprasadgk9/ops-signals/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Release](https://img.shields.io/github/v/release/ramprasadgk9/ops-signals)](https://github.com/ramprasadgk9/ops-signals/releases)

<h2 align="center"><i>"Never debug the same incident twice."</i></h2>

Open-source and self-hosted for Prometheus and OpenTelemetry: Ops Signals explains every metric
change in plain language, links it to the deploy behind it, and remembers how each incident was
fixed.

It sits next to your Prometheus, Grafana and Alertmanager, analyzes metrics with published
detection methods, and needs no LLM. It adds to your observability stack; it doesn't replace it.

![Ops Signals demo: a deploy causes a latency shift, the alert is enriched with what happened, what changed, and a matching past incident](docs/screenshots/images/demo/ops-signals-demo.gif)

### Already on OpenTelemetry?

Point your Collector at Ops Signals; no Prometheus needed. Findings, cases, operational memory and
Slack notifications work from OTLP alone; a few features still need Prometheus.
[What you get with OTLP only →](#using-ops-signals-with-otlp-only)

![OTLP only: from an empty install to findings from live Collector data](docs/screenshots/images/web/otlp-only.gif)

### Try it in one command

```bash
git clone https://github.com/ramprasadgk9/ops-signals.git
cd ops-signals
docker compose -f docker-compose.demo.yml up
```

This starts Ops Signals with an incident already in progress: a deploy, then a latency shift, then
a Prometheus alert. About a minute later, open **http://localhost:8090** to see the enriched alert
as it would appear in Slack, and **http://localhost:8080** for the full UI. You only need Docker:
no Python, Node, Slack workspace or data of your own. See [`docs/demo.md`](docs/demo.md) for what's
running and how it works.

> **Run it on a trusted network.** The API has no authentication unless you set
> `OPS_SIGNALS_API_TOKEN`. Don't expose it to the internet. See [Security model](#security-model).

New here? [`docs/README.md`](docs/README.md) is a guided path through every doc referenced below.

## Contents

- [The Problem](#the-problem)
- [What Ops Signals Does](#what-ops-signals-does)
- [What Makes It Different](#what-makes-it-different)
- [How It Works](#how-it-works)
- [Product Overview](#product-overview) (screenshots)
- [Quick Start](#quick-start): [choose how to run it](#choose-how-to-run-it), [laptop install](#try-it-on-your-laptop), [troubleshooting](#troubleshooting), [security model](#security-model)
- [Deploy for Your Team](#deploy-for-your-team): [Docker Compose](#one-server-docker-compose), [Helm](#kubernetes-helm), [Grafana plugin](#add-the-grafana-plugin)
- [Architecture](#architecture)
- [Using Ops Signals](#using-ops-signals): [feature map](#where-to-find-each-feature), [Ask Ops Signals](#operational-intelligence-assistant)
- [Data, Automation & Configuration](#data-automation--configuration): [data sources](#data-sources), [autonomous analysis](#autonomous-analysis), [metric usage](#metric-usage), [YAML config](#yaml-configuration)
- [Integrations](#integrations): [Grafana plugin](#grafana-plugin), [MCP](#mcp-server), [OTLP](#otlp-metrics-ingestion) ([OTLP only: what you get](#using-ops-signals-with-otlp-only)), [Slack](#slack-notifications), [alert enrichment](#alert-enrichment-alertmanager-to-slack), [Jira](#pluggable-case-ticketing-jira-cloud)
- [Example Finding](#example-operational-finding)
- [Current Limitations](#current-limitations) · [Roadmap](#roadmap) · [Contributing](#contributing) · [License](#license)

## The Problem

An alert fires: `checkout` latency is up. Before anyone can fix anything, the on-call engineer
answers the same three questions by hand:

1. **What happened?** Is it a spike, a new baseline, a slow trend, or noise? A dashboard draws the
   line; it doesn't say which.
2. **What changed?** Was there a deploy or config change just before? That lives in CI, not next to
   the graph.
3. **Have we seen this before?** Last time, the root cause and the fix ended up in a ticket or a
   postmortem that nobody searches, so the investigation starts from zero.

Two more problems never page anyone at all:

- **Blind spots.** Most metrics are on no dashboard and in no alert. A problem in one of them goes
  unseen until it turns into an outage somewhere else.
- **Lost lessons.** What one engineer learned in an investigation doesn't reach the next alert or the
  next engineer.

How Ops Signals closes each gap:

| Today | With Ops Signals |
| --- | --- |
| A line on a chart, or a threshold that was crossed | A **finding** that names the change in words ("sustained baseline shift ~621 → ~425 ms, started around 23:59 UTC") and shows which analyzers produced it |
| Change history in a different tool | Findings and alerts name the **deploy or config change** just before the problem and, with drill-down, which pods it came from |
| Past fixes buried in tickets | Resolved cases and imported postmortems become **searchable memory**; an alert shows the most similar resolved case and how it was fixed |
| Unwatched metrics fail silently | **Metric Usage** compares your Grafana dashboards and alert rules with every metric, and flags metrics that had problems nothing would have shown |
| Each page triaged from scratch | **Alert enrichment** posts one Slack message that answers all three questions, and `GET /api/alert-context` lets an alert manager ask "seen before, real or noise?" before it pages anyone |

See [`docs/vision.md`](docs/vision.md) for the longer narrative behind this.

## What Ops Signals Does

**Gets data from where it already is**
- Prometheus, one server or several, including Mimir, Thanos and VictoriaMetrics tenants, pulled on
  demand or on a schedule
- OTLP pushed from an OTel SDK or Collector, CSV upload, and Alertmanager webhooks
- Deploy, config and feature-flag events from your CI through `POST /api/events`, and deploys
  found in Prometheus itself: a new version on a `*_build_info` metric, or a new Kubernetes
  ReplicaSet - see [`docs/deploy-discovery.md`](docs/deploy-discovery.md)

**Explains what changed**
- A config-driven router picks analyzers for each metric: baseline shift, change point, anomaly and
  outlier detection, trend, pattern discovery, forecasting and data health
- Each result becomes a **finding** with a title, a plain-language summary, a category and an
  importance score. Declarative rules across several metrics produce **behavior findings** (for
  example, memory pressure building up across services)
- Drill-down shows which pods a change came from, and which deploy started them - see
  [`docs/finding-drilldown.md`](docs/finding-drilldown.md)
- **Autonomous analysis** watches Prometheus by itself: pick the scope and policy, and run it once or
  on a schedule

**Gets the right people moving**
- **Alert enrichment**: one Slack message per Prometheus alert with what happened, what changed and
  whether it's been seen before - see [Alert Enrichment](#alert-enrichment-alertmanager-to-slack)
- High-importance findings go to Slack, so a problem found at 03:00 doesn't wait for someone to open
  the UI
- **Cases** track an investigation from open to resolved, with RCA, corrective action and outcome,
  and link two-way to **Jira Cloud** tickets
- **Metric Usage** finds blind spots, dashboards reading metrics that no longer exist, and the
  stored series that nothing uses (with an estimated cost, if you set a rate), with a ready query to watch each
  unused metric or scrape config to drop it - see [Metric Usage](#metric-usage)

**Remembers**
- Resolved cases become searchable operational memory. Past postmortems can be imported, so the
  memory isn't empty on day one
- `GET /api/alert-context` gives other systems prior outcomes, similar resolved cases and recurrence
- **Ask Ops Signals** is a chat over cases, findings, behaviors, analyzers and these docs

**Fits how you work**
- A React web UI, a Grafana plugin and an MCP server for AI clients
- New analyzers are added through config, in Python or as your own HTTP service, without touching
  core code
- Each team can change analyzer settings for its own services or metrics, in its own file, with a
  reason for each change - see [Per-service analyzer settings](docs/configuration.md#per-service-analyzer-settings)
- A benchmark suite measures router accuracy, detection accuracy and false alarms against
  known-answer datasets - see [`benchmark/README.md`](benchmark/README.md)

## What Makes It Different

- **It explains, not just detects.** Every finding says what kind of change it is, in words, and
  shows which analyzers and signals produced it, not just a score.
- **No LLM required.** Analysis, routing, findings and alert enrichment are deterministic. AI is an
  optional add-on (local Ollama, or a provider you already use) that can improve answers and triage
  Jira comments, but never overrides the deterministic result, and every answer says whether a model
  produced it.
- **It gets better with every resolved incident.** Each resolved case is checked against the next
  alert, so the fix you found last quarter is suggested when the pattern returns.
- **It adds to your stack and replaces nothing.** It's an extra Alertmanager receiver (your routes
  are untouched), reads Prometheus and Grafana read-only, and doesn't need Kubernetes.
- **Its methods are published and measured.** Every detection analyzer is a peer-reviewed method
  (citations in [`docs/analyzer-methodology.md`](docs/analyzer-methodology.md)), and it's
  benchmarked against known-answer data. Where something isn't validated yet, such as the router's
  suitability scores, the docs say so.
- **It's open and self-hosted.** MIT licensed, and your data stays on your network, with PostgreSQL
  as the system of record.

**How it compares.** Robusta/HolmesGPT add Kubernetes context and LLM investigation to alerts,
Keep deduplicates and routes alerts across tools, and Grafana Sift runs ML checks in Grafana Cloud.
Ops Signals needs no Kubernetes and no LLM: it explains the alerting metric itself and links it to
past resolved cases. It can run alongside any of them. See [`docs/comparison.md`](docs/comparison.md),
including where those tools are ahead.

## How It Works

```mermaid
flowchart LR
  S[Prometheus, OTLP or CSV] --> B[Normalize and store]
  B --> C[Router picks analyzers]
  C --> D[Signals]
  D --> E[Findings]
  D --> E2[Cross-metric behavior findings]
  E --> F[Cases]
  E2 --> F
  F --> M[Operational memory]
  M --> G[Ask Ops Signals and alert-context API]
  I[Alertmanager alert] --> C
  CI[Deploy events from CI] --> J
  M --> J[Enriched alert in Slack]
  I --> J
```

What it is not: a replacement for Prometheus, Grafana, Datadog or an incident-management platform.
It doesn't remediate anything by itself, and two similar cases don't prove the same root cause.

## Product Overview

Ops Signals ships as a standalone operational intelligence workspace and a Grafana plugin. This
section is what each surface looks like and produces; [Using Ops Signals](#using-ops-signals)
below is how to actually work with each piece.

**[View the complete screenshot gallery](docs/screenshots.md)**

### Standalone Operational Intelligence Workspace

![Ops Signals Overview](docs/screenshots/images/web/01-overview.png)

### Findings in Plain Words

Each finding leads with a badge (Worse, Better, Monitoring gap...) and a headline, then what changed
in the metric's own units, why it matters, what changed at the same moment, and what to check. The
analyzer's own wording stays under **Technical details**. The wording is a file you edit
([how](docs/finding-wording.md)), not AI output.

![Findings in plain words: an error rate that dropped reads "Better", with why it matters, the CPU drop at the same minute, and what to check](docs/screenshots/images/web/13-findings-plain-words.png)

### Analyze Prometheus Data Directly

![Direct Prometheus Analysis](docs/screenshots/images/web/03-new-analysis-prometheus.png)

### See Which Pods a Change Came From

A service-level finding says *what* changed. With [drill-down](docs/finding-drilldown.md) on, it
also says *where*: one bad pod, a few, every pod, or new pods from a rollout. Each of those calls
for a different next step.

![Finding drill-down: the error increase came from two new pods, pointing to a rollout](docs/screenshots/images/web/10-finding-drilldown.png)

### Investigate and Preserve Operational Knowledge

![Case Investigation](docs/screenshots/images/web/05-case-details.png)

### Run Analysis Inside Grafana

![Grafana analysis result: the same plain wording as the web UI, with the evidence beside it](docs/screenshots/images/grafana-plugin/02-metrics-analysis.png)

### Enriched Alerts in Slack

When a Prometheus alert fires, Ops Signals posts one message that says what happened, what changed,
and whether it has been seen before. This one is from the [demo](docs/demo.md), shown in its Slack
stand-in; see [Alert Enrichment](#alert-enrichment-alertmanager-to-slack) for real Slack.

![Enriched alert: a latency shift, the deploy before it, and a matching past incident with its fix](docs/screenshots/images/slack/enriched-alert-demo.png)

### Two ways to use Ops Signals

- **Standalone Web UI:** Supports CSV upload, direct Prometheus analysis, findings, cases, behavior intelligence, operational memory, and assistant retrieval.
- **Grafana Plugin:** Supports metric analysis within an existing Grafana and Prometheus environment using the active Grafana time range.

Alert enrichment and finding notifications have no page of their own: their output is the Slack
message.

## Quick Start

### Choose How to Run It

| You want to | Use | Needs |
| --- | --- | --- |
| See it working in a minute, with a scripted incident | `docker compose -f docker-compose.demo.yml up` ([demo](docs/demo.md)) | Docker |
| Try it on your laptop, with sample metrics or your own Prometheus | `./scripts/setup.sh`, then `./scripts/run_all.sh` (the steps below) | Docker, Python, Node |
| Try it on your laptop against your own Mimir, Thanos or several Prometheus servers | The same, with one extra step: [Point It at Your Own Prometheus](#point-it-at-your-own-prometheus-optional) | Docker, Python, Node |
| Run it for your team on one server | `docker compose -f docker-compose.packaged.yml up -d` ([Deploy for Your Team](#deploy-for-your-team)) | Docker |
| Run it in Kubernetes | `helm upgrade --install ops-signals ./helm/ops-signals` ([Deploy for Your Team](#deploy-for-your-team)) | Kubernetes, Helm |
| Use it inside Grafana | the Grafana plugin ([Grafana Plugin](#grafana-plugin)) | Grafana, plus one of the two above |

The demo doesn't read your data. The laptop install starts its own Prometheus with mock metrics, so
it works before you connect anything, and stops starting them once you point it at your own. The
team installs read only from the Prometheus you point them at.

### Try It on Your Laptop

The steps below set up a development install that you can point at your own data.

#### Prerequisites

- **Git**
- **Docker**, with Compose v2 (the `docker compose` command, not the older standalone `docker-compose`) - runs PostgreSQL/TimescaleDB and Qdrant for you
- **Python 3.12** (recommended: it's what the Docker images and CI use). 3.11 and 3.14 also work;
  3.13 is explicitly not supported by `scripts/setup.sh`. The setup script picks 3.12 when it's
  installed, and keeps the version an existing `.venv` already uses
- **Node.js 20+** and npm - for the React frontend
- *(Optional)* **Ollama** - only needed for local AI-assisted answers (see [Enable Local AI](#optional-enable-local-ai)); everything works without it
- macOS or Linux (the scripts are bash-based; on Windows, use WSL)

Check what you already have installed:

```bash
docker compose version
python3 --version
node --version
```

#### Run Setup

Skip the clone if you already have the repository from the demo.

```bash
git clone https://github.com/ramprasadgk9/ops-signals.git
cd ops-signals
./scripts/setup.sh
```

This creates a Python virtualenv and installs dependencies, runs `npm install` for the frontend, starts PostgreSQL and Qdrant in Docker, waits for both to report healthy, and initializes the database schema. First run pulls Docker images and packages, so expect it to take a few minutes. You'll see `Setup complete.` printed at the end.

#### Point It at Your Own Prometheus (Optional)

Skip this to start with the bundled Prometheus and mock metrics. You can do it any time later; see
[Switching later](#switching-later).

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

The [Prometheus](#prometheus) section has the details. With either set, `run_all.sh` doesn't start
the bundled Prometheus and mock metrics (`OPS_SIGNALS_LOCAL_PROMETHEUS=true` starts them anyway).

#### Start Ops Signals

```bash
./scripts/run_all.sh
```

This starts the backend (`:8001`), frontend (`:5174`), Postgres, Qdrant, Prometheus, and mock metrics together, all from one command.

#### Open the Application

Go to **http://localhost:5174** in your browser. You should see the Overview dashboard:

![Ops Signals Overview](docs/screenshots/images/web/01-overview.png)

#### Connect a Data Source

Findings will be empty on a fresh install - that's expected, nothing has been analyzed yet. Until
the first data arrives, the Overview shows a **Get data in** panel with every way in:

- **OTLP** - the endpoint to point an OTel Collector or SDK at, with a config snippet (see [OTLP](#otlp)).
- **Alertmanager** - the webhook URL and a `receivers:` snippet; **Send test alert** proves the
  whole path once alert enrichment is on (see [Alert Enrichment](#alert-enrichment-alertmanager-to-slack)).
- **Prometheus** - pulled on a schedule once `OPS_SIGNALS_PROMETHEUS_URL` is set in `.env`, or
  `OPS_SIGNALS_PROMETHEUS_CONNECTIONS_FILE` for several Mimir tenants (see [Prometheus](#prometheus)).
- **Deploy events** - the URL and a `curl` step for your CI pipeline, so alerts and findings can say
  which deploy came just before a change (see [Deploy and change events](#deploy-and-change-events)).
- **Load demo data** - analyzes a bundled checkout series in seconds, or upload your own CSV from
  **New Analysis**: **Validate Data** previews it, **Analyze and Save** stores the findings so you can
  create cases from them (see [CSV Input](#csv-input)).

The same sources, with whether each is receiving, live on the **Integrations** page
(`/integrations`) afterwards; received alerts are on the **Alerts** page (`/alerts`). The APIs behind
them are `GET /api/ingestion/status` and `GET /api/alerts`.

#### Optional: Enable Local AI

By default, Ask Ops Signals, the analyzer recommendation advisor and finding wording run on deterministic retrieval and templates - no AI, no API key, no network calls out. To add local LLM-assisted answers on top of that (never instead of it - the deterministic behavior stays the fallback):

```bash
docker compose --profile ai up -d
```

This starts a local Ollama container and pulls a small default model (`qwen2.5:3b`, ~2GB, one-time download). Then point the backend at it:

```bash
OPS_SIGNALS_AI_ENABLED=1 OPS_SIGNALS_AI_PROVIDER=ollama ./scripts/run_all.sh
```

See [Operational Intelligence Assistant](#operational-intelligence-assistant) for exactly what changes when this is on. Other places it's used: [Where AI is used](docs/ai-features.md).

Prefer a model you already run or pay for? Set `OPS_SIGNALS_AI_PROVIDER=openai_compatible` (vLLM, Azure OpenAI, Bedrock gateways, LiteLLM) or `anthropic` instead. See [Other AI Providers](docs/ask-ops-signals-assistant.md#other-ai-providers).

### Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| `docker is required` | Docker isn't installed, or the daemon isn't running | Install/start Docker Desktop (or Docker Engine on Linux) |
| `Unsupported Python version selected: 3.13` | System Python is 3.13, which `setup.sh` rejects | Install 3.12 (recommended), 3.11 or 3.14, then run `PYTHON_BIN=python3.12 ./scripts/setup.sh` |
| `npm is required to install frontend dependencies` | Node.js/npm isn't installed | Install Node.js 20+ |
| `postgres did not become ready in time` or `qdrant did not become ready in time` | Docker is still starting, or the port is already taken | `docker compose ps` and `docker compose logs postgres` (or `qdrant`); confirm ports `5432`/`6333` are free |
| A port (`8001`, `5174`, `9090`) is already in use | Another process is bound to it | Stop that process, or see `scripts/run_all.sh` for the ports it uses |
| `permission denied` running a script | The script isn't marked executable | `chmod +x scripts/*.sh` |
| It starts, but something doesn't work | A connection, token or setting is wrong | Open **Setup check** in the web UI: each red or yellow row has **How to fix**. **Copy report** gives a text summary (without secrets) to paste into an issue |

### Security model

Ops Signals is meant to run inside a trusted network, next to your Prometheus and Grafana:

- **No authentication by default.** Set `OPS_SIGNALS_API_TOKEN` and every endpoint except
  `/api/health` requires `Authorization: Bearer <token>`. The alert and event receivers accept their
  own token, or the API token if they don't have one.
- **Dangerous endpoints are off by default.** `OPS_SIGNALS_ENABLE_TESTING_API=true` turns on the
  endpoint that wipes all data. `OPS_SIGNALS_ALLOW_FILE_WRITES=true` lets the analyzer and behavior
  labs write files on the server. The dev scripts turn both on.
- **CORS** is limited to local dev origins. Add your Grafana URL with `OPS_SIGNALS_CORS_ORIGINS`.
- **Roles (Viewer, Editor, Admin)** come from Grafana in the plugin, and from your company's groups
  in the web UI: [`docs/web-ui-sign-in.md`](docs/web-ui-sign-in.md).

[`docs/security-model.md`](docs/security-model.md) covers how each client (web UI, Grafana plugin,
Alertmanager) sends the token, the Helm and Compose settings, and the known limitations.

### Scripts Reference

| Script | What it does | When to use it | Ports |
| --- | --- | --- | --- |
| `./scripts/setup.sh` | Installs Python and frontend deps, starts Postgres and Qdrant, and initializes the database. | First-time setup or after a clean checkout. | Postgres `5432`, Qdrant `6333` |
| `./scripts/run_all.sh` | Starts the standalone backend, frontend, Postgres, Qdrant, and - until `.env` points at your own Prometheus - a bundled Prometheus with mock metrics. | Daily local development outside Grafana. | Backend `8001`, frontend `5174`, Prometheus `9090` |
| `./scripts/multicluster.sh up`, then `app` | Starts a local Grafana Mimir with several clusters, an HA pair and two tenants, then the app with one connection per tenant. | Testing multi-cluster and multi-tenant behaviour; not for real deployments. See [`docs/testing-multicluster-locally.md`](docs/testing-multicluster-locally.md). | Mimir `9009`, plus the `run_all.sh` ports |
| `./scripts/try_keycloak_sign_in.sh up` | Starts a throwaway Keycloak (open-source identity provider) with test users and groups, sets the web UI's company sign-in up against it, then starts the app. | Seeing sign-in and roles work with a real provider before onboarding a team; for this computer only. See [`docs/try-company-sign-in.md`](docs/try-company-sign-in.md). | Keycloak `8180`, plus the `run_all.sh` ports |
| `./scripts/run_grafana_stack.sh` | Builds the Grafana plugin, starts Grafana, Prometheus, mock metrics, and the plugin backend. | Testing the Grafana plugin experience. | Grafana `3000`, Prometheus `9090`, backend `8002` |
| `./scripts/test_mcp.sh` | Starts the MCP server and verifies `initialize` and `tools/list`. | Checking MCP locally without Codex. | None; stdio only |
| `MCP_MODE=mcp-write ./scripts/test_mcp.sh` | Verifies the write-enabled MCP tool list. | Confirming write-capable tools are exposed. | None; stdio only |

`3000` is reserved for Grafana, `8002` for the Grafana/plugin backend - they don't conflict with the standalone app's `8001`/`5174`.

## Deploy for Your Team

There are two ways to run Ops Signals on one machine. They are separate setups with different
addresses:

| | Try it out | Run it for your team |
|---|---|---|
| Start | `./scripts/run_all.sh` | `docker compose -f docker-compose.packaged.yml up -d` |
| What runs | backend and web UI from source | backend, web UI and MCP server as containers |
| Metrics | mock metrics it starts for you | your own Prometheus |
| Web UI | http://localhost:5174 | **http://localhost:8080** |
| API | http://localhost:8001 | http://localhost:8000 |

Both start Postgres and Qdrant on ports 5432 and 6333, so stop one before starting the other.

### One Server: Docker Compose

You need Docker and a Prometheus this machine can reach.

```bash
git clone https://github.com/ramprasadgk9/ops-signals.git
cd ops-signals
echo 'OPS_SIGNALS_PROMETHEUS_URL=http://host.docker.internal:9090' >> .env
docker compose -f docker-compose.packaged.yml up -d
```

- **`OPS_SIGNALS_PROMETHEUS_URL`** is your Prometheus as the backend container sees it.
  `host.docker.internal` means the machine Docker runs on, so the line above is for a Prometheus on
  this machine at port 9090. For one elsewhere, use its address, for example
  `http://prometheus.example.internal:9090`. This stack doesn't include a Prometheus of its own, so
  without this line everything starts but there are no metrics to watch, and **Test Connection**
  on **New Analysis** fails.
- **The first start builds the three images** from this checkout, which takes a few minutes.
- **Check it:** open http://localhost:8080 → **Setup check** (bottom of the sidebar). It tests the
  database, each metrics connection and memory search, and says what to fix for anything that isn't
  green. From a terminal: `curl http://localhost:8000/api/setup/check`.
- **Before others can reach it,** add `OPS_SIGNALS_API_TOKEN=<a long random string>` to `.env` and
  run the `up` command again. Without it, anyone who can reach port 8000 can use the API (see
  [Security model](#security-model)).

Stop it with `docker compose -f docker-compose.packaged.yml down`. Your data is kept; add `-v` to
delete it too. To update, `git pull`, then run the `up` command with `--build` added, so the images
are rebuilt from the new code.

**Several Mimir tenants:** list them in a connections file and add the connections overlay.
Tokens go in `prometheus-connections.env`, never in the YAML:

```bash
cp examples/prometheus-connections.yaml prometheus-connections.yaml
printf 'MIMIR_TEAM_A_TOKEN=...\nMIMIR_TEAM_B_TOKEN=...\n' > prometheus-connections.env
docker compose -f docker-compose.packaged.yml -f docker-compose.connections.yml up -d
```

### Kubernetes: Helm

```bash
kubectl create secret generic ops-signals-db \
  --from-literal=database-url='postgresql+psycopg://USER:PASSWORD@HOST:5432/ops_signals'

helm upgrade --install ops-signals ./helm/ops-signals \
  --set database.urlSecret.name=ops-signals-db \
  --set backend.env.OPS_SIGNALS_PROMETHEUS_URL=http://prometheus-server.monitoring:9090
```

**Several Mimir tenants:** put the connections file under `prometheusConnections.config` in your
values and the tokens in a Secret named by `prometheusConnections.secretName`.

Both paths, with every value to set, are in [`docs/release-packaging.md`](docs/release-packaging.md).

### Add the Grafana Plugin

Once the backend runs (Docker Compose or Helm above), your team can use Ops Signals inside your own
Grafana (13.1 or later). You need a Prometheus datasource in that Grafana.

1. **Build the plugin zip** from this checkout (needs Node.js 20+):

   ```bash
   ./scripts/release/build_grafana_plugin_artifact.sh 0.5.0
   ```

   It writes `dist/release/0.5.0/breezypoppy3596-opssignals-app-<version>.zip`.

2. **Install it:** unzip it into Grafana's plugins folder (`/var/lib/grafana/plugins` by default).
   The zip holds one folder named after the plugin id, as Grafana expects.

   ```bash
   unzip dist/release/0.5.0/breezypoppy3596-opssignals-app-*.zip -d /var/lib/grafana/plugins
   ```

3. **Allow it, then restart Grafana.** The plugin isn't signed yet, so Grafana loads it only when
   it's named in `allow_loading_unsigned_plugins` under `[plugins]` in `grafana.ini`, or in
   `GF_PLUGINS_ALLOW_LOADING_UNSIGNED_PLUGINS=breezypoppy3596-opssignals-app` in Grafana's
   environment. Grafana reads the plugin only when it starts.

4. **Connect it to the backend** (a Grafana admin, once): **Administration → Plugins and data →
   Plugins → Ops Signals → Configuration**.
   - **Connect through:** Grafana.
   - **Backend URL:** the backend as the Grafana server reaches it, for example
     `http://ops-signals.example.internal:8000`. If Grafana runs in a container on the same machine
     as the Docker Compose install, use `http://host.docker.internal:8000`, not `localhost`.
   - **API token:** the `OPS_SIGNALS_API_TOKEN` from the backend's `.env`, if you set one.
   - Click **Enable and save**.

5. **Check it:** the **Setup check** below the settings should show the backend reached through
   Grafana. Then open **Apps → Ops Signals**.

To try this on one computer, run Grafana in Docker with the plugins folder mounted:

```bash
mkdir -p ~/grafana-plugins
unzip dist/release/0.5.0/breezypoppy3596-opssignals-app-*.zip -d ~/grafana-plugins
docker run -d --name grafana -p 3000:3000 \
  -e GF_PLUGINS_ALLOW_LOADING_UNSIGNED_PLUGINS=breezypoppy3596-opssignals-app \
  -v ~/grafana-plugins:/var/lib/grafana/plugins \
  --add-host host.docker.internal:host-gateway \
  grafana/grafana:13.1.0
```

Sign in at http://localhost:3000 as `admin` / `admin` and continue at step 4 with
`http://host.docker.internal:8000`.

Provisioning, roles and troubleshooting are in the plugin's [`README`](frontend/README.md) and
[`docs/grafana-plugin-access-and-roles.md`](docs/grafana-plugin-access-and-roles.md).

## Architecture

Data goes through one pipeline: validation, normalization into PostgreSQL, router-selected
analyzers, signals, then findings (and, separately, cross-metric behavior findings), which can be
promoted to cases. The [diagram above](#how-it-works) shows the flow;
[`docs/architecture.md`](docs/architecture.md) has the detailed version with per-stage code
references.

Two pipelines run the same analyzers and routing: **Interactive Analysis** (`SignalPipeline`, used
by Grafana, REST, CSV and the CLI) and **Autonomous Analysis** (`MetricAnalysisExecutor`, used by
the scheduler). They share the router and analyzer implementations but not orchestration code - see
[`docs/autonomous-pipeline-architecture.md`](docs/autonomous-pipeline-architecture.md).

**Storage.** PostgreSQL is the system of record: analysis runs, normalized points, signals,
findings, cases and investigation state. Qdrant is the semantic retrieval index built from it, kept
in sync on case create and update; nothing is written to Qdrant that isn't in PostgreSQL first.

More detail:

- [`docs/architecture.md`](docs/architecture.md) - the full pipeline, a diagram, and a "Why
  This Reduces MTTR" section connecting it to operational outcomes.
- [`docs/core-domain-model.md`](docs/core-domain-model.md) - the data model: canonical
  points, signals, and the fields on each.
- [`docs/design-decisions.md`](docs/design-decisions.md) - the "why," in short ADR-style
  writeups, including why PostgreSQL and Qdrant are split this way.
- [`docs/standalone-overview-api.md`](docs/standalone-overview-api.md) - the Overview
  summary and memory statistics endpoint contracts.
- [`docs/standalone-prometheus-analysis.md`](docs/standalone-prometheus-analysis.md) - the
  direct Prometheus query flow and how it differs from Grafana datasource-based analysis.

## Using Ops Signals

Where to find each capability once the app is running.

### Where to Find Each Feature

| Feature | Where | Read more |
| --- | --- | --- |
| **UI tour**: every tab of the web UI (14) and both Grafana plugin modes, one line each | - | [`docs/ui-tour.md`](docs/ui-tour.md) |
| **Interactive analysis**: one metric at a time, from a Prometheus query or a CSV, findings right away | **New Analysis**; Grafana **Interactive Analysis** | [`docs/standalone-prometheus-analysis.md`](docs/standalone-prometheus-analysis.md) |
| **Analyzers**: 7 built in (Baseline Shift, Ruptures Change Point, Z-Score Anomaly, PyOD Outlier, Trend, STUMPY Motif, Prophet Forecast) plus Data Health, added through config; how the router picks and how far to trust it | **Analyzer Workbench** → **Recommendations** | [`docs/analyzer-plugin-framework.md`](docs/analyzer-plugin-framework.md), [`docs/analyzer-recommendation.md`](docs/analyzer-recommendation.md) |
| **Behavior intelligence**: rules across several metrics, with a worked memory-pressure example | **Behavior Intelligence** (Detected, Patterns) | [`docs/behavior-intelligence.md`](docs/behavior-intelligence.md) |
| **Analyzer workbench**: run any analyzer on sample data (**Labs**), register a new one in Python or as your own HTTP service (**Add Analyzer**), preview router scores (**Recommendations**) | **Analyzer Workbench** | [`docs/analyzer-plugin-framework.md`](docs/analyzer-plugin-framework.md#analyzer-workbench-ui), [`docs/http-analyzer-contract.md`](docs/http-analyzer-contract.md) |
| **Findings**: drill-down by pod, the deploy before a change, filter by service | **Findings** | [`docs/operational-findings.md`](docs/operational-findings.md), [`docs/finding-drilldown.md`](docs/finding-drilldown.md) |
| **Metric usage**: which metrics a Grafana dashboard or alert watches, and which had problems that nothing shows (blind spots), checked every 6 hours | **Metric Usage** | [Metric Usage](#metric-usage) |
| **Cases**: every case with its lifecycle (`open -> investigating -> rca_in_progress -> resolved -> closed`), RCA and outcome, filter by service | **Cases** | [`docs/operational-cases.md`](docs/operational-cases.md) |
| **Historical analysis**: semantic search over past cases and findings, the alert-context preview an external alert manager would see, and importing past postmortems so it works on day one | **Recurring problems** | [`docs/operational-memory.md`](docs/operational-memory.md), [`docs/importing-incident-history.md`](docs/importing-incident-history.md) |
| **Autonomous analysis**: what to watch, run once or on a schedule | **Autonomous Analysis Configure**; Grafana **Autonomous Analysis** | [Autonomous Analysis](#autonomous-analysis) |

### Operational Intelligence Assistant

Ops Signals includes a single chat interface ("Ask Ops Signals") that routes questions across
historical cases, current findings, behaviors, analyzers, and application documentation. The
assistant should be treated as a retrieval and explanation layer, not as an oracle.

By default it runs on deterministic retrieval and template answers - no AI required. Point it at
a local model (self-hosted via Ollama, `docker compose --profile ai up`; no API key, no cloud
calls) and it additionally gets:

- LLM-synthesized answers grounded in the same retrieved evidence, instead of a fixed template
- LLM-assisted question routing on top of (never instead of) the deterministic keyword router, so
  a weaker model can only add coverage, never lose it
- Semantic search over cases, findings, and behaviors, not just keyword matching

Every response labels which mode produced it (`ai_synthesis_used`), so it's never ambiguous
whether an answer came from a model or from a template.

#### What users can expect

- Ask natural-language questions about findings, cases, signals, behaviors, analyzers, and architecture
- Retrieve relevant cases, documentation, and evidence from vector search
- Get plain-language summaries grounded in stored operational data and repo docs
- Ask follow-up questions like "what changed?", "have we seen this before?", or "what is behavior intelligence?"
- See source links, case IDs, or documentation references used in the answer

#### What users should not expect

- Guaranteed root-cause truth from the chat output alone
- Autoremediation or direct system changes
- Free-form guesses without evidence
- Answers that go beyond the stored data, docs, and retrieval context
- Replacement for the underlying analyzers, rules, or source observability tools

## Data, Automation & Configuration

How data gets in, how autonomous scanning decides what to watch, and how to tune analyzer and
behavior config.

### Data Sources

#### Prometheus

Connect Ops Signals to an existing Prometheus datasource for direct or autonomous analysis. See
[`docs/standalone-prometheus-analysis.md`](docs/standalone-prometheus-analysis.md).

One Prometheus is set with `OPS_SIGNALS_PROMETHEUS_URL`. For Grafana Mimir with several tenants (or
several Prometheus servers), list them as named connections in a file set by
`OPS_SIGNALS_PROMETHEUS_CONNECTIONS_FILE` - start from
[`examples/prometheus-connections.yaml`](examples/prometheus-connections.yaml). The Configure panel and
Validate Data then get a connection picker, each autonomous policy keeps its connection, and alerts
are analysed on the tenant their labels match. Series from several clusters behind one endpoint are
analysed per cluster, and HA replica copies count once. See
[Mimir, Thanos and other multi-source backends](docs/standalone-prometheus-analysis.md#mimir-thanos-and-other-multi-source-backends).

##### Switching later

Moving from the bundled Prometheus to your own, or from one Prometheus to several Mimir tenants, is a
change to `.env` and a restart; nothing is reinstalled.

- Policies and findings made before keep working: they belong to the connection `default`, which
  always means the default connection, the first one in the file unless it sets `default:`.
- The connections file is checked at startup: a duplicate id, an unknown `default` or an unset
  `${TOKEN}` stops the backend with an error naming it. Later edits to the file are picked up without
  a restart.
- After the restart, Configure and New Analysis get a connection picker, Integrations lists each
  connection and whether it answers, and alerts go to the connection whose `match_labels` they carry.

#### CSV Input

```csv
timestamp,service,metric_name,value,env,host,namespace,pod,unit,metric_type
2026-07-12T14:00:00Z,payments-api,cpu_usage,78.2,prod,ip-10-0-1-5,,payments-7d8c9,percent,gauge
2026-07-12T14:01:00Z,payments-api,cpu_usage,84.6,prod,ip-10-0-1-5,,payments-7d8c9,percent,gauge
```

#### OTLP

Prometheus and CSV are both pull/upload - Ops Signals asks for the data. OTLP is the reverse: an
OTel SDK or Collector pushes metrics to Ops Signals: point its `otlphttp` exporter at
`http://localhost:8001/api/otlp`. See [OTLP Metrics Ingestion](#otlp-metrics-ingestion) for setup
and guardrails.

#### Deploy and change events

Your CI pipeline sends deploys, config changes and feature-flag flips to `POST /api/events` (the
**Send deploy events** tile on the Integrations page has a ready-made `curl` step). Alerts and
findings then name the change that came just before a problem. How events are joined to metrics
(service, environment, time) is in
[`docs/finding-drilldown.md`](docs/finding-drilldown.md#how-are-deploy-events-joined-to-metrics-and-findings).

Before CI is set up, Ops Signals finds deploys in Prometheus on its own: a service reporting a new
version on its `*_build_info` metric, or a new ReplicaSet from kube-state-metrics. These show in the
same places as CI's deploys, tagged "Found automatically", and a deploy CI sends later replaces the found one. See
[`docs/deploy-discovery.md`](docs/deploy-discovery.md).

#### Findings as Prometheus metrics

`GET /api/metrics` includes the active findings as `ops_signals_active_findings{service, metric,
cluster, evidence, severity}`. Scrape it and an ordinary alert rule can page on "strong evidence on
checkout" through your existing Alertmanager routes, and any dashboard can chart findings. See
[`docs/finding-metrics.md`](docs/finding-metrics.md).

### Autonomous Analysis

Autonomous analysis turns three inputs into concrete Prometheus metric jobs: monitoring intent
(categories such as performance, capacity, availability, or custom metrics), scope (environment,
service, namespace and the labels that identify them) and an execution policy (interval, analysis
window, metric budget). Metrics are discovered from Prometheus and classified by the rules in
`config/prometheus_metric_knowledge.yaml` and `config/autonomous_metric_taxonomy.yaml`, with
sampling that keeps one noisy service from crowding out the rest.

A policy runs once or on a recurring schedule, and a failing schedule is surfaced rather than going
quiet. Each run takes at most `max_metrics_per_run` metrics (default 500); the rest are excluded for
that run, not carried over, and shown as budget-limited. Jobs run one after another. Results,
coverage and history are on the **Overview** tab and in the Grafana plugin.

See [`docs/autonomous-analysis-preview.md`](docs/autonomous-analysis-preview.md) for planning,
discovery, the budget and scheduling, and
[`docs/autonomous-pipeline-architecture.md`](docs/autonomous-pipeline-architecture.md) for how it
runs.

### Metric Usage

With thousands of metrics, most are on no dashboard and in no alert. Metric Usage shows which ones
are, and which ones had problems that nobody would have seen. Every 6 hours it reads Grafana
dashboards and alert rules plus Prometheus alerting and recording rules, takes the metric names from
their queries, compares them with every metric in each Prometheus connection and with recent
findings, and sorts each metric into one group:

- **Blind spot**: on no dashboard or alert, and had significant or critical findings recently. Each
  one links to its finding and can become a case.
- **Missing**: a dashboard or alert reads a metric that no longer exists, so it shows nothing.
- **Not watched**: everything else, biggest first.
- **Watched**: on a dashboard or in an alert, directly or through recording rules. Last on the page
  and closed: there's nothing to do there, but it shows which dashboards and alerts read each
  metric, so you can check your dashboards were found before you drop anything.

The page opens with the unused share of stored series, the problems nobody would have seen, and how
coverage has moved since the oldest kept check. The **Findings** cards say which dashboard or alert
shows each metric, and the **Overview** names the blind spots when there are any.

It needs read-only Grafana access: in Grafana, **Administration -> Service accounts**, add one with
the **Viewer** role and create a token. Then set the URL and token in `.env`; the folder, metric and
interval settings are optional:

```bash
OPS_SIGNALS_GRAFANA_URL=https://grafana.example.com
OPS_SIGNALS_GRAFANA_TOKEN=glsa_...
OPS_SIGNALS_METRIC_USAGE_EXCLUDE_FOLDERS=Scratch,Test*
OPS_SIGNALS_METRIC_USAGE_IGNORE_METRICS=go_*
OPS_SIGNALS_METRIC_USAGE_INTERVAL_HOURS=6
```

With `docker-compose.packaged.yml`, put the same lines in the `.env` next to it and run `up -d`
again. The URL is as the backend container sees it, so a Grafana on the same machine is
`http://host.docker.internal:3000`, not `localhost`. With Helm, set them under `backend.env`, and
put the token in the Secret named by `prometheusConnections.secretName`, whose keys all become
backend environment variables.

You don't list dashboards or alert rules one by one: with the URL and token it reads every
dashboard and Grafana alert rule the token can see, and Prometheus alerting and recording rules come
from your Prometheus connections without extra settings.

The page counts unused storage in series. To also see an estimated monthly cost under that count,
set what 1,000 active series cost you per month, `OPS_SIGNALS_METRIC_USAGE_COST_PER_1K_SERIES` (and
`OPS_SIGNALS_METRIC_USAGE_CURRENCY`, default `USD`). There is no built-in price, and the estimate is
only as good as the rate: real bills also depend on samples, retention and queries.

With several Prometheus connections, a panel counts only on the connections its Grafana datasource
reads: those with the same URL, or those naming it under `grafana_datasources` in the connections
file. Name it there when tenants share one URL, or when Grafana reaches Prometheus by another host
name; panels on a datasource that matches no connection are left out, with a warning.

#### Acting on unused metrics

Each **Not watched** metric has two buttons, because an unused metric means one of two things:

- **Add to Grafana**: it matters and nobody watches it. The dialog gives a query that fits the
  metric's type (a rate for counters, the 95th percentile for histogram buckets, the value for
  gauges) and the steps to put it on a dashboard or an alert rule. Nothing is created in Grafana.
- **Drop**: nobody needs it. The dialog gives Prometheus scrape config that stops storing it, one
  `metric_relabel_configs` rule with `action: drop` under each scrape job that collects it. Tick
  several metrics to get one config for all of them. You copy it into `prometheus.yml` and reload;
  Ops Signals changes nothing itself.

Only whole metrics are dropped, never single labels: dropping a label merges series and corrupts what
is left. Drop isn't offered for metrics with recent problems, metrics a recording rule makes (remove
the rule instead), `up` and `scrape_*` (Prometheus makes them), metrics whose scrape job isn't
known, and metrics first seen less than 7 days ago, so a new metric's team has time to build its
dashboard. Metrics Ops Signals analyzes, or that a query reads by a name pattern, can be dropped with
a warning.

"Not used" means not used by what the check reads. Queries people run by hand, scripts and
autoscalers that call the Prometheus API, and other Grafana instances aren't seen, so the dialog
lists what was and wasn't checked next to the Copy button. The config works for metrics Prometheus
scrapes; metrics sent by remote write or OTLP have to be dropped where they're sent from. Series
with no `job` label are called out and not counted in what the rule drops.

Jobs are named by the series' `job` label, which is usually the scrape config's `job_name`. With
relabeling or prometheus-operator they differ: put the rule in the job that sets that label (or the
ServiceMonitor's `metricRelabelings`). Metrics from several Prometheus connections get one config
block each, since each goes into its own server's config.

**Recording rules nobody reads** lists rules whose output no dashboard, alert or other rule reads,
following chains: a rule that only feeds another unread rule is unread too. A rule whose output had
recent problems is a blind spot instead, not listed here. **How to remove** says which group to
delete it from, with a warning when a query reads metrics by a name pattern that matches it.

The scrape jobs come from `count by (__name__, job)` and the types from Prometheus
`/api/v1/metadata`; where a backend doesn't serve metadata, types are guessed from names.

**Run now** on the page starts a check without waiting for the schedule. All settings are listed in
[`.env.example`](.env.example).

### YAML Configuration

Configuration is layered YAML, merged in this order: shared settings, analyzer defaults, then
provider-specific input mapping. [`docs/configuration.md`](docs/configuration.md) has the merge
order and an example.

| File | What it sets |
| --- | --- |
| `config/analyzers.yaml` | Analysis mode, window, and per-analyzer defaults such as window size and sensitivity |
| `config/providers/*.yaml` | How each input source maps onto the canonical point format |
| `config/analyzer_overrides.d/*.yml` | Per-service analyzer settings, one file per team: stricter or looser thresholds for chosen services or metrics - start from `payments-team.yml.example` |
| `config/behavior_definitions.d/*.yml` | Cross-metric behavior rules, one file per behavior - see [`docs/behavior-intelligence.md`](docs/behavior-intelligence.md) |
| `config.yaml` | Operational memory: Qdrant and embeddings |

The router's suitability weights aren't a threshold you tune; they're heuristic and documented in
[`docs/analyzer-recommendation.md`](docs/analyzer-recommendation.md).

## Integrations

Ways to plug Ops Signals into tools you already use.

### Grafana Plugin

```bash
./scripts/run_grafana_stack.sh
```

That script builds the plugin bundle, starts Grafana on `3000`, Prometheus on `9090`, mock metrics, and the backend on `8002`. `8002` is reserved for the Grafana/plugin backend. It's for trying and developing the plugin; to install it in your team's Grafana, see [Add the Grafana Plugin](#add-the-grafana-plugin).

See [`docs/grafana-plugin-local-setup.md`](docs/grafana-plugin-local-setup.md) for installing the
plugin specifically, and
[`docs/grafana-plugin-feature-walkthrough.md`](docs/grafana-plugin-feature-walkthrough.md) for a
tour of Interactive Analysis and Autonomous Analysis inside Grafana.

### MCP Server

An MCP server exposes Ops Signals to MCP clients over stdio: `python -m intelligence.cli mcp`
(read-only) or `mcp-write` (adds case updates, memory indexing and the chat tools). `./scripts/test_mcp.sh` checks
it locally. Client configuration and the tool list are in [`docs/mcp-server.md`](docs/mcp-server.md).

### OTLP Metrics Ingestion

Ops Signals can receive metrics pushed directly from an OpenTelemetry SDK or an OTel Collector,
in addition to CSV upload and pull-based Prometheus queries:

```
POST /api/otlp/v1/metrics
```

Both OTLP/HTTP encodings are supported (`Content-Type: application/x-protobuf` or
`application/json`). Gauge and Sum (counter) metrics are supported; Histogram,
ExponentialHistogram, and Summary points are accepted but rejected with a `partial_success`
response, not silently dropped.

To try it without setting up a real OTel Collector, send a synthetic series and watch a finding
appear in the UI:

```bash
./scripts/run_all.sh
./scripts/send_test_otlp_metrics.py --service demo-service
```

To try a real OpenTelemetry Collector instead, sending this machine's host and Docker container
metrics: `./scripts/otel_collector.sh start` (and `status`, `logs`, `stop`).

To see what an OTLP-only install looks like from scratch, without touching your running stack,
start an empty, throwaway copy with no Prometheus or Alertmanager (UI on :5184):
`./scripts/otlp_sandbox.sh up`, then `collector` for live data or `sample` for a day of data, and
`down` to remove it all.

Point `-t otlphttp` metrics in an OTel Collector config at Ops Signals like this:

```yaml
exporters:
  otlphttp:
    endpoint: http://localhost:8001/api/otlp
```

The path is `/api/otlp`, not OTLP's spec-default root path - see
[`docs/design/otlp-metrics-ingestion-plan.md`](docs/design/otlp-metrics-ingestion-plan.md#3-endpoint) for why.
The design doc covers the volume and cardinality guardrails and the `GET /api/metrics`
self-observability endpoint, which also serves the active findings
([`docs/finding-metrics.md`](docs/finding-metrics.md)).

#### Using Ops Signals with OTLP only

If your metrics already flow through OpenTelemetry, from any vendor's SDK or Collector, you can
send them straight to Ops Signals without running Prometheus. This is what you get, and what you
don't, before you onboard.

![OTLP only: from an empty install to findings from live Collector data](docs/screenshots/images/web/otlp-only.gif)

[Watch the one-minute walkthrough](docs/screenshots/videos/otlp-only.webm) (re-record with `./scripts/record_otlp_walkthrough.sh`)

| | With OTLP only |
|---|---|
| ✅ **Works** | Findings from live data, cases and ticketing, operational memory and similar past cases, Slack notifications, the assistant and MCP, behavior rules |
| ⚠️ **Partly** | Latency percentiles: OTLP histograms aren't read yet, so percentiles come only from Prometheus or CSV data |
| ➕ **Needs another source** | Autonomous analysis, drill-down by pod and Metric Usage need a Prometheus-compatible source; alert enrichment also needs Alertmanager; deploy correlation needs [deploy events](#deploy-and-change-events) |

The app shows the same list under **Integrations → What works with my data?**, and features that
need another source say so where you meet them.

**What to expect in the first hour.** Measured with a real OTel Collector sending one laptop's host
and Docker container metrics (about 300 series) to an empty install:

- The first findings appear about 10 minutes after data starts arriving.
- The first 30-40 minutes are the noisiest: each series has only minutes of history, so normal
  changes, such as containers starting up, stand out. New problems needing attention went from 35
  in the first 10 minutes to 1-6 per 10 minutes after 40 minutes.
- Expect a few hundred findings in that first hour, most of them context: about 300 problems, 57
  of them needing attention. The Overview leads with the ones needing attention ("57 Need
  Attention, +242 in context"); context findings are one click away on the Findings page. Bursty
  series such as disk and network bytes produce most of the "unusual activity" ones.
- A problem that every analysis sees again is one problem: the Overview counts it once (697
  findings in that hour were 299 problems), its card says "Started 09:00 · still happening" or
  "09:00-09:45 · over", and Slack hears about it once, and again only if it gets worse. In one
  10-minute round that was 19 Slack messages instead of 110.

**How OTLP data is analyzed.** Each series' new points wait until 10 minutes have gathered (a
large backfill is analyzed at once), then are analyzed together with up to 6 hours of that series'
history. Counters (a Sum that only goes up, such as CPU time or bytes sent) are turned into
per-second rates first, as Prometheus' `rate()` does; a Sum that can go down, such as memory in
use, is analyzed as a level. Tune with `OPS_SIGNALS_OTLP_ANALYSIS_INTERVAL_MINUTES` (10),
`OPS_SIGNALS_OTLP_HISTORY_HOURS` (6) and `OPS_SIGNALS_OTLP_IMMEDIATE_BATCH_POINTS` (60).

To see all of this on your own machine, `./scripts/otlp_sandbox.sh up` starts an empty copy next
to your normal one, and `./scripts/otlp_sandbox.sh collector` sends it live data.

### Slack Notifications

Pushes high-importance findings to a Slack channel, so a problem that autonomous analysis finds at
03:00 doesn't wait for someone to open the UI.

1. Create a Slack incoming webhook (Slack app settings, api.slack.com/apps → Incoming Webhooks).
2. In `.env` (see `.env.example`):
   ```bash
   OPS_SIGNALS_SLACK_ENABLED=true
   OPS_SIGNALS_SLACK_WEBHOOK_URL=https://hooks.slack.com/services/...
   OPS_SIGNALS_SLACK_MIN_IMPORTANCE=0.7
   ```
3. Restart the backend, then check the wiring with `./scripts/send_test_slack_finding.py`.

Only findings with importance at or above `OPS_SIGNALS_SLACK_MIN_IMPORTANCE` are posted. A broken
webhook is logged and never fails the analysis.

### Alert Enrichment (Alertmanager to Slack)

![Enriched alerts in Slack](docs/screenshots/images/slack/alert-enrichment-messages.png)

A plain alert says only that a threshold was crossed. The on-call engineer then spends the first
minutes of every page working out *what happened, what changed, and whether it's been seen before*.
Alert enrichment answers those three questions in the alert itself.

When a Prometheus rule fires, Alertmanager sends the alert to Ops Signals as an **extra** receiver
(your existing routes are untouched). Ops Signals then:

1. pulls the alerting series from Prometheus and runs the analyzers → **📈 What happened**
   ("sustained baseline shift ~621 → ~425 ms, started around 23:59 UTC"), or reuses a finding that
   autonomous analysis already produced and says how much earlier it was detected;
2. matches deploys/config changes your CI sent to `POST /api/events` → **🚀 What changed**
   ("started 7 min after deploy `v2.0.0`");
3. runs the existing alert-context lookup → **🧠 Seen before** (prior occurrences, confirmed vs
   noise, most similar resolved case and its fix);
4. posts one Slack message, clearly marked as coming from an **Alertmanager alert**, with a
   **✅ [RESOLVED]** follow-up when the alert clears.

It adds a trigger and an output around the existing pipeline, not new analysis logic. The finding
lands in the normal findings tables and the UI, and every alert is recorded in
`ops_alert_enrichments`. Status, `absent()` and log alerts skip the analysis, say why, and still get
the change and history sections. Nothing is ever dropped or hidden.

**Try it locally.** Set `OPS_SIGNALS_ALERT_ENRICHMENT_ENABLED=true` and a Slack webhook in `.env`,
then:

```bash
./scripts/run_all.sh              # also starts a local Alertmanager + demo alert rules
./scripts/send_test_alert.py      # fire a test alert on demand (--scenario status, --deploy-minutes-ago 5, ...)
```

For a live demo with pods and deploys, run [`./scripts/demo_live.py`](docs/live-demo.md) in a second terminal.

**Connect your own Alertmanager** by adding a webhook receiver pointing at
`/api/integrations/alertmanager` with `continue: true`, pointing `OPS_SIGNALS_PROMETHEUS_URL` at the
same Prometheus, and (optionally) sending deploy events from CI. Full guide - why it matters,
architecture, Alertmanager config, per-rule annotations, Slack controls and troubleshooting:
[`docs/alert-enrichment.md`](docs/alert-enrichment.md).

### Pluggable Case Ticketing (Jira Cloud)

A case can be linked to a Jira Cloud ticket, and the two stay in sync both ways: the case shows the
ticket's status and comments, and a useful comment can be promoted into the case's investigation
notes with one click. When the case is resolved, the root cause and fix are posted back to the
ticket, which is moved to Done if the workflow allows it. Inbound webhooks are verified with a shared
secret (`OPS_SIGNALS_JIRA_WEBHOOK_SECRET`), and a Jira outage never blocks the case.

With AI turned on, new Jira comments are also checked automatically: diagnostic clues go into the
case notes, marked as AI-promoted, and routine chatter is left out. Without AI, comments wait for you
to promote them.

Jira is the first provider behind a pluggable ticketing interface. See
[`docs/operational-cases.md`](docs/operational-cases.md) for setup and how sync works.

## Examples

### Example Operational Finding

A finding from autonomous analysis of `http_errors_total` on the `cart` service, with drill-down on
and a deploy recorded (shortened):

```json
{
  "service": "cart",
  "metric_name": "http_errors_total",
  "title": "http_errors_total experienced a persistent baseline shift during the selected time window.",
  "summary": "A structural change was detected around sample 120, where the average value increased from 0.4197 to 3.0148, a change of 618.4%. ...",
  "category": "behavior_change",
  "health_status": "critical",
  "importance_score": 0.85,
  "investigation_priority": 1,
  "comparison_json": {
    "breakdown": {"status": "ok", "label": "pod", "spread": "partial", "parts_total": 6, "parts_changed": 2, "new_parts": 2}
  },
  "changes": {
    "status": "matched",
    "matches": [{"event_type": "deploy", "version": "v1.4.2", "minutes_before_anchor": 0.1}],
    "pods": {"status": "linked", "parts": ["cart-8c2-q1", "cart-8c2-w7"]}
  }
}
```

`category` is one of `behavior_change`, `unusual_activity`, `data_quality` or
`operational_insight`; `health_status` is `critical`, `significant` or `normal`, set by the
importance score (0.8 or more, 0.55 or more, below that). The UI shows them as **High**, **Medium**
and **Low** importance: `normal` means a change was found but it is small, not that all is well. See
[`docs/operational-findings.md`](docs/operational-findings.md). How a finding becomes a
case is in [`docs/operational-cases.md`](docs/operational-cases.md).

## Current Limitations

- Scripts, CI and receivers share one optional API token, with no names or roles; people get roles
  only through the Grafana plugin or the web UI's sign-in. Run it on a trusted network - see
  [`docs/security-model.md`](docs/security-model.md)
- With OTLP or CSV alone, autonomous analysis, pod drill-down, alert enrichment and Metric Usage are
  off: they need a Prometheus-compatible source (and Grafana, for Metric Usage dashboards). The UI
  says so where you meet them - see [what each source turns on](docs/integrations.md#what-each-source-turns-on)
- No autonomous remediation
- No claim that similarity equals root-cause equivalence
- Historical retrieval depends on the quality of stored summaries and metadata
- Some memory workflows are still evolving and should be treated as operational assistance, not automation
- Analyzer recommendation scoring is deterministic and currently profile-based; it does not yet run deeper analyzer-specific probes
- Alert enrichment analyzes Prometheus-compatible alerts only (Grafana-managed and Loki alerts get
  the change and history sections), uses one Prometheus connection, and posts resolve follow-ups as
  new Slack messages rather than threads - see
  [`docs/alert-enrichment.md`](docs/alert-enrichment.md#current-limitations)
- OTLP metrics ingestion is single-instance only (no distributed queue), OTLP/HTTP only (no gRPC),
  and metrics-only (no logs/traces) - see
  [`docs/design/otlp-metrics-ingestion-plan.md`](docs/design/otlp-metrics-ingestion-plan.md#10-explicit-non-goals-phase-1)

## Roadmap

- Expand analyzer coverage
- Improve operational memory retrieval filters
- Add richer case comparison and retrieval views
- Extend evaluation datasets for regression checks
- Document release and contribution workflows more fully
- Kubernetes and cloud-provider ingestion; ITSM/automation and generic external-system consumers -
  see the explicitly-labeled roadmap section in
  [`docs/architecture.md`](docs/architecture.md#roadmap-not-yet-implemented)

## Who's Using Ops Signals?

If you're running Ops Signals somewhere - production, staging, or just evaluating it - we'd like to know. Add yourself to [ADOPTERS.md](ADOPTERS.md) via a short PR, or open an issue if a PR is more than you want to do.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

Ops Signals was created, designed and implemented by Ramprasad Goturkarnam ([@ramprasadgk9](https://github.com/ramprasadgk9)), its lead maintainer and primary contributor.

**Maintainers:**

- Ramprasad Goturkarnam ([@ramprasadgk9](https://github.com/ramprasadgk9)), creator and lead maintainer
- Pruthvi Davineni ([@pruthviraja](https://github.com/pruthviraja)), maintainer

## License

See [LICENSE](LICENSE).
