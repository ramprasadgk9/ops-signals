# Open-Source Release Review

This document is an implementation-first review of the repository as it exists now,
after the standalone Operational Intelligence UI revamp, direct Prometheus analysis
integration, overview summary endpoints, memory statistics endpoint, assistant
routing improvements, Qdrant health fix, and screenshot gallery documentation.

It is intentionally strict: if a capability is only described in documentation but
not confirmed in code, it is not treated as complete.

## Executive Summary

Ops Signals is a real, working early-stage open-source project. It now has
meaningful depth across standalone UI workflows, CSV ingestion, direct Prometheus
query analysis, analyzers, findings, cases, behavior rules, operational memory,
assistant routing, a Grafana plugin, and an MCP server.

It is not production-ready yet, but it is now in credible public early-release
territory. The strongest framing is: a self-hostable operational intelligence
workspace for turning time-series data into explainable findings, cases, and
retrievable operational memory.

### Overall assessment

- Open-source release readiness: 7.8 / 10
- Production readiness: 3.5 / 10

### Why this score

- The core domain is implemented end to end.
- The repo has local setup scripts and repeatable developer workflows.
- The standalone UI is now a product-shaped Operational Intelligence workspace
  rather than a thin developer dashboard.
- Direct Prometheus analysis is implemented in the standalone app without changing
  the Grafana plugin contract.
- Overview and memory statistics now use backend endpoints instead of frontend
  mock or invented values.
- The assistant and memory layers are real, but still mostly retrieval and
  deterministic composition rather than deeply generative intelligence.
- Some optional analyzers fall back to heuristics when external libraries are unavailable.
- The test suite is materially better than before, but still lacks browser E2E
  coverage, Grafana integration automation, and benchmark/golden-output tests.
- First-time-user documentation is decent, but still needs a guided tour with
  expected outputs from one stable demo run.

## What the Project Solves

Ops Signals turns time-series data into:

- normalized operational records
- analyzer-generated signals
- aggregated findings
- explainable behavior findings
- investigation cases
- searchable operational memory
- assistant-style retrieval over cases and repo knowledge

It is best understood as an operational intelligence layer on top of existing observability tooling, not a replacement for Grafana, Prometheus, Datadog, or incident-management systems.

## What Is Already Implemented

### Data Ingestion

| Feature | Status | Where implemented | What it does | Limits |
| --- | --- | --- | --- | --- |
| CSV ingest | Complete | `intelligence/adapters/csv_adapter.py`, `intelligence/pipeline.py`, `backend/app/api/ingestion.py` | Loads canonical CSV inputs and sends them through the pipeline | Not a generic file-ingestion platform |
| Prometheus-style ingest | Complete | `backend/app/api/ingestion.py`, `frontend/src/grafana/grafanaPrometheus.ts`, `frontend/src/grafana/PluginApp.tsx` | Supports Prometheus-shaped samples through existing analysis flow | Requires correctly shaped sample payloads |
| Direct Prometheus query analysis | Complete | `backend/app/api/direct_prometheus.py`, `backend/app/services/prometheus_service.py`, `frontend/src/pages/ValidateDataPage.tsx`, `docs/18-standalone-prometheus-analysis.md` | Queries Prometheus HTTP API from the standalone app, previews time-series data, and runs the existing analyzer pipeline | First release requires a single returned series; connection profiles are environment-based |
| Normalization | Complete | `intelligence/normalize/normalizer.py`, `tests/test_prometheus_timestamp_normalizer.py` | Normalizes timestamps and canonical fields | Provider-specific behavior still depends on config and input shape |
| PostgreSQL storage | Complete | `backend/app/models/entities.py`, `intelligence/storage/postgres_store.py` | Stores normalized points, signals, findings, cases, runs, capabilities, questions, and learning outcomes | Requires correct initialization and DB setup |
| Analysis runs | Complete | `backend/app/models/entities.py`, `intelligence/pipeline.py`, `backend/app/api/analysis_runs.py` | Records run metadata, routing, and outputs | No scheduling or orchestration engine |

### Analyzer Framework

| Feature | Status | Where implemented | What it does | Limits |
| --- | --- | --- | --- | --- |
| Analyzer base interface | Complete | `intelligence/analyzers/base.py` | Defines a consistent analyzer contract | None significant |
| Analyzer registry | Complete | `backend/app/capabilities/registry.py`, `backend/app/capabilities/builtins.py`, `intelligence/pipeline.py` | Exposes analyzer capabilities and supported questions | Still centered on built-in analyzers |
| Baseline shift analyzer | Complete | `intelligence/analyzers/baseline_shift.py` | Detects sustained changes in central tendency | Simple midpoint comparison |
| Z-score anomaly analyzer | Complete | `intelligence/analyzers/anomaly_zscore.py` | Detects statistically unusual points and groups them | Basic z-score detection only |
| Trend analyzer | Complete | `intelligence/analyzers/trend.py` | Detects directional trend over a window | Linear trend only |
| Change-point analyzer | Complete | `intelligence/analyzers/ruptures.py` | Detects persistent change points | Still a simple implementation |
| STUMPY analyzer | Partial | `intelligence/analyzers/stumpy.py` | Detects motifs or falls back to a custom search | Optional dependency may be missing; fallback is heuristic |
| Prophet analyzer | Partial | `intelligence/analyzers/prophet.py` | Forecasts future values or falls back to linear extrapolation | Optional dependency may be missing; fallback is heuristic |
| Analyzer configuration | Complete | `config/analyzers.yaml`, `intelligence/pipeline.py` | Enables/disables analyzers and sets parameters | Selection logic still depends on current router rules |
| Analyzer extensibility | Complete | `intelligence/analyzers/base.py`, `backend/app/capabilities/builtins.py` | New analyzers can be added through the shared interface | No external plugin ecosystem yet |

### Findings

| Feature | Status | Where implemented | What it does | Limits |
| --- | --- | --- | --- | --- |
| Finding generation | Complete | `intelligence/finding_aggregator.py`, `intelligence/pipeline.py`, `backend/app/api/findings.py` | Aggregates signals into findings | Rules-based, not adaptive |
| Evidence payloads | Complete | Analyzer modules, `intelligence/signals/schema.py` | Stores evidence, severity, confidence, timestamps | Evidence richness depends on analyzer |
| Confidence | Complete | Analyzer modules | Stores heuristic confidence values | Not calibrated probabilistically |
| Importance scoring | Complete | `intelligence/importance_score.py` | Produces importance scores for signals and findings | Heuristic scoring |
| Categories | Complete | Finding aggregator, entity schema | Assigns categories and health status | Category system is still fairly simple |
| Explanations | Complete | `intelligence/daily_report.py`, `backend/app/questions/composer.py` | Produces human-readable summaries and answers | Mostly deterministic templates |

### Behavior Intelligence

| Feature | Status | Where implemented | What it does | Limits |
| --- | --- | --- | --- | --- |
| YAML behavior rules | Complete | `config/behavior_definitions.yml`, `backend/app/behavior_intelligence/loader.py` | Loads behavior definitions from YAML | Custom rule format, not a general rule engine |
| Multi-signal matching | Complete | `backend/app/behavior_intelligence/service.py` | Combines multiple signals across metrics | Depends on exact metric/analyzer matches |
| Rule execution | Complete | `backend/app/behavior_intelligence/condition_evaluator.py`, `backend/app/behavior_intelligence/finding_builder.py` | Evaluates conditions and creates behavior findings | No live authoring UI |
| Configurable behaviors | Complete | `config/behavior_definitions.yml`, `backend/app/api/behavior_definitions.py` | Behavior definitions are API-visible and configurable in config | Editing is not exposed as a polished UI workflow |

### Operational Cases

| Feature | Status | Where implemented | What it does | Limits |
| --- | --- | --- | --- | --- |
| Create case from finding | Complete | `backend/app/api/cases.py` | Promotes findings into cases | No bulk workflow |
| Investigation updates | Complete | `backend/app/api/cases.py` | Stores investigation status and notes | Notes are JSON-backed and lightweight |
| RCA updates | Complete | `backend/app/api/cases.py` | Stores root cause fields and verification | No strict state machine |
| Resolution updates | Complete | `backend/app/api/cases.py` | Stores outcome, corrective action, and learning outcome | Some transitions are still heuristic |
| Learning outcome capture | Complete | `backend/app/services/analyzer_learning_service.py` | Creates learning records from finalized cases | Learning flow is useful but still not fully polished |
| Case lifecycle | Complete | `backend/app/models/entities.py`, `backend/app/api/cases.py` | Tracks status from open to resolved through investigation, RCA, and outcome | Derived status logic is somewhat ad hoc |

### Operational Memory

| Feature | Status | Where implemented | What it does | Limits |
| --- | --- | --- | --- | --- |
| Qdrant integration | Complete | `backend/app/memory/vector_store.py`, `backend/app/memory/qdrant_initializer.py`, `backend/app/assistant/knowledge_bootstrap.py` | Stores embeddings and payload metadata | Requires Qdrant |
| Embeddings | Complete | `backend/app/memory/embedder.py`, `intelligence/embeddings/embedder.py` | Builds embeddings for cases and docs | Quality depends on embedding backend/model |
| Similar case retrieval | Complete | `backend/app/memory/similarity_service.py`, `backend/app/api/memory.py` | Finds similar operational cases by vector search | Similarity is not root-cause proof |
| Case indexing | Complete | `backend/app/memory/indexer.py` | Indexes case summaries into memory | Re-indexing/staleness handling is basic |
| Memory search | Complete | `backend/app/api/memory.py`, `backend/app/assistant/service.py` | Supports memory chat and similarity lookup | Retrieval quality depends on summary quality and embeddings |
| Memory statistics | Complete | `backend/app/api/memory.py`, `backend/app/memory/schemas.py`, `frontend/src/standalone/memoryService.ts`, `docs/17-standalone-overview-api.md` | Counts case memory status from PostgreSQL case metadata and reports vector-store health | Counts describe case metadata, not raw Qdrant point totals |
| Qdrant health check | Complete | `backend/app/memory/vector_store.py`, `tests/test_qdrant_vector_store.py` | Verifies collection existence and detailed collection info | Does not yet reconcile DB indexed-case count against Qdrant point count |

### Knowledge / Chat

| Feature | Status | Where implemented | What it does | Limits |
| --- | --- | --- | --- | --- |
| Assistant routing | Complete | `backend/app/api/assistant.py`, `backend/app/assistant/service.py`, `tests/api_backend/test_assistant_routing.py` | Routes chat across cases, findings, memory, behavior, docs, and analyzer guidance | Not a general-purpose oracle |
| Historical retrieval | Complete | `backend/app/assistant/service.py`, `backend/app/memory/similarity_service.py` | Uses embeddings and Qdrant to find similar cases | Retrieval-backed, not a proof engine |
| App/document retrieval | Complete | `backend/app/assistant/knowledge_bootstrap.py` | Indexes README, docs, and generated overview docs | Depends on bootstrap having run successfully |
| Evidence grouping | Complete | `backend/app/assistant/schemas.py`, `frontend/src/pages/MemoryChatPage.tsx` | Returns grouped assistant evidence and renders it in a side panel | Ranking and summarization are still deterministic |
| Deterministic question answering | Complete | `backend/app/questions/router.py`, `backend/app/questions/composer.py` | Routes supported questions to rule-based answers | Only a fixed set of questions is supported |
| Uses signals and cases | Complete | `backend/app/questions/router.py`, `backend/app/assistant/service.py` | Grounds responses in signals and cases | Still deterministic and limited by known question ids |
| Uses run context | Complete | `backend/app/assistant/service.py`, `backend/app/memory/document_builder.py` | Injects case context into retrieval queries | Not every run detail is surfaced back to the user |

### Web UI

| Feature | Status | Where implemented | What it does | Limits |
| --- | --- | --- | --- | --- |
| Standalone shell | Complete | `frontend/src/components/AppShell.tsx`, `frontend/src/standalone/components.tsx`, `frontend/src/standalone/theme.ts` | Provides sidebar, top bar, status panel, and shared workspace primitives | Still optimized for local single-user operation |
| Overview page | Complete | `frontend/src/pages/OverviewPage.tsx`, `backend/app/api/overview.py`, `frontend/src/pages/OverviewPage.test.tsx` | Shows KPI cards, severity trend, category breakdown, recent findings, cases, behavior changes, and memory preview from real APIs | Time window support is limited to `24h` and `7d` |
| Findings page | Complete | `frontend/src/pages/FindingsPage.tsx`, `backend/app/api/findings.py` | Browse findings with window-aware alignment to overview trend/category data | No heavy analytics suite |
| Investigations page | Complete | `frontend/src/pages/InvestigationsPage.tsx`, `frontend/src/standalone/casesService.ts` | Case-derived investigation workflow view | No separate investigation backend entity |
| Cases page | Complete | `frontend/src/pages/CasesPage.tsx`, `frontend/src/standalone/casesService.ts` | Search/filter cases with preview and navigation | Assignment model is explicitly unsupported |
| Case details page | Complete | `frontend/src/pages/CaseDetailsPage.tsx` | Inspect and edit investigation, RCA, resolution, similar cases, and explicit Publish Knowledge step | Needs stricter backend state validation |
| History page | Complete | `frontend/src/pages/HistoryPage.tsx` | Browse analysis runs | Limited as a history explorer |
| Question answers | Complete | `frontend/src/pages/QuestionAnswerPage.tsx` | View routed answers | Strongly tied to supported question catalog |
| Capabilities page | Complete | `frontend/src/pages/CapabilitiesPage.tsx` | Show analyzer/question mapping | Could use more explanatory text |
| Behavior intelligence page | Complete | `frontend/src/pages/BehaviorIntelligencePage.tsx`, `frontend/src/standalone/behaviorService.ts` | Shows behavior KPIs, detected behaviors, rules, and pattern library | Rules are read-only in the UI |
| Analyzer recommendation page | Complete | `frontend/src/pages/AnalyzerRecommendationPage.tsx` | Show ranking and recommendation output | Heuristic/recommendation-centric |
| New Analysis / Validate Data page | Complete | `frontend/src/pages/ValidateDataPage.tsx`, `backend/app/api/direct_prometheus.py`, `backend/app/services/prometheus_service.py` | Supports CSV upload and direct Prometheus preview/run workflow with time-window controls | First release accepts one Prometheus series per analysis |
| Experiment pages | Complete | `frontend/src/pages/ExperimentDashboardPage.tsx`, `frontend/src/pages/AnalyzerRouterExperimentPage.tsx` | Support router experiments and comparison | Feels more internal than release-polished |
| Operational Memory inventory | Complete | `frontend/src/pages/OperationalMemoryPage.tsx`, `frontend/src/pages/OperationalMemoryPage.test.tsx` | Shows authoritative memory status counts and case-backed indexed/stale/failed/not-indexed inventory | Inventory uses case API pagination, not direct Qdrant enumeration |
| Assistant chat | Complete | `frontend/src/pages/MemoryChatPage.tsx` | Ask retrieval-backed questions over cases, findings, behavior, memory, and docs | Depends on indexed memory and bootstrapped app knowledge quality |
| Settings | Complete | `frontend/src/pages/SettingsPage.tsx` | Basic settings surface | Fairly lightweight |
| System page | Complete | `frontend/src/pages/SystemPage.tsx` | Basic runtime/system status surface | Not a full admin console |
| Signal detail | Complete | `frontend/src/pages/SignalDetailPage.tsx` | Inspect individual signals | Could be richer |

### Grafana Plugin

| Feature | Status | Where implemented | What it does | Limits |
| --- | --- | --- | --- | --- |
| Plugin packaging | Complete | `frontend/plugin.json`, `frontend/src/module.ts` | Builds a Grafana plugin bundle | Still local/developer-oriented |
| Plugin UI | Complete | `frontend/src/panel/OpsSignalsPanel.tsx`, `frontend/src/grafana/PluginApp.tsx` | Shows analysis results in Grafana context | UX is not enterprise-polished yet |
| Prometheus integration | Complete | `frontend/src/grafana/grafanaPrometheus.ts`, `frontend/src/grafana/prometheusQueryBuilder.ts` | Supports Grafana/Prometheus-oriented workflows | Limited to current plugin design |
| Local Grafana stack | Complete | `scripts/run_grafana_stack.sh` | Runs Grafana, Prometheus, mock metrics, backend | Local-dev stack rather than hosted distribution |

### MCP Server

| Feature | Status | Where implemented | What it does | Limits |
| --- | --- | --- | --- | --- |
| MCP server | Complete | `backend/app/mcp_server.py`, `intelligence/cli.py` | Exposes MCP over stdio | Agent-facing, but still bounded by current tool semantics |
| Read-only tool mode | Complete | `backend/app/mcp_server.py` | Restricts tools to read-only set | Good for safe exploration |
| Write mode | Complete | `backend/app/mcp_server.py`, `intelligence/cli.py` | Exposes update/create/index tools | Needs careful use by agents |
| Tool catalog | Complete | `backend/app/api/mcp.py` | Lists MCP tools and schemas | Tool set is broad but still domain-specific |

### Testing

| Feature | Status | Where implemented | What it does | Limits |
| --- | --- | --- | --- | --- |
| Config loader tests | Complete | `tests/test_config_loader.py` | Verifies config merging | Limited scope |
| Pipeline test | Complete | `tests/test_csv_pipeline.py` | Verifies pipeline signal/finding generation | In-memory store only |
| Normalizer test | Complete | `tests/test_prometheus_timestamp_normalizer.py` | Verifies timestamp parsing | Narrow behavior coverage |
| API tests | Complete | `tests/api_backend/*.py` | Covers key backend behaviors including overview summary, memory stats, direct Prometheus, assistant routing, and findings window filtering | Missing broader integration coverage |
| Frontend unit/page tests | Partial | `frontend/src/**/*.test.tsx`, `frontend/src/standalone/*.test.ts` | Covers standalone services, import boundaries, overview resilience, operational memory, and Prometheus UI basics | No browser E2E suite yet |

## What Is Only Partial

These features exist, but are not fully polished or fully comprehensive.

### STUMPY and Prophet

Both analyzers are implemented with optional dependency paths and fallbacks.
If the external libraries are not installed, the system falls back to heuristic behavior.

### Analyzer recommendation engine

The recommendation engine is real and useful, but still mostly profile-based.
It ranks analyzers from metric shape, not from deeper analyzer-specific runtime probes.

### Knowledge assistant

The assistant is grounded in retrieval and deterministic routing. It now has
broader routes for cases, findings, memory, behavior, documentation, and analyzer
guidance, plus evidence grouping in the UI. That is good for reliability, but it
still means the system is not a broad autonomous or generative operations agent.

### Prometheus

Prometheus support is now stronger. The standalone UI can query Prometheus directly
for preview and persisted analysis, and the Grafana plugin still uses Grafana's
datasource flow. It is still not a Prometheus replacement: collection, alerting,
long-term storage, and dashboarding remain external concerns.

### Case lifecycle automation

Case status and outcome transitions exist, but the lifecycle logic is still heuristic rather than a strict domain state machine.

### Grafana plugin UX

The plugin works, but it still feels closer to a functional developer integration than a fully polished distribution-ready plugin.

### Memory reconciliation

PostgreSQL case metadata is the authoritative source for memory status counts.
Qdrant is the vector retrieval backend. The system does not yet reconcile
`memory_status=indexed` rows against raw Qdrant point counts in a dedicated
repair or audit workflow.

## What Is Missing or Planned

| Feature | Status | Evidence | Why it is not complete |
| --- | --- | --- | --- |
| Autonomous remediation | Missing | `README.md` explicitly says it does not perform autonomous remediation | There is no remediation engine |
| Stable screenshot gallery | Complete | `docs/screenshots.md`, `docs/screenshots/images/web/`, `docs/screenshots/images/grafana-plugin/` | Screenshots are now documented; keeping them current is a release maintenance task |
| Stronger memory workflows | Partial / evolving | `README.md`, `backend/app/api/memory.py`, `frontend/src/pages/OperationalMemoryPage.tsx` | The flow is useful, but lacks reconciliation, repair, and admin operations |
| Richer retrieval filters and comparison views | Planned | `README.md` roadmap, `docs/10-roadmap.md` | Not yet implemented as a polished feature |
| More analyzer coverage | Planned | `README.md` roadmap | Current analyzer set is useful but limited |
| Better regression datasets | Planned | `README.md` roadmap, tests folder | Benchmark/eval corpus is still small |
| Better contributor docs | Planned | `README.md`, `docs/13-release-process.md` | The repo has guidance, but not a full contributor onboarding package |
| More polished first-run onboarding | Planned | Current README and UI | A first-time user still has to infer too much |
| Browser E2E tests | Missing | No Playwright/Cypress workflow is present | Current frontend coverage is unit/page-level, not browser workflow validation |

## Internal Knowledge Retrieval Flow

The assistant is not magic. It works like this:

1. It classifies intent as historical, application, or mixed in `backend/app/assistant/service.py`.
2. For historical questions, it builds a case document using `CaseDocumentBuilder`.
3. It embeds that document and searches Qdrant through `SimilarityService`.
4. It hydrates matched case rows from PostgreSQL.
5. For application questions, it embeds the question and searches the docs vector store.
6. The docs vector store is bootstrapped from README, docs, and generated overview documents in `backend/app/assistant/knowledge_bootstrap.py`.
7. Question-specific answers are deterministic and routed through `QuestionRouter` and `AnswerComposer`.

This means:

- case similarity is retrieval-based
- app knowledge is retrieval-based
- question answers are template/deterministic, not open-ended model generation

That is a strong design for reliability, but it is still narrower than a fully generative operational assistant.

## API Surface

The API surface is broad and real.

### Analysis

- `GET /api/analysis-runs`
- `GET /api/analysis-runs/{run_id}`
- `POST /api/ingestion/prometheus-run`
- `POST /api/ingestion/csv-run`
- `POST /api/ingestion/csv-validate`
- `GET /api/prometheus/connections`
- `GET /api/prometheus/label-values`
- `POST /api/prometheus/test-connection`
- `POST /api/prometheus/preview`
- `POST /api/analysis/prometheus`
- `GET /api/overview/summary`
- `POST /api/experiment-analyzer-router/route`

### Findings

- `GET /api/findings`
- `GET /api/findings/{finding_id}`

`GET /api/findings` supports optional `service`, `metric_name`,
`analysis_run_id`, and `window` filters.

### Cases

- `GET /api/cases`
- `GET /api/cases/{case_id}`
- `POST /api/cases/findings/{finding_id}/create`
- `PATCH /api/cases/{case_id}/investigation`
- `PATCH /api/cases/{case_id}/rca`
- `PATCH /api/cases/{case_id}/resolution`

### Behaviors

- `GET /api/behavior-definitions`
- `GET /api/behavior-evaluations`
- `GET /api/behavior-evaluations/evaluate`

### Recommendations

- `GET /api/metric-analyzer-recommendations/metrics`
- `POST /api/metric-analyzer-recommendations/evaluate`
- `POST /api/metric-analyzer-recommendations/chat`

### Knowledge

- `POST /api/assistant/chat`
- `GET /api/assistant/knowledge/status`
- `POST /api/assistant/knowledge/bootstrap`

### Memory

- `POST /api/cases/{case_id}/memory/index`
- `DELETE /api/cases/{case_id}/memory`
- `GET /api/cases/{case_id}/memory/status`
- `GET /api/cases/{case_id}/similar`
- `POST /api/memory/chat`
- `GET /api/memory/health`
- `GET /api/memory/stats`

### Experiments / utilities

- `GET /api/experiments`
- `GET /api/experiments/compare`
- `GET /api/experiments/{experiment_id}`
- `POST /api/testing/reset-operational-data`
- `GET /api/capabilities`
- `GET /api/services`
- `GET /api/services/{service}/metrics`
- `GET /api/signals`
- `GET /api/signals/{signal_id}`
- `GET /api/questions`
- `GET /api/questions/available`
- `POST /api/questions/answer`
- `GET /api/timeseries`

## Tests and Coverage Gaps

### Existing tests

- Config loading
- CSV pipeline
- Prometheus timestamp parsing
- API behavior
- Question routing
- Answer composition
- Analyzer learning outcomes
- Metric analyzer recommendation
- Metric analyzer recommendation chat
- Overview summary and memory statistics endpoint tests
- Direct Prometheus API tests
- Assistant routing tests
- Qdrant vector-store health regression test
- Standalone frontend service tests
- Overview page resilience tests
- Operational Memory page tests
- Prometheus New Analysis page tests
- Standalone import-boundary test

### Main gaps

- No full browser E2E coverage for the standalone workflow
- No Grafana plugin integration suite
- No benchmark or golden-response framework for UI/API
- Limited memory bootstrap and assistant edge-case coverage
- Limited live dependency tests for Postgres, Qdrant, and Prometheus under Docker

## Documentation Review

### Strong parts

- README is substantial and now documents local scripts, standalone app usage, and MCP usage.
- Architecture and rationale docs exist.
- Release process doc exists.
- Diagrams exist.
- Standalone Overview and Prometheus direct-analysis API docs exist.
- A screenshot gallery now covers the standalone Web UI and Grafana plugin.

### Gaps

- No concise first-time-user tour with expected outputs from one canonical sample run.
- Some docs sound more mature than the implementation actually is.
- The repo would benefit from a clearer distinction between:
  - stable core
  - developer tooling
  - experiments
  - preview/plugin workflows
  - local-only visual references

## Open-Source Release Readiness

### What users get today

- explainable metric analysis
- direct Prometheus preview and analysis from the standalone app
- findings generated from analyzer output
- cases with investigation and RCA fields
- memory-backed historical lookup
- an Operational Intelligence-style standalone UI
- a working assistant with deterministic routing and evidence groups
- a Grafana plugin path
- an MCP server with read and write tool modes

### What first-time users can likely understand

Probably enough to say:

> Ops Signals turns time-series data into explainable findings, cases, and searchable operational memory.

That is understandable, and now the standalone UI supports that story much more
directly. The remaining problem is onboarding: a new user still needs a short
golden path showing exactly which command to run, what data appears, and what a
good first analysis looks like.

### What is impressive

- End-to-end pipeline from CSV to findings to cases
- Direct Prometheus analysis without disrupting the Grafana plugin path
- Standalone Operational Intelligence workspace with real API-backed cards/tables
- Behavior intelligence rules
- Qdrant-backed case memory
- Analyzer recommendations
- Grafana plugin support
- MCP exposure for agent workflows

### What still feels unfinished

- No autonomous remediation
- Limited UI onboarding
- Screenshot/story assets exist, but they still need an explicit first-run narrative
- Some heuristic logic where a strict state machine would be better
- Some optional dependency fallbacks that can alter behavior
- No browser E2E or release smoke workflow that exercises the full UI path

## Competitive Positioning

This project is not trying to out-Grafana Grafana or out-Prometheus Prometheus.

### Compared with Grafana

Ops Signals has:

- more opinionated operational reasoning
- findings and case lifecycle objects
- memory-backed historical similarity

Grafana still has:

- much stronger dashboarding
- a much broader ecosystem
- more mature observability workflows

### Compared with Prometheus

Ops Signals has:

- analysis and interpretation layered on top of time-series data

Prometheus still has:

- collection
- querying
- alerting
- storage maturity

### Compared with OpenObserve

Ops Signals is narrower and more opinionated:

- explainable analysis
- cases
- behavior rules
- memory

OpenObserve is broader in observability platform scope.

### Compared with LangGraph-style operational agents

Ops Signals is more deterministic and domain-specific.
That is a strength for trust and reproducibility, but it is less flexible than a fully agentic orchestration stack.

### Compared with Elastic Observability

Elastic is much broader and more mature as an observability platform.
Ops Signals is more focused on explainable analysis and case-based operational memory.

## High-Priority Roadmap

1. Add a first-run guide with sample inputs, expected outputs, and exact screenshots
   generated from a stable demo run.
2. Add browser E2E tests for New Analysis -> Findings -> Case -> Publish Knowledge
   -> Assistant retrieval.
3. Add a release smoke command that validates backend, frontend, Grafana build,
   MCP read/write modes, Postgres, Qdrant, and Prometheus.
4. Add stricter case lifecycle validation and clearer backend state transitions.
5. Add memory reconciliation visibility for DB indexed-case status versus Qdrant
   point availability.
6. Clarify stable vs experimental surfaces in docs and navigation.
7. Improve assistant language so retrieval-backed answers, deterministic templates,
   and unavailable evidence are visually and textually distinct everywhere.

## Low-Priority Roadmap

1. Add more analyzers.
2. Add richer case comparison views.
3. Improve recommendation fitness scoring.
4. Add benchmark datasets and regression baselines.
5. Further polish release and contribution docs.
6. Add plugin-marketplace-style packaging metadata if distribution becomes a goal.
7. Add more visual polish after the release-critical workflow docs and E2E tests land.

## Final Recommendation

This repository is ready for a public open-source early release, provided the
release is framed honestly:

- “working”
- “self-hostable”
- “explainable”
- “early stage”
- “not yet production-ready”

It should not be framed as complete automation or as a finished observability platform.

The recommended release label is:

> Early developer preview: usable locally, API-backed, explainable, and suitable
> for evaluation, but not yet hardened for production operations.
