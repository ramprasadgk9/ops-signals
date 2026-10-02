# Documentation

This is the guided path through Ops Signals' documentation - read top to bottom the first time,
then come back to whichever section you need. Every doc here is also useful standalone; this page
just orders them.

## 1. Get Started

What the project is, and how to get it running.

- [`01-vision.md`](01-vision.md) - the fuller product vision, including the MTTR framing referenced
  throughout these docs.
- [`demo.md`](demo.md) - one `docker compose up` that starts Ops Signals with an incident already
  in progress (a deploy, a latency shift, an enriched alert, a matching past case). Start here to
  see it working before installing anything.
- [`live-demo.md`](live-demo.md) - a live, menu-driven demo next to `run_all.sh`: rollouts, slow
  rises, spikes and staging deploys, with real alerts and pod breakdowns.
- **[Quick Start](../README.md#quick-start)** (root `README.md`) - clone, setup script, run script,
  open the UI. Start here to actually install it.
- [`comparison.md`](comparison.md) - how Ops Signals relates to Robusta/HolmesGPT, Keep and
  Grafana Sift, including where those tools are ahead.
- [`security-model.md`](security-model.md) - what's open by default, the API token, the switches
  for the reset and file-writing endpoints, and CORS. Read it before exposing Ops Signals beyond
  your own machine.
- [`grafana-plugin-local-setup.md`](grafana-plugin-local-setup.md) - installing the Grafana app
  plugin specifically, if that's how you plan to use Ops Signals.

## 2. Architecture Deep Dive

How the pieces fit together, what talks to what, and why the two storage layers exist.

- [`02-architecture.md`](02-architecture.md) - **start here for architecture.** The full pipeline
  (ingest → route/analyze → find/correlate → case lifecycle → persist → consume), a diagram, and a
  "Why This Reduces MTTR" section connecting the pipeline to actual operational outcomes.
- [`03-core-domain-model.md`](03-core-domain-model.md) - the data model: canonical points, signals,
  and the fields on each.
- [`08-operational-memory.md`](08-operational-memory.md) - how a resolved Case becomes a Qdrant
  embedding, and how semantic similarity search over past cases works.
- [`09-design-decisions.md`](09-design-decisions.md) and [`adr/`](adr/) - the "why," in short
  ADR-style writeups: why Postgres is the system of record, why Qdrant is a retrieval index and not
  the source of truth, why answer composition is deterministic by default, and more.
- [`design/otlp-metrics-ingestion-plan.md`](design/otlp-metrics-ingestion-plan.md) - the OTLP/HTTP metrics
  ingestion path: the receiver, volume/cardinality guardrails, how received points reach the
  scheduler's existing analysis cycle, and the self-observability endpoints.
- [`alert-enrichment.md`](alert-enrichment.md) - Slack finding notifications and alert enrichment:
  Alertmanager alerts analyzed on arrival and posted to Slack with what happened, what changed, and
  similar past cases. Why it matters, how it fits the pipeline, and setup. Design details:
  [`design/alert-enrichment-plan.md`](design/alert-enrichment-plan.md).
- [`mcp-server.md`](mcp-server.md) - the MCP server over stdio: read-only and write modes, the
  tools each exposes, testing it, and client configuration.

**External integration**: if you're plugging Ops Signals into your own alerting or automation, the
consumer surface is `POST /api/integrations/alertmanager` (enrich alerts as they fire - see
[`alert-enrichment.md`](alert-enrichment.md)), `GET /api/alert-context` (pre-page decision support) and
`POST /api/assistant/chat` (conversational Q&A) - the last two documented in `02-architecture.md`'s
"Consume" section.

## 3. Analyzers

What analyzers are, why a given one gets picked for a given metric, and how much to trust that pick.

- [`04-analyzer-plugin-framework.md`](04-analyzer-plugin-framework.md) - what an analyzer is, the
  two-registry model (pipeline vs. router), and how to add your own.
- [`16-analyzer-recommendation.md`](16-analyzer-recommendation.md) - **the** reference for routing:
  how the Universal Router scores and picks analyzers, eligibility vs. suitability, and the
  weighting behind the scores.
- [`26-analyzer-methodology.md`](26-analyzer-methodology.md) - which analyzers are published,
  validated methods versus which parts (the router's scoring weights) are heuristic and
  not yet validated against real outcomes. Read this before trusting a recommendation blindly.

## 4. UI Tour

- [`ui-tour.md`](ui-tour.md) - every tab in the standalone web UI (Overview, Autonomous Analysis
  Configure, Investigations, Findings, Cases, Behavior Intelligence, Behavior Lab, Operational
  Memory, Ask Ops Signals, Experiments, New Analysis) and every mode in the Grafana plugin
  (Interactive Analysis, Autonomous Analysis), with a one-line purpose and a link to the deeper doc
  for each.

## 5. Behavioral Intelligence

- [`14-behavior-intelligence.md`](14-behavior-intelligence.md) - why cross-metric reasoning exists
  (some problems only show up when you look at two metrics together, e.g. CPU anomaly + rising
  throttling), the declarative YAML model, and a full worked example of configuring one.

## 6. Analyzer Workbench

- [`04-analyzer-plugin-framework.md#analyzer-workbench-ui`](04-analyzer-plugin-framework.md#analyzer-workbench-ui) -
  the Labs (run any analyzer directly against sample data), Add Analyzer wizard, and Recommendations
  preview, all grouped under Experiments in the web UI.

## 7. Design Documents

Technical plans behind larger features: the decisions, trade-offs and non-goals. Read these when
you're changing the feature, not to learn how to use it.

- [`design/otlp-metrics-ingestion-plan.md`](design/otlp-metrics-ingestion-plan.md) - OTLP/HTTP
  metrics ingestion (implemented).
- [`design/alert-enrichment-plan.md`](design/alert-enrichment-plan.md) - Alertmanager receiver and
  change-event correlation (implemented, except the read API and retention cleanup).
- [`design/proposals/`](design/proposals/) - proposals that are not built yet, such as
  [`jira-integration-plan.md`](design/proposals/jira-integration-plan.md).

---

Everything else in this folder (release process, benchmark suite, ADRs, screenshots, roadmap) is
reference material rather than part of the guided path - browse [the rest of `docs/`](.) as needed.
