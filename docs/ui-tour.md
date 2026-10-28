# UI Tour

A short guide to every tab in the standalone web UI and every mode in the Grafana plugin — what
each one is for, and where to read more.

The two frontends are separate applications sharing the same backend (see
[`docs/architecture.md`](architecture.md)); a feature that exists in one does not
automatically exist in the other.

## Standalone Web UI

| Tab | Route | What it's for |
| --- | --- | --- |
| **Overview** | `/` | The landing dashboard — recent findings, case activity, and a summary of what the autonomous scheduler has found. Start here. |
| **Alerts** | `/alerts` | Alerts received from Alertmanager and other sources: a 24-hour timeline with deploys marked, and per alert where the change came from (pods), what changed just before (deploys) and the finding or case it was linked to. |
| **Integrations** | `/integrations` | Setup for every way data gets in: OTLP push, Prometheus (URL, reachable, what uses it), the Alertmanager webhook, and deploy events from CI, each with its URL, a snippet and whether data is arriving. |
| **Autonomous Analysis Configure** | `/autonomous-monitoring` | Configure which services/metrics to watch and which monitoring categories to enable, preview the resulting plan, run it once, or save it as a recurring schedule. With sign-in on, a Viewer sees it as **Autonomous Analysis**: the schedule and what runs found, without the set-up form. See [`docs/autonomous-analysis-preview.md`](autonomous-analysis-preview.md). |
| **Findings** | `/findings` | Every single-metric Finding the system has produced, searchable and filterable. Each finding's detail view names which ingestion path produced it (CSV, Prometheus, Datadog, or OTLP) and charts the raw points behind it, for tracing a finding back to what was actually ingested. Cards can carry a pod chip ("2 new pods", "1 of 6 pods") and a deploy chip ("After deploy v1.4.2"); see [the chips on a finding card](finding-drilldown.md#the-chips-on-a-finding-card). With an AI provider on, the detail view's What to check and Happened with lines (and Why it matters, for a metric the wording file doesn't describe) are written for that metric, marked **AI**, with **Show template wording** to switch back; with it off, admins see once how to turn it on. Same in the plugin's evidence panel. See [AI wording](finding-wording.md#ai-wording). See [`docs/operational-findings.md`](operational-findings.md). |
| **Metric Usage** | `/metric-usage` | Which metrics Grafana dashboards and alerts watch, checked every 6 hours: blind spots (problems on metrics nothing shows) first, then metrics a dashboard reads that no longer exist, unwatched metrics, and the unused share of stored series. Watched metrics come last, closed: open them to check your dashboards were found. Each unwatched metric has **Add to Grafana** (a query and the steps) and **Drop** (Prometheus scrape config to stop storing it; tick several for one config), and recording rules nobody reads say how to remove them. See [Metric Usage](../README.md#metric-usage). |
| **Cases** | `/cases` | Every Case (an investigation promoted from a Finding or Behavior Finding). Tabs split them into Open, In progress, On hold and Resolved; the side panel shows the selected case's root cause and timeline. (`/investigations` redirects to the In progress tab.) With AI on, a case's Root Cause and Resolution tabs have **Draft from case**. Publish Knowledge shows the case timeline and a write-up saved with the case. See [`docs/operational-cases.md`](operational-cases.md). |
| **Behavior Intelligence** | `/behavior-intelligence` | Problems that only show up when several metrics are considered together. **Detected** lists the matches, each with the metrics it combined and why it matched (also shown on Findings as combined patterns). **Patterns** lists the rules every run checks and the pairs mined from your data; admins open the builder there (New pattern, Edit copy, Use this pattern, Turn into pattern) to write a rule with conditions in plain words (is rising, is falling, has an unusual spike), see how it would have done on a service's recent runs and open any run for the details, and save it to a pack. `/behavior-intelligence/lab` opens the builder. See [`docs/behavior-intelligence.md`](behavior-intelligence.md). |
| **Recurring problems** | `/recurring-problems` | Past cases grouped into problems that keep coming back, with the causes found and what to do next; whether monitoring caught imported past incidents; and, folded away, the indexing details and the alert-context preview an external alert manager would see. Cases that belong to a recurring problem show a "Seen before" line linking here. A finding or case back within 30 days of a fix on the same service says **Fix didn't hold** instead, naming the old fix; see [When a fix didn't stick](operational-memory.md#when-a-fix-didnt-stick). (`/operational-memory` redirects.) See [`docs/operational-memory.md`](operational-memory.md). |
| **Ask Ops Signals** *(Beta)* | `/assistant` | Grounded conversational Q&A over cases, findings, and behaviors. See [`docs/ask-ops-signals-assistant.md`](ask-ops-signals-assistant.md). |
| **New Analysis** | `/validate-data` | Upload a CSV or point at a Prometheus datasource to run a one-off analysis outside the autonomous scheduler. For a CSV, **Validate Data** previews without saving and **Analyze and Save** stores the findings so they can become cases. See [`docs/standalone-prometheus-analysis.md`](standalone-prometheus-analysis.md). |

### Analyzer Workbench

Its own group in the sidebar, below the main pages:

- **Labs** — one page per analyzer (Z-Score Anomaly, PyOD Outlier, Prophet Forecast, Ruptures Change
  Point, STUMPY Motif, Trend) for running that analyzer directly against sample data and inspecting
  its raw output.
- **Add Analyzer** — the guided flow for registering a new analyzer, either Python code or your own
  HTTP service. See [`docs/analyzer-plugin-framework.md`](analyzer-plugin-framework.md#extensibility-model)
  and [`docs/http-analyzer-contract.md`](http-analyzer-contract.md).
- **Recommendations** — the Universal Router's live recommendation preview for a given series. See
  [`docs/analyzer-recommendation.md`](analyzer-recommendation.md).

### Not a page: alert enrichment and Slack

Alert enrichment and finding notifications have no tab: their output is a Slack message. Each
enriched alert's analysis still produces an ordinary finding, so it appears under **Findings**. The
**Alerts** page and the Overview's alerts panel list received alerts with the same "Where" and
"What changed" as the message, and marks deploys on its timeline; all change events are available at
`GET /api/events`. See
[`docs/alert-enrichment.md`](alert-enrichment.md), or run [`docs/demo.md`](demo.md) to see one.

### Setup check and Settings

**Setup check** (bottom of the sidebar; the old `/system` address opens it) tests each part of the
install: the backend, the database, every metrics connection, memory search, login, and the optional
extras (alerts, deploy events, notifications, ticketing, Grafana, AI). Anything that isn't green has
**How to fix**: what was tried, the likely cause, the steps and config to copy. **Deploy events**
counts both deploys from CI and those found in Prometheus ("3 found automatically in the last 7
days"), and turns yellow when the last look in Prometheus failed
([`docs/deploy-discovery.md`](deploy-discovery.md)). Metrics connections
have a **Test** button, and **Copy report** gives a plain-text summary without secrets for an issue
or an admin. **Per-service analyzer settings** shows which team files are in use, files skipped for
a mistake, and overrides that matched nothing lately; **How to set** lists every setting a team can
change, with its range, and the example file
([`docs/configuration.md`](configuration.md#per-service-analyzer-settings)). A finding made with
these settings has a **Custom settings · not tested** tag. **Login** says which sign-in is on and
who you are; with company sign-in it shows the redirect address to register (with **Copy**), **Test
sign-in**, and **How to set up company sign-in**
([`docs/web-ui-sign-in.md`](web-ui-sign-in.md)). While something needed is broken, Overview shows a reminder linking here. The same
check is on the Grafana plugin's Configuration page, and at `GET /api/setup/check` (with sign-in on, for Admins only; everyone else gets each check's name and status at `GET /api/setup/summary`, which the reminder uses).

**Settings** covers configuration — not part of the core analysis workflow, so not covered further
here, with one exception: Settings'
OTLP Ingestion card shows the push endpoint URL and live received/backlog counts — the closest
equivalent to Prometheus's "Test Connection" for a push-based integration. See
[`docs/design/otlp-metrics-ingestion-plan.md`](design/otlp-metrics-ingestion-plan.md).

## Grafana Plugin

The plugin has two top-level modes, switched via tabs at the top of the app:

| Mode | What it's for |
| --- | --- |
| **Interactive Analysis** | Investigate one metric at a time — pick a Prometheus query, run analyzers against it, and inspect findings directly inside Grafana. |
| **Autonomous Analysis** | The plugin's equivalent of the web UI's Autonomous Analysis Configure + Overview, in one place: a **Configure** stage to set scope/categories and preview or save a schedule, and an **Overview** stage showing the latest run's findings, coverage details, and history. The two are reachable as a persistent tab pair once a scan has run or a schedule exists. A Grafana Viewer gets only the Overview, with the schedule shown read-only above it. |

Setup instructions: [`docs/grafana-plugin-local-setup.md`](grafana-plugin-local-setup.md). Feature
walkthrough: [`docs/grafana-plugin-feature-walkthrough.md`](grafana-plugin-feature-walkthrough.md).
