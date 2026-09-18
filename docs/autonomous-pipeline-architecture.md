# Autonomous Pipeline Architecture Boundaries

This note records the boundary decision for separating Interactive Analysis from Autonomous Analysis and the first durable autonomous execution model.

## Component Classification

| Component | Classification | Notes |
| --- | --- | --- |
| `intelligence.pipeline.SignalPipeline` | Interactive only | Continues to support Grafana interactive analysis, REST, CSV, CLI, and existing tests. It owns the current single-series interactive orchestration. |
| `backend.app.autonomous.metric_executor.MetricAnalysisExecutor` | Autonomous only | Executes one logical metric job for autonomous orchestration without calling `SignalPipeline`. |
| `backend.app.models.entities.AutonomousPolicyEntity` | Autonomous control plane | Stores minimal policy configuration for current UI needs. |
| `backend.app.models.entities.AutonomousPolicyRunEntity` | Autonomous control plane | Authoritative record of one autonomous policy execution. |
| `backend.app.models.entities.AutonomousMetricJobEntity` | Autonomous control plane | Authoritative record of one planned/skipped/executed metric job, optionally linked to `analysis_runs`. |
| `backend.app.autonomous.repository` | Autonomous control plane | Repository boundary for policy-run and metric-job state changes. |
| `backend.app.autonomous.services.MetricDiscoveryService` | Autonomous only | Discovers metric metadata for autonomous scope planning with push-down label scoping, anti-starvation dynamic quota sampling, and truncation visibility (`series_available`, `starved_metrics`). |
| `backend.app.autonomous.services.MetricClassificationService` | Autonomous only | Maps monitoring intent to metric concepts and Prometheus metrics. |
| `backend.app.autonomous.services.MetricPlanBuilder` | Autonomous only | Builds autonomous metric plans and planned request payloads. |
| `backend.app.autonomous.execution.execute_autonomous_plan_once` | Autonomous only | Coordinates a preview plan execution once; this is not a repeating scheduler. |
| `TimeSeriesRoutingService` / `UniversalTimeSeriesRouter` | Shared domain component | Reusable for routing decisions in both pipelines. |
| Analyzer implementations | Shared domain component | Reusable technical detectors; neither pipeline should own analyzer logic. |
| `FindingAggregator` | Shared with caution | Currently still single-series oriented and used for technical metric findings. Autonomous cross-metric narrative/dedup should happen later in separate services. |
| `BehaviorIntelligenceService` | Shared domain component | Can evaluate signal facts for one run; cross-metric autonomous behavior still needs higher-level orchestration. |
| `PostgresStore` | Shared persistence component | Current persistence implementation. Repository adapters should be extracted gradually. |
| Case API functions | Requires extraction | Case creation/update logic currently lives in FastAPI handlers and should become a service before scheduler use. |
| Memory API/indexer | Requires extraction | Qdrant primitives are reusable, but promotion policy should be autonomous-specific. |
| Grafana plugin autonomous overview | Requires replacement | Current counts are backfilled from existing APIs and are not authoritative autonomous policy-run counts. |

## Current Boundary

Interactive Analysis:

```text
Grafana / REST / CSV / CLI
  -> SignalPipeline
  -> PostgresStore
```

Autonomous Analysis:

```text
Policy / draft request
  -> MetricDiscoveryService
  -> MetricClassificationService
  -> MetricPlanBuilder
  -> AutonomousPolicyRun
  -> AutonomousMetricJob rows
  -> MetricAnalysisExecutor
  -> PostgresStore / existing technical analysis persistence
  -> analysis_runs
  -> AutonomousMetricJob.analysis_run_id
```

The autonomous path shares low-level router/analyzer/finding/persistence components, but it does not call `SignalPipeline` as its orchestration engine.

## Durable Autonomous Execution State

Autonomous execution state is stored outside `SignalPipeline`:

```text
AutonomousPolicy
  -> AutonomousPolicyRun
  -> AutonomousMetricJob
  -> MetricAnalysisExecutor
  -> analysis_runs
```

`analysis_runs` remains independently usable by Interactive Analysis. The relationship is one-way and optional: an autonomous job can reference an analysis run, but an analysis run does not require an autonomous job.

`AutonomousPolicyRun` is the authoritative control-plane summary for autonomous execution counts:

- `metrics_discovered`
- `metrics_selected`
- `jobs_planned`
- `jobs_completed`
- `jobs_skipped`
- `jobs_failed`
- `findings_created`

`AutonomousMetricJob` stores the metric identity, PromQL, category/concept, selection reason, skip reason, timing, failure metadata, and optional `analysis_run_id`.

Current history APIs:

- `GET /api/autonomous/policy-runs`
- `GET /api/autonomous/policy-runs/{policy_run_id}`
- `GET /api/autonomous/policy-runs/{policy_run_id}/jobs`

The autonomous overview UI can now migrate from legacy backfilled counts to these native autonomous records.

## Still Missing For Full Target Architecture

- Finding occurrence repository and deterministic fingerprinting.
- Cross-metric correlation service.
- Significance evaluation service.
- Operational narrative service.
- Autonomous case orchestrator.
- Memory promotion service.
- Publication projection builders.
- Idempotency keys and retry state.
- Outbox/reconciliation for case and vector-memory promotion.

## Rationale

`SignalPipeline` embeds single-series and interactive assumptions: one normalized time series, immediate analyzer execution, technical finding aggregation, optional question-answer generation, and persistence ordering inside one class. Autonomous analysis needs separate orchestration for multi-metric planning, screening, execution, deduplication, correlation, case decisions, and memory promotion.

The first safe step was to preserve `SignalPipeline` unchanged and introduce autonomous-specific orchestration seams that share only explicit lower-level components. The next step adds autonomous-native execution state so policy runs and jobs can be audited without inferring behavior from interactive `analysis_runs`.
