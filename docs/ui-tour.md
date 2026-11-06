# UI Tour

A short guide to every tab in the standalone web UI and every mode in the Grafana plugin — what
each one is for, and where to read more.

The two frontends are separate applications sharing the same backend (see
[`docs/architecture.md`](architecture.md)); a feature that exists in one does not
automatically exist in the other.

## Standalone Web UI

| Tab | Route | What it's for |
| --- | --- | --- |
| **Overview** | `/` | What needs you now. Start here. **Look at this first** names the one problem to open first, with the counts (findings needing attention, open cases, services affected, automation) as links. **Needs Attention** lists this shift's open cases, combined patterns and new problems in the same order; open cases nothing happened to in 24 hours fold into one line. Below: the count tiles, blind spots (when there are any), and one status line each for Autonomous Analysis and Alerts. The **Shift handoff** button opens the last 8, 12 or 24 hours for the next person on call, with **Copy for Slack** (and **Write with AI** when AI is on). See [Shift handoff](standalone-overview-api.md#shift-handoff). |
| **Alerts** | `/alerts` | Alerts received from Alertmanager and other sources: a 24-hour timeline with deploys marked, and per alert where the change came from (pods), what changed just before (deploys) and the finding or case it was linked to. |
| **Integrations** | `/integrations` | Setup for every way data gets in: OTLP push, Prometheus (URL, reachable, what uses it), the Alertmanager webhook, and deploy events from CI, each with its URL, a snippet and whether data is arriving. |
| **Autonomous Analysis Configure** | `/autonomous-monitoring` | Configure which services/metrics to watch and which monitoring categories to enable, preview the resulting plan, run it once, or save it as a recurring schedule. With sign-in on, a Viewer sees it as **Autonomous Analysis**: the schedule and what runs found, without the set-up form. See [`docs/autonomous-analysis-preview.md`](autonomous-analysis-preview.md). |
| **Findings** | `/findings` | Every single-metric Finding the system has produced, searchable and filterable. A finding is a symptom, not a diagnosis; **What's what?** in the subtitle explains the words on the page (here, on Cases, Behavior Intelligence and Recurring problems) and links the [glossary](glossary.md). Each card's timing chip says whether the problem is still happening or over; a problem that ended moves from Needs attention to Context only an hour later, with the **Over** badge (see [finding states](operational-findings.md#finding-states-from-found-to-over)). Each finding's detail view names which ingestion path produced it (CSV, Prometheus, Datadog, or OTLP) and charts the raw points behind it, for tracing a finding back to what was actually ingested. Cards can carry a pod chip ("2 new pods", "1 of 6 pods") and a deploy chip ("After deploy v1.4.2"); see [the chips on a finding card](finding-drilldown.md#the-chips-on-a-finding-card). With an AI provider on, the detail view's What to check and Happened with lines (and Why it matters, for a metric the wording file doesn't describe) are written for that metric, marked **AI**, with **Show template wording** to switch back; with it off, admins see once how to turn it on. Same in the plugin's evidence panel. See [AI wording](finding-wording.md#ai-wording). See [`docs/operational-findings.md`](operational-findings.md). |
| **Metric Usage** | `/metric-usage` | Which metrics Grafana dashboards and alerts watch, checked every 6 hours: blind spots (problems on metrics nothing shows) first, then metrics a dashboard reads that no longer exist, unwatched metrics, and the unused share of stored series. Watched metrics come last, closed: open them to check your dashboards were found. Each unwatched metric has **Add to Grafana** (a query and the steps) and **Drop** (Prometheus scrape config to stop storing it; tick several for one config), and recording rules nobody reads say how to remove them. See [Metric Usage](metric-usage.md). |
| **Cases** | `/cases` | Every Case (an investigation promoted from a Finding or Behavior Finding). Tabs split them into Open, In progress, On hold and Resolved; the side panel shows the selected case's root cause and timeline. (`/investigations` redirects to the In progress tab.) With AI on, a case's Root Cause and Resolution tabs have **Draft from case**. Publish Knowledge shows the case timeline and a write-up saved with the case. See [`docs/operational-cases.md`](operational-cases.md). |
| **Behavior Intelligence** | `/behavior-intelligence` | Problems that only show up when several metrics are considered together. **Detected** lists the matches, each with the metrics it combined and why it matched (also shown on Findings as combined patterns). **Patterns** lists the rules every run checks and the pairs mined from your data; admins open the builder there (New pattern, Edit copy, Use this pattern, Turn into pattern) to write a rule with conditions in plain words (is rising, is falling, has an unusual spike), see how it would have done on a service's recent runs and open any run for the details, and save it to a pack. `/behavior-intelligence/lab` opens the builder. See [`docs/behavior-intelligence.md`](behavior-intelligence.md). |
| **Recurring problems** | `/recurring-problems` | Past cases grouped into problems that keep coming back, with the causes found and what to do next; whether monitoring caught imported past incidents; and, folded away, the indexing details and the alert-context preview an external alert manager would see. Cases that belong to a recurring problem show a "Seen before" line linking here. A finding or case back within 30 days of a fix on the same service says **Fix didn't hold** instead, naming the old fix; see [When a fix didn't stick](operational-memory.md#when-a-fix-didnt-stick). (`/operational-memory` redirects.) See [`docs/operational-memory.md`](operational-memory.md). |
| **Ask Ops Signals** *(Beta)* | `/assistant` | Grounded conversational Q&A over cases, findings, behaviors and the docs. **Reindex docs** picks up docs you added; the **?** next to it explains it and, under **Writing a doc?**, gives 6 tips for docs the assistant can answer from and a link to **Check new docs**. See [`docs/ask-ops-signals-assistant.md`](ask-ops-signals-assistant.md). |
| **New Analysis** | `/validate-data` | Upload a CSV or point at a Prometheus datasource to run a one-off analysis outside the autonomous scheduler. For a CSV, **Validate Data** previews without saving and **Analyze and Save** stores the findings so they can become cases. A metric with one series per pod is combined into one line the way scheduled runs read it; after **Preview Data**, a **Pods** box picks another way or one pod, and names a pod that behaves differently. See [`docs/standalone-prometheus-analysis.md`](standalone-prometheus-analysis.md). |

### Analyzer Workbench

Its own group in the sidebar, below the main pages. Each item says what it's for:

- **Settings in use** (`/analyzer-settings`) — what every analysis run uses right now. **At a glance**
  says what's changed from the defaults and what runs. The table groups analyzers by whether a run
  uses them, and lists each setting's value, what it means and the file it comes from
  (built-in default, `config/analyzers.yaml`, the data source's file, or a team's file in
  `config/analyzer_overrides.d/`). Pick a service and metric to see their own settings and which
  override won (the Metric box lists that service's metrics). Settings the analyzer only shows as a
  label, or doesn't read in its mode, fold away; a key no analyzer reads is flagged as a likely typo.
  **How settings work** answers which file to edit and why a Lab change didn't change
  findings. Read-only. See [See which analyzer settings are in use](configuration.md#see-which-analyzer-settings-are-in-use).
- **Labs** — one page per analyzer (Z-Score Anomaly, PyOD Outlier, Prophet Forecast, Ruptures Change
  Point, STUMPY Motif, Trend) for running that analyzer directly against sample data and inspecting
  its raw output. Each Lab is a sandbox and says so at the top: it shows the value runs use under
  every field, and after a run with changed values says what the values in use would have found. **Use these values for
  real** turns the values you changed into a snippet for a team's file or for `config/analyzers.yaml`;
  nothing is saved.
- **Add Analyzer** — the guided flow for registering a new analyzer, either Python code or your own
  HTTP service. See [`docs/analyzer-plugin-framework.md`](analyzer-plugin-framework.md#extensibility-model)
  and [`docs/http-analyzer-contract.md`](http-analyzer-contract.md).
- **Which analyzer fits?** — pick an analyzed metric and see which analyzers suit its data, in
  three columns (Good fit, Can help, Not a fit), each with what it looks for and whether it ran on
  that metric last time. Links go to the analyzer's Lab and to Settings in use for that metric; if
  an analyzer ran but doesn't suit the metric, the page offers a per-service setting that turns it
  off there. See [`docs/analyzer-recommendation.md`](analyzer-recommendation.md#which-analyzer-fits-my-metric).

### Not a page: alert enrichment and Slack

Alert enrichment and finding notifications have no tab: their output is a Slack message. Each
enriched alert's analysis still produces an ordinary finding, so it appears under **Findings**. The
**Alerts** page and the Overview's alerts panel list received alerts with the same "Where" and
"What changed" as the message, and marks deploys on its timeline; all change events are available at
`GET /api/events`. See
[`docs/alert-enrichment.md`](alert-enrichment.md), or run [`docs/demo.md`](demo.md) to see one.

### Hand off your shift

To hand off your on-call shift, open **Overview** and click **Shift handoff**. Pick the last 8, 12
or 24 hours: it shows what to watch first, with a button to open it, and what else is worth a look.
**Copy for Slack** copies the note and the list for your team channel; with AI on, **Write with AI**
turns it into a short written note first. In the Grafana plugin the same button is on the Autonomous
Analysis Overview. What it counts: [Shift handoff](standalone-overview-api.md#shift-handoff).

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
these settings has a **Custom settings · not tested** tag. **Login** walks
through the three steps of [`docs/access.md`](access.md) as a strip (lock the API, give people
roles, check it), with **Watch how (2 min)** until it's done and one button for the next step: **Lock the API** with the command to copy, then
**Choose how people sign in** with a card each for the Grafana plugin, company login and a sign-in
proxy, every step tagged with where it happens. With company sign-in on, it shows the redirect
address to register (with **Copy**), **Test sign-in**, and **How to set up company sign-in**; when
done, who you are and **Who can do what**. The **Not signed in** chip top right opens the same step. While something needed is broken, Overview shows a reminder linking here. The same
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
| **Interactive Analysis** | Investigate one metric at a time — pick a Prometheus query, run analyzers against it, and inspect findings directly inside Grafana. A metric with one series per pod is combined into one line, as in New Analysis; a PromQL query that returns one series per pod gets **Combine** buttons that put the combined query in the box. See [`docs/grafana-plugin-feature-walkthrough.md`](grafana-plugin-feature-walkthrough.md). |
| **Autonomous Analysis** | The plugin's equivalent of the web UI's Autonomous Analysis Configure + Overview, in one place: a **Configure** stage to set scope/categories and preview or save a schedule, and an **Overview** stage showing the latest run's findings, coverage details, and history, with a **Shift handoff** button that opens the handoff for the next person on call and **What's what?** in its subtitle for the words it uses. The two are reachable as a persistent tab pair once a scan has run or a schedule exists. A Grafana Viewer gets only the Overview, with the schedule shown read-only above it. |

Setup instructions: [`docs/grafana-plugin-local-setup.md`](grafana-plugin-local-setup.md). Feature
walkthrough: [`docs/grafana-plugin-feature-walkthrough.md`](grafana-plugin-feature-walkthrough.md).
