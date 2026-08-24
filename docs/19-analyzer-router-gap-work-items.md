# Analyzer Router Gap Work Items

This document converts the current analyzer-router gaps into parallelizable bugs and enhancements. Each item is intentionally scoped so different people can work independently without requiring a multi-classifier redesign.

## Current Architecture Baseline

The intended flow is:

1. Normalize sample data.
2. Extract a deterministic time-series profile.
3. Route to analyzers that fit the observed behavior.
4. Execute selected analyzers.
5. Aggregate analyzer signals into operational findings.

This is the correct architecture for the current product. The gaps below are about implementation completeness, consistency, and evidence quality.

## Work Item 1: Design Config-Driven Analyzer Registration Before Migrating Current Analyzers

Type: Enhancement

Title: Add a config-driven analyzer registration path for new analyzers

Description:
The pipeline currently creates analyzer instances through hardcoded Python conditionals. Before changing existing analyzers, introduce a config-driven registration path that can load new analyzers from configuration. The first implementation should add one new analyzer through this path while leaving the current analyzer behavior untouched. After the new path is proven, existing analyzers can be migrated one by one.

Recommendation:
Do not rewrite the current analyzer construction first. Add the new config-driven path side by side, prove it with one new analyzer, and then migrate existing analyzers gradually. This keeps production behavior stable while creating the extension model the project needs.

Proposed Design:

- Add an analyzer implementation registry that maps analyzer IDs to import paths or factory classes.
- Extend analyzer config with execution metadata, for example:

```yaml
analysis:
  analyzer_registry:
    enabled: true
    analyzers:
      new_analyzer_id:
        enabled: true
        class_path: package.module.NewAnalyzer
        router_ids:
          - new_router_id
        params:
          threshold: 1.5
        capabilities:
          id: new_capability
          title: New Capability
          supported_question_ids:
            - what_changed
```

- Keep existing `analysis.analyzers` config working during migration.
- Add validation so a configured analyzer must expose the expected analyzer interface and emit standard `OperationalSignal` records.
- Add execution snapshot fields that show whether an analyzer was loaded from the legacy hardcoded path or the new config-driven path.

What It Achieves:
New analyzers can be added without editing `SignalPipeline._build_analyzers`. Teams can work on analyzers independently by adding implementation files and config entries, while the pipeline enforces a common contract.

Acceptance Criteria:

- A new config-driven analyzer loader exists and is covered by tests.
- At least one new analyzer is registered only through config and runs successfully in the pipeline.
- Current hardcoded analyzers continue to run exactly as before.
- Invalid config fails with a clear error that names the analyzer ID and invalid field.
- Config-driven analyzers can define constructor params, router ID mappings, and capability metadata.
- Analyzer execution snapshots identify whether each analyzer came from `legacy` or `config`.
- Documentation explains the migration plan for moving existing analyzers into config over time.

Proof From Code:

- `SignalPipeline._build_analyzers` currently hardcodes each analyzer construction in `intelligence/pipeline.py`.
- Current analyzer settings live under `analysis.analyzers` in `config/analyzers.yaml`, but the config only provides params for known hardcoded analyzer IDs.
- `SignalPipeline._router_to_pipeline_analyzers` is also hardcoded, so new router-to-pipeline mappings require code changes.
- The analyzer interface already exists through `intelligence/analyzers/base.py`, which makes config-driven loading feasible without changing the signal contract.

Suggested Owners:

- Platform/backend owner: build analyzer loader and validation.
- Analyzer owner: add first config-driven analyzer as a proof point.
- Documentation owner: add migration guide and config examples.
- Test owner: cover valid config, invalid config, and legacy compatibility.

## Work Item 2: Align Router Registry With Executable Pipeline Analyzers

Type: Bug

Title: Prevent router recommendations for analyzers that the pipeline cannot execute

Description:
The router registry contains analyzers that are not implemented in the production pipeline. In `recommended_only` mode, this can create recommendations that do not produce executed analyzer output. The system should either hide unsupported router analyzers from production routing or mark them as unsupported with a clear execution status.

What It Achieves:
Users and downstream learning records can trust that a `RECOMMENDED` analyzer maps to an actual executable analyzer, unless it is explicitly marked as unsupported or roadmap-only.

Acceptance Criteria:

- Production routing does not silently recommend analyzer IDs that have no executable pipeline analyzer.
- Unsupported registry analyzers are either filtered out or returned with `execution_status: unsupported`.
- `executed_analyzers_json` clearly explains every recommended analyzer as `completed`, `skipped`, or `unsupported`.
- Tests cover at least one unsupported analyzer from the registry.
- Existing benchmark tests still pass.

Proof From Code:

- Executable pipeline analyzers are currently hardcoded in `SignalPipeline._build_analyzers`: `baseline_shift`, `ruptures`, `anomaly_zscore`, `trend`, `stumpy`, and `prophet` in `intelligence/pipeline.py`.
- Router registry includes additional analyzers: `river`, `kats`, `darts`, `alibi_detect`, `trend_regression`, `adtk`, and `pyod` in `experiments/analyzer_router/analyzer_registry.yaml`.
- Mapping only covers some router analyzers in `SignalPipeline._router_to_pipeline_analyzers`: `darts -> prophet`, `trend_regression -> trend`, `adtk/pyod -> anomaly_zscore`, while `river`, `kats`, and `alibi_detect` have no executable mapping.

Suggested Owners:

- Router/backend owner: update routing behavior and snapshots.
- Test owner: add snapshot and benchmark coverage.

## Work Item 3: Use The Actual `ruptures` Library In `RupturesAnalyzer`

Type: Bug

Title: Replace custom change-point scan with the installed `ruptures` package

Description:
The project depends on `ruptures`, and the analyzer is named `ruptures`, but the implementation currently uses a custom `numpy` mean-shift loop. Either the analyzer should use the actual `ruptures` package or the name/docs should be changed to avoid implying library-backed behavior.

What It Achieves:
The analyzer behavior matches its name, dependency list, and user expectation. It also unlocks real change-point algorithms and model choices from the `ruptures` library.

Acceptance Criteria:

- `RupturesAnalyzer` imports and uses the `ruptures` package for change-point detection.
- Evidence includes the algorithm/model used, detected breakpoint index or indexes, and score/threshold information.
- Analyzer remains deterministic for benchmark datasets.
- A fallback path is either removed or explicitly labeled as `library: fallback`.
- Tests verify that baseline-shift benchmark scenarios still emit a `ruptures` signal.

Proof From Code:

- `requirements.txt` includes `ruptures>=1.1.9`.
- `intelligence/analyzers/ruptures.py` imports only `numpy` and `pandas`, then manually scans possible split points with `left.mean()` and `right.mean()`.
- The current evidence does not include a library name or algorithm name.

Suggested Owners:

- Analyzer owner: implement `ruptures` integration.
- Benchmark owner: validate expected change-point behavior.

## Work Item 4: Unify Recommendation Profiling And Production Profiling

Type: Bug

Title: Make analyzer recommendation use the same `SeriesProfile` path as production routing

Description:
Production routing uses `TimeSeriesRoutingService` and `extract_series_profile`, which produces `detected_profiles`, `shift_index`, `spikiness`, seasonality, trend, and other router fields. The metric analyzer recommendation service builds a simplified ad hoc profile and manually fills fields like `spikiness = 0.0` and `shift_index = variance / mean`. This can make recommendations inconsistent with production routing.

What It Achieves:
The Analyzer Recommendation page and the production pipeline give consistent advice for the same metric sample.

Acceptance Criteria:

- `MetricAnalyzerRecommendationService` reuses `TimeSeriesRoutingService`, `extract_series_profile`, or a shared profile builder instead of constructing an ad hoc router profile.
- Recommendation output includes the same `detected_profiles` used by production routing.
- `shift_index`, `spikiness`, and `irregular_sampling_percentage` are calculated by shared logic.
- Add a test where recommendation routing and production routing return the same recommendation buckets for the same stored sample.
- Remove or deprecate duplicated profiling helpers when safe.

Proof From Code:

- Production routing calls `TimeSeriesRoutingService().route_normalized(normalized)` in `intelligence/pipeline.py`.
- Recommendation service creates a custom `MetricProfile` in `backend/app/metric_analyzer_recommendations/service.py`.
- Recommendation service then builds a dynamic `RouterProfile` object and hardcodes `spikiness: 0.0`, maps `irregular_sampling_percentage` from missing ratio, and approximates `shift_index` from variance divided by mean.
- Existing tests already assert shared routing for CSV validation and pipeline paths in `tests/test_router_benchmark.py`; recommendation service needs the same kind of alignment test.

Suggested Owners:

- API owner: refactor recommendation service.
- Frontend owner: surface shared profile fields if needed.
- Test owner: add parity tests.

## Work Item 5: Improve Signal Aggregation With Analyzer Agreement And Conflict Semantics

Type: Enhancement

Title: Add explicit agreement/conflict evidence when multiple analyzers detect related behavior

Description:
The pipeline already aggregates analyzer signals into findings, but agreement and conflict between analyzers are mostly implicit in the final summary. The aggregator should explicitly record when analyzers support the same conclusion and when they point to different interpretations, such as abrupt baseline shift versus gradual trend.

What It Achieves:
Findings become more explainable. Multiple weak signals can become a stronger finding when they agree, while conflicting signals can be presented as secondary context instead of noise.

Acceptance Criteria:

- Finding `comparison_json` or another evidence field includes analyzer agreement metadata.
- When `ruptures` and `baseline_shift` agree, the finding records this as supporting evidence.
- When `trend` coexists with structural change, the finding marks trend as secondary context unless evidence supports gradual movement.
- Importance/confidence scoring accounts for analyzer agreement without double-counting duplicate evidence.
- Tests cover at least baseline-shift plus ruptures agreement, anomaly plus trend mixed context, and forecast plus seasonality context.

Proof From Code:

- `FindingAggregator.aggregate` groups signals by service and metric in `intelligence/finding_aggregator.py`.
- `_summary` already treats `ruptures`, `baseline_shift`, `trend`, `anomaly`, and forecast signals differently, but does not emit structured agreement metadata.
- `_structural_change_summary` already phrases baseline shift as supporting structural change, showing the desired behavior exists in text but not as structured evidence.

Suggested Owners:

- Aggregation owner: add agreement/conflict model.
- Scoring owner: update importance scoring if needed.
- Test owner: add focused aggregator tests.

## Work Item 6: Calibrate Router And Analyzer Thresholds With Benchmark Outcomes

Type: Enhancement

Title: Make threshold tuning evidence-driven using benchmarks and resolved learning outcomes

Description:
Thresholds such as `shift_index`, `seasonality_strength`, `trend_strength`, z-score, and baseline percent change determine which analyzers run and which findings are emitted. These thresholds are currently deterministic and testable, but they need systematic calibration against benchmark scenarios and resolved cases.

What It Achieves:
Reduces false positives and false negatives without adding a multi-classifier. The router remains explainable, but thresholds become evidence-backed.

Acceptance Criteria:

- Create a threshold calibration report or script that runs all benchmark scenarios and summarizes misses, false positives, and optional analyzer drift.
- Document the current threshold values and why each one exists.
- Add before/after benchmark output for any threshold changes.
- Learning outcomes from resolved cases can be exported or summarized by analyzer and detected profile.
- Threshold changes require benchmark evidence in the PR description.

Proof From Code:

- Router thresholds are configured in `experiments/analyzer_router/analyzer_registry.yaml`, for example `shift_index >= 0.12`, `seasonality_strength >= 0.42`, and `trend_strength >= 0.18`.
- Pipeline analyzer thresholds are configured in `config/analyzers.yaml`, for example `threshold_percent: 25`, `zscore_threshold: 3.0`, and `min_slope_percent: 10`.
- Benchmark tests already run multiple deterministic scenarios in `tests/test_router_benchmark.py`.

Suggested Owners:

- Benchmark owner: build calibration report.
- Domain owner: review threshold changes.
- Backend owner: wire learning outcome summaries if needed.

## Work Item 7: Close Or Explicitly Scope Advanced Analyzer Gaps

Type: Enhancement

Title: Decide execution strategy for distribution drift and streaming anomaly analyzer gaps

Description:
Advanced scenarios are already documented as gaps in tests. The team should decide whether to implement executable analyzers for distribution drift and streaming anomaly detection, or explicitly keep them as roadmap-only recommendations.

What It Achieves:
The product avoids pretending to support advanced behaviors it cannot execute yet, while preserving a clear path for future analyzer expansion.

Acceptance Criteria:

- For `distribution_drift`, choose one path:
  - implement an executable analyzer, or
  - mark the router analyzer as unsupported/roadmap-only in production.
- For `online_anomaly` or streaming behavior, choose one path:
  - implement a streaming-capable analyzer path, or
  - require `execution_mode=streaming` and exclude it from batch execution.
- Benchmark gap tests are updated only when the product behavior changes.
- Docs explain which advanced analyzers are production-ready versus experimental.

Proof From Code:

- `tests/test_router_benchmark.py` marks `cpu_distribution_drift_v1` and `cpu_online_anomaly_stream_v1` as documented gaps.
- Router registry includes `alibi_detect` for drift and `river` for online anomaly/streaming use.
- Production pipeline has no executable `alibi_detect` or `river` analyzer.

Suggested Owners:

- Product/domain owner: decide roadmap versus implementation.
- Analyzer owner: implement selected advanced analyzer if approved.
- Documentation owner: update production support matrix.

## Work Item 8: Make Optional Library Dependencies Explicit

Type: Enhancement

Title: Clarify optional analyzer library behavior for STUMPY and Prophet

Description:
`STUMPYAnalyzer` and `ProphetAnalyzer` support real libraries when installed, but silently fall back to custom logic when unavailable. This is useful for resilience, but users and developers need clear visibility into which path ran.

What It Achieves:
Analyzer results become easier to debug, reproduce, and compare across environments.

Acceptance Criteria:

- Analyzer evidence always includes `library` and `library_mode`, such as `stumpy/full`, `prophet/full`, or `fallback`.
- Startup or analyzer capability metadata exposes whether optional libraries are available.
- Tests cover fallback evidence when optional libraries are missing.
- Documentation explains which dependencies are required for full analyzer behavior.

Proof From Code:

- `STUMPYAnalyzer` conditionally imports `stumpy` and sets evidence `library` to `stumpy` or `fallback`.
- `ProphetAnalyzer` conditionally imports `Prophet` and sets evidence `library` to `prophet` or `fallback`.
- `requirements.txt` does not include `stumpy` or `prophet`, so fallback behavior is likely in a default install.

Suggested Owners:

- Analyzer owner: update evidence and metadata.
- Docs owner: update analyzer support matrix.

## Parallel Work Plan

The items can run mostly in parallel:

- Person A: Work Item 1, config-driven analyzer registration design.
- Person B: Work Item 2, router executable alignment.
- Person C: Work Item 3, `ruptures` library integration.
- Person D: Work Item 4, recommendation and production profile unification.
- Person E: Work Item 5, aggregation agreement/conflict evidence.
- Person F: Work Item 6, threshold calibration report.
- Person G: Work Item 7, advanced analyzer scope decision.
- Person H: Work Item 8, optional dependency visibility.

Coordination points:

- Work Items 1 and 2 both touch analyzer registration and router-to-pipeline mappings.
- Work Items 2 and 7 both touch router support semantics.
- Work Items 4 and 6 both depend on shared profile fields.
- Work Items 3, 5, and 6 should coordinate on benchmark expectations for change-point behavior.

## Definition Of Done For The Full Gap Set

- Every production recommendation maps to executable behavior or an explicit unsupported status.
- New analyzers can be added through config without editing pipeline construction logic.
- Analyzer names match their actual implementation libraries.
- Recommendation UI and production routing use the same profiling logic.
- Findings contain structured evidence for analyzer agreement or conflict.
- Threshold changes are supported by benchmark or learning-outcome evidence.
- Advanced analyzer gaps are either implemented or clearly scoped as roadmap-only.
