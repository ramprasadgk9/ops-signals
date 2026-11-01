# Documentation

This is the guided path through Ops Signals' documentation - read top to bottom the first time,
then come back to whichever section you need. Every doc here is also useful standalone; this page
just orders them.

## 1. Get Started

What the project is, and how to get it running.

- [`glossary.md`](glossary.md) - what the words mean: finding, case, analyzer and the other Ops
  Signals terms, then Prometheus, Mimir, tenants, OTLP and the rest of the tech around it.
- [`vision.md`](vision.md) - the fuller product vision, including the MTTR framing referenced
  throughout these docs.
- [`demo.md`](demo.md) - one `docker compose up` that starts Ops Signals with four services already
  in trouble (an enriched alert, a fix that didn't stick, an unannounced deploy, an OTLP service
  with a case in progress). Start here to see it working before installing anything.
- [`live-demo.md`](live-demo.md) - a live, menu-driven demo next to `run_all.sh`: rollouts, slow
  rises, spikes and staging deploys, with real alerts and pod breakdowns.
- **[Quick Start](../README.md#quick-start)** (root `README.md`) - clone, setup script, run script,
  open the UI. Start here to actually install it.
- [`getting-started.md`](getting-started.md) - after the Quick Start: point it at your own
  Prometheus or Mimir, connect a data source, turn on AI, troubleshooting, and every script.
- [`deploy.md`](deploy.md) - running it for a team: one server with Docker Compose, Kubernetes with
  Helm, and adding the Grafana plugin to your own Grafana.
- [`data-sources.md`](data-sources.md) - Prometheus and Mimir connections, CSV input, deploy and
  change events, and findings as Prometheus metrics.
- [`otlp.md`](otlp.md) - sending metrics from an OTel SDK or Collector, and what works with OTLP
  only.
- [`metric-usage.md`](metric-usage.md) - blind spots, missing and unwatched metrics, and the Add to
  Grafana and Drop actions.
- [`access.md`](access.md) - **start here before others use it.** Who can use Ops Signals in three
  steps: lock the API, give people roles (Grafana plugin, company login or a sign-in proxy), check
  it on Setup check. One table of what each role can do.
- [`security-model.md`](security-model.md) - what's open by default, the API token, the switches
  for the reset and file-writing endpoints, and CORS. Read it before exposing Ops Signals beyond
  your own machine.
- [`running-multiple-backends.md`](running-multiple-backends.md) - running several backends on one
  database: what they must share, which background jobs run once and which may repeat, and the
  recommended setup.
- [`grafana-plugin-local-setup.md`](grafana-plugin-local-setup.md) - installing the Grafana app
  plugin specifically, if that's how you plan to use Ops Signals.
- [`grafana-plugin-access-and-roles.md`](grafana-plugin-access-and-roles.md) - signing in through
  Grafana, what Viewers, Editors and Admins can do, who-did-what, and how to check it locally.
- [`web-ui-sign-in.md`](web-ui-sign-in.md) - signing in to the web UI with your company's identity
  provider (OpenID Connect) or sign-in proxy, and roles from company groups.
- [`try-company-sign-in.md`](try-company-sign-in.md) - trying that sign-in before onboarding a team:
  a throwaway Keycloak set up by a script or by hand, and what each role should see.
- [`adoption-roadmap.md`](adoption-roadmap.md) - what's next so companies with many teams can adopt
  it: sign-in through Grafana, roles, login modes, team ownership.
- [`grafana-plugin-roadmap.md`](grafana-plugin-roadmap.md) - where the Grafana plugin stands and
  the steps to Grafana's plugin catalog (create-plugin build, signing, submission).

## 2. Architecture Deep Dive

How the pieces fit together, what talks to what, and why the two storage layers exist.

- [`architecture.md`](architecture.md) - **start here for architecture.** The full pipeline
  (ingest → route/analyze → find/correlate → case lifecycle → persist → consume), a diagram, and a
  "Why This Reduces MTTR" section connecting the pipeline to actual operational outcomes.
- [`core-domain-model.md`](core-domain-model.md) - the data model: canonical points, signals,
  and the fields on each.
- [`operational-memory.md`](operational-memory.md) - how a resolved Case becomes a Qdrant
  embedding, and how semantic similarity search over past cases works.
- [`importing-incident-history.md`](importing-incident-history.md) - filling operational memory on
  day one by importing past postmortems and incidents from Jira, PagerDuty, incident.io or CSV and
  Markdown files: what to export, how fields map, and why re-importing never duplicates.
- [`design-decisions.md`](design-decisions.md) and [`adr/`](adr/) - the "why," in short
  ADR-style writeups: why Postgres is the system of record, why Qdrant is a retrieval index and not
  the source of truth, why answer composition is deterministic by default, and more.
- [`design/otlp-metrics-ingestion-plan.md`](design/otlp-metrics-ingestion-plan.md) - the OTLP/HTTP metrics
  ingestion path: the receiver, volume/cardinality guardrails, how received points reach the
  scheduler's existing analysis cycle, and the self-observability endpoints.
- [`alert-enrichment.md`](alert-enrichment.md) - Slack finding notifications and alert enrichment:
  Alertmanager alerts analyzed on arrival and posted to Slack with what happened, what changed, and
  similar past cases. Why it matters, how it fits the pipeline, and setup. Design details:
  [`design/alert-enrichment-plan.md`](design/alert-enrichment-plan.md).
- [`deploy-discovery.md`](deploy-discovery.md) - deploys found in Prometheus without CI: a new
  version on a `*_build_info` metric or a new Kubernetes ReplicaSet, and how duplicates with CI's
  deploys are avoided.
- [`finding-metrics.md`](finding-metrics.md) - active findings on `GET /api/metrics`, so alert rules,
  Alertmanager routes and dashboards can use them; scrape config and example alert rules.
- [`mcp-server.md`](mcp-server.md) - the MCP server over stdio: read-only and write modes, the
  tools each exposes, testing it, and client configuration.

**External integration**: if you're plugging Ops Signals into your own alerting or automation, the
consumer surface is `POST /api/integrations/alertmanager` (enrich alerts as they fire - see
[`alert-enrichment.md`](alert-enrichment.md)), `GET /api/alert-context` (pre-page decision support) and
`POST /api/assistant/chat` (conversational Q&A) - the last two documented in `architecture.md`'s
"Consume" section. [`integrations.md`](integrations.md) is the full index: every data-in, data-out,
pluggable-surface and "where you work" integration in one table, each with what it's for and how it's
wired.

## 3. Analyzers

What analyzers are, why a given one gets picked for a given metric, and how much to trust that pick.

- [`analyzers-explained.md`](analyzers-explained.md) - **start here for analyzers.** The nine
  analyzers in plain words, each with a chart of the behavior it catches, a one-page comparison and
  when each one runs.
- [`analyzer-plugin-framework.md`](analyzer-plugin-framework.md) - what an analyzer is, the
  two-registry model (pipeline vs. router), and how to add your own.
- [`http-analyzer-contract.md`](http-analyzer-contract.md) - connect your own model or detection
  service over HTTP: the request and reply format, a runnable example, and what happens when the
  service is down.
- [`analyzer-recommendation.md`](analyzer-recommendation.md) - **the** reference for routing:
  how the Universal Router scores and picks analyzers, eligibility vs. suitability, and the
  weighting behind the scores.
- [`analyzer-methodology.md`](analyzer-methodology.md) - which analyzers are published,
  validated methods versus which parts (the router's scoring weights) are heuristic and
  not yet validated against real outcomes. Read this before trusting a recommendation blindly.
- [`finding-trust.md`](finding-trust.md) - how much to trust a finding: the "Needs attention" and
  "Context only" lists, the badges, the tested numbers behind them (and how they compare with a
  random alert), and the "Was this real?" answers that replace them for your service.
- [`finding-wording.md`](finding-wording.md) - how finding cards and Slack messages describe a
  finding in plain words, and how to change that wording in `config/finding_templates.yaml`.
- [`ai-features.md`](ai-features.md) - every place AI is used, in one table: where it shows, what
  it adds, what shows without it, and what each feature sends to the provider.
- [`finding-anatomy.md`](finding-anatomy.md) - one finding followed through wording, trust and
  "Happened with" to the finished card. Start here before the two pages above.

## 4. UI Tour

- [`ui-tour.md`](ui-tour.md) - every tab in the standalone web UI (Overview, Autonomous Analysis
  Configure, Investigations, Findings, Cases, Behavior Intelligence, Operational
  Memory, Ask Ops Signals, Experiments, New Analysis) and every mode in the Grafana plugin
  (Interactive Analysis, Autonomous Analysis), with a one-line purpose and a link to the deeper doc
  for each.

## 5. Behavioral Intelligence

- [`behavior-intelligence.md`](behavior-intelligence.md) - why cross-metric reasoning exists
  (some problems only show up when you look at two metrics together, e.g. CPU anomaly + rising
  throttling), the declarative YAML model, and a full worked example of configuring one.

## 6. Analyzer Workbench

- [`analyzer-plugin-framework.md#analyzer-workbench-ui`](analyzer-plugin-framework.md#analyzer-workbench-ui) -
  Settings in use (which settings runs use, and from which file), the Labs (run any analyzer
  directly against sample data), Add Analyzer wizard, and Recommendations preview, all grouped under
  Analyzer Workbench in the web UI.
- [`configuration.md#see-which-analyzer-settings-are-in-use`](configuration.md#see-which-analyzer-settings-are-in-use) -
  where an analyzer setting comes from, which file to edit, and why a Lab change doesn't change findings.

## 7. Design Documents

Technical plans behind larger features: the decisions, trade-offs and non-goals. Read these when
you're changing the feature, not to learn how to use it.

- [`design/otlp-metrics-ingestion-plan.md`](design/otlp-metrics-ingestion-plan.md) - OTLP/HTTP
  metrics ingestion (implemented).
- [`design/alert-enrichment-plan.md`](design/alert-enrichment-plan.md) - Alertmanager receiver and
  change-event correlation (implemented, except the read API and retention cleanup).
- [`design/proposals/jira-integration-plan.md`](design/proposals/jira-integration-plan.md) - Pluggable
  case ticketing integration with Jira Cloud reference implementation (implemented).
- [`design/proposals/`](design/proposals/) - active architectural proposals.

---

Everything else in this folder (release process, benchmark suite, ADRs, screenshots, roadmap) is
reference material rather than part of the guided path - browse [the rest of `docs/`](.) as needed.
