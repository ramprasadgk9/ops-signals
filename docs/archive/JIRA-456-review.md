# JIRA-456 Analyzer Stabilization Review

Date: 2026-09-04

Scope: analyzer execution, routing, analyzer labs, configuration, persistence, frontend result display, and tests. This updates the original static review with stabilization fixes already landed through commit `e9c2172` (`Stabilize analyzer recommendation execution`).

## 1. Architecture Map

Analyzer execution currently flows through these layers:

1. Input normalization
   - CSV/API input is normalized by `normalize_timeseries(...)`, then passed to `SignalPipeline.run_normalized(...)`.
   - Evidence: `intelligence/pipeline.py:67-80`, `backend/app/services/timeseries_routing_service.py:28-40`.

2. Router profiling and analyzer selection
   - `TimeSeriesRoutingService.route_normalized(...)` profiles the normalized dataframe and calls `UniversalTimeSeriesRouter.recommend_analyzers_for_profile(...)`.
   - Evidence: `backend/app/services/timeseries_routing_service.py:36-51`, `experiments/analyzer_router/router.py:78-86`.

3. Router scoring
   - Analyzer capability definitions come from `experiments/analyzer_router/analyzer_registry.yaml` plus promoted custom analyzer YAML.
   - Suitability is computed from base score, scoring rules, and behavioral profile match/mismatch caps.
   - Evidence: `experiments/analyzer_router/router.py:102-115`, `experiments/analyzer_router/router.py:131-148`, `experiments/analyzer_router/router.py:167-174`.

4. Router-to-runtime selection
   - Default config now uses `selection_mode: recommended_threshold`.
   - The pipeline selects only `RECOMMENDED` router decisions at or above the configured threshold, caps execution count, and excludes optional analyzers unless configured otherwise.
   - Evidence: `config/analyzers.yaml:1-9`, `intelligence/config.py:36-50`, `intelligence/pipeline.py:312-360`.

5. Router-to-runtime mapping
   - Runtime aliasing is intentionally narrow. `trend_regression` maps to executable `trend`; unsupported custom/config-only analyzers are shown as unavailable instead of silently executing a different implementation.
   - Evidence: `intelligence/pipeline.py:362-453`.

6. Analyzer construction
   - Runtime analyzers are constructed from `config/analyzers.yaml` params and nested `implementation` / `finding_rules`.
   - Evidence: `intelligence/pipeline.py:197-299`, `intelligence/pipeline.py:462-470`.

7. Analyzer execution
   - Each analyzer receives the same normalized dataframe and returns `OperationalSignal` objects.
   - Analyzer failures are isolated per analyzer. One failed analyzer is recorded and does not prevent healthy analyzers from running.
   - Evidence: `intelligence/analyzers/base.py:11-23`, `intelligence/pipeline.py:112-189`, `backend/app/autonomous/metric_executor.py:107-140`.

8. Signal scoring and finding aggregation
   - Signals are scored, persisted, and aggregated into findings.
   - Evidence: `intelligence/pipeline.py:131-147`, `intelligence/finding_aggregator.py:25-78`.

9. Persistence
   - Analysis runs are created as `running`, then finalized as `completed`, `completed_with_errors`, or `failed`.
   - Routing decisions and analyzer execution snapshots are stored in the learning snapshot.
   - Evidence: `intelligence/pipeline.py:529-565`, `intelligence/storage/postgres_store.py:41-113`, `intelligence/storage/postgres_store.py:227-233`.

10. UI result visibility
   - New Analysis now shows which analyzers were executed, skipped, failed, or unavailable.
   - Evidence: `frontend/src/pages/ValidateDataPage.tsx:192`, `frontend/src/pages/ValidateDataPage.tsx:950-956`, `backend/app/api/direct_prometheus.py`, `backend/app/models/prometheus.py`.

11. Labs and Add Analyzer workbench
   - Labs create controlled analyzer scenarios and save config suggestions.
   - Add Analyzer creates DB drafts, validates routing, promotes custom recommendation-only YAML, and can create adapter stubs for backend support.
   - Evidence: `backend/app/api/analyzer_labs.py:380-484`, `backend/app/api/analyzer_labs.py:568-640`, `backend/app/api/analyzer_labs.py:643-698`, `backend/app/api/analyzer_labs.py:782-816`.

## 2. Stabilization Fixes Landed

### RESOLVED HIGH: One analyzer exception can fail the entire run

Status: Fixed in commit `e9c2172`.

Previous behavior:
`SignalPipeline.run_normalized(...)` called analyzers without per-analyzer failure isolation. One bad analyzer could make the full run fail.

Current behavior:
`_run_analyzers(...)` catches analyzer-specific exceptions, records the failed analyzer and error message, continues other analyzers, and finalizes the run as `completed_with_errors` when partial success occurs.

Evidence:
- `intelligence/pipeline.py:112-189`
- `backend/app/autonomous/metric_executor.py:107-140`
- `tests/test_csv_pipeline.py:173-248`

Remaining risk:
Need API-level tests with a real analyzer dependency failure, not only a monkeypatched analyzer.

### RESOLVED HIGH: Analysis runs are created as completed before analyzer execution

Status: Fixed in commit `e9c2172`.

Previous behavior:
Runs were persisted as `completed` before routing, analyzer execution, finding aggregation, and failure handling completed.

Current behavior:
Runs are created as `running`; final status is set after analyzer execution. Full success becomes `completed`, partial analyzer failure becomes `completed_with_errors`, and total selected-analyzer failure becomes `failed`.

Evidence:
- `intelligence/pipeline.py:529-565`
- `tests/test_csv_pipeline.py:236-243`

Remaining risk:
Autonomous scheduling and dashboard state transitions should still be verified with an integration test against Postgres.

### RESOLVED HIGH: Router can recommend one analyzer while pipeline executes another analyzer

Status: Fixed in commit `e9c2172`.

Previous behavior:
Router IDs could silently execute different libraries, for example `darts` via `prophet`, `kats` via multiple unrelated analyzers, and `pyod` via z-score.

Current behavior:
The pipeline runs recommended analyzers using exact/safe runtime IDs only. The only alias retained is `trend_regression -> trend`. Recommendation-only or missing-runtime analyzers are displayed as skipped/unavailable instead of being substituted.

Evidence:
- `intelligence/pipeline.py:312-360`
- `intelligence/pipeline.py:362-453`
- `config/analyzers.yaml:1-9`
- `tests/test_csv_pipeline.py:122-170`

Remaining risk:
The router can still rank analyzers that do not have executable backend implementations. This is acceptable only when the UI clearly labels them as recommendation-only or execution unavailable.

## 3. Remaining Top Bug Candidates

### 1. HIGH: Custom recommendation-only analyzers can appear routable but cannot execute

Evidence:
- `config/custom_analyzers.yaml:1-42`
- `backend/app/analyzers/custom/statsforecast_forecast.py:37-56`
- `backend/app/api/admin_analyzers.py:116-119`
- `backend/app/api/analyzer_labs.py:717-731`

Current behavior:
`statsforecast_forecast` can be promoted to custom analyzer YAML and routed as a recommendation-only analyzer. Backend adapter stubs can be created, but runtime mapping remains `not_implemented` until manually wired.

Why it may be incorrect:
This is safe only if every UI/API surface keeps it clearly marked as recommendation-only and prevents stub output from being treated as real execution.

Minimal scenario:
Promote a custom analyzer, create backend support, then run an execution test or recommendation flow before the adapter is implemented.

Expected behavior:
Recommendation-only custom analyzers should never emit real signals/findings until implementation status is complete and runtime mapping is executable.

Recommended test:
Promoted custom analyzer with `implementation.status: pending` must never produce persisted signals/findings and must not show as execution-ready.

### 2. HIGH: Analyzer-specific finding rules can be bypassed in mixed-signal groups

Evidence:
- `intelligence/finding_aggregator.py:40-46`
- `intelligence/finding_aggregator.py:80-114`
- `tests/test_finding_aggregator_precedence.py:82-213`

Current behavior:
The aggregator suppresses PyOD/STUMPY/Prophet/Z-score findings only when the group contains only that analyzer family. If a non-matching PyOD signal is grouped with a trend/baseline signal, the PyOD signal can still be included in a finding.

Why it may be incorrect:
`finding_rule_matched: false` should probably mean “this signal must not contribute to a finding,” not merely “suppress analyzer-only findings.”

Minimal scenario:
One trend signal plus one PyOD signal with `finding_rule_matched: false` in the same metric/service group.

Expected behavior:
The non-matching analyzer signal should be filtered out or excluded from finding evidence.

Recommended test:
Aggregate `[trend_signal, pyod_signal(finding_rule_matched=False)]` and assert the finding does not include the PyOD signal ID/evidence.

### 3. HIGH: PyOD `finding_rules.window` is recorded but not enforced

Evidence:
- `config/analyzers.yaml:63-66`
- `intelligence/analyzers/pyod_outlier.py:24`
- `intelligence/analyzers/pyod_outlier.py:145-153`

Current behavior:
The PyOD finding rule stores `window: 15m`, but `finding_rule_matched` checks grouped point count and confidence. The count window itself is not applied as a sliding or bounded 15-minute window.

Why it may be incorrect:
The stated rule “more than 8 high-confidence outliers in 15 minutes” can become “more than 8 outliers in whatever group was formed by `grouping_gap`.”

Minimal scenario:
Eight outliers spread over one hour but connected by `grouping_gap`.

Expected behavior:
Rule should match only if the required outlier count occurs inside the configured time window.

Recommended test:
Create 8 outliers outside 15 minutes and assert no finding; create 8 inside 15 minutes and assert finding.

### 4. HIGH: Z-score analyzer does not clean NaN/Inf before statistics

Evidence:
- `intelligence/analyzers/anomaly_zscore.py:49-57`
- Other analyzers clean values first: `intelligence/analyzers/trend.py:51-53`, `intelligence/analyzers/prophet.py:69-72`, `intelligence/analyzers/pyod_outlier.py:78-80`

Current behavior:
Z-score sorts the dataframe and calculates mean/std directly on `value`, without coercing numeric values or replacing Inf.

Why it may be incorrect:
NaN/Inf can make mean/std invalid, causing no anomalies or malformed evidence without an explicit quality failure.

Minimal scenario:
Values `[1, 1, 1, 100, inf]`.

Expected behavior:
Invalid values should be dropped or rejected consistently before z-score computation.

Recommended test:
Run z-score with NaN/Inf values and assert deterministic invalid-value handling plus no NaN/Inf in signal evidence.

### 5. HIGH: Feature profiling separates valid values from valid timestamps, which can misalign evidence

Evidence:
- `experiments/analyzer_router/feature_extractor.py:77-82`
- `experiments/analyzer_router/feature_extractor.py:124-158`

Current behavior:
Values are cleaned independently from timestamps. Rows with invalid values can still affect timestamp regularity; rows with invalid timestamps can still affect numeric features.

Why it may be incorrect:
Routing features can describe different subsets of the original series. Missing/invalid timestamp rows can shift detected profiles without being tied to the same samples used for numeric analysis.

Minimal scenario:
Dataset where invalid timestamps occur exactly at spike/change rows.

Expected behavior:
Feature extraction should compute profile features from row-wise valid timestamp/value pairs, with separate counts for dropped rows.

Recommended test:
Create rows with valid values but invalid timestamps and assert profile counts, duration, regularity, and detected profiles remain internally consistent.

### 6. MEDIUM: Interpolated sample count reports remaining missing values, not interpolated values

Evidence:
- `experiments/analyzer_router/feature_extractor.py:61-74`
- `experiments/analyzer_router/feature_extractor.py:134-135`

Current behavior:
After interpolation, `interpolated_sample_count` is set to `df[value_column].isna().sum()`. That is the number of remaining missing values, not the number filled.

Why it may be incorrect:
Data-quality reporting and router evidence can say 0 interpolated samples after interpolation actually filled gaps.

Minimal scenario:
Series with two missing values within the interpolation limit.

Expected behavior:
`interpolated_sample_count` should equal filled values, while remaining missing values should be a separate metric.

Recommended test:
Profile `[1, NaN, 3]` with interpolation enabled and assert interpolated count is 1.

### 7. MEDIUM: Prophet confidence decreases as deviation increases

Evidence:
- `intelligence/analyzers/prophet.py:83-85`
- `intelligence/analyzers/prophet.py:105-113`
- `tests/test_prophet_analyzer.py:23-54`

Current behavior:
Prophet severity increases when relative error is high, but confidence is computed as `1.0 - relative_error`.

Why it may be incorrect:
For finding confidence, a larger forecast miss should usually increase confidence that the signal is meaningful. Current semantics made user interpretation difficult during lab testing.

Minimal scenario:
Relative error 0.10 gives confidence 0.90; relative error 0.80 gives confidence 0.20.

Expected behavior:
Either confidence should increase with deviation strength, or the field should be renamed/explicitly documented as model-fit confidence and not used for finding confidence.

Recommended test:
Two forecast miss scenarios with increasing relative error should assert intended confidence monotonicity.

### 8. MEDIUM: Duplicate timestamps can make regular sampling appear valid

Evidence:
- `experiments/analyzer_router/feature_extractor.py:94-101`
- `experiments/analyzer_router/eligibility.py:17-59`

Current behavior:
Duplicate timestamps are counted, but eligibility does not reject or penalize duplicates. If duplicate diffs dominate, median interval can be 0 and regularity math becomes unreliable.

Recommended test:
Profile a dataset with duplicate timestamps and assert analyzers requiring regular sampling are rejected or warned.

### 9. MEDIUM: Baseline/ruptures change index can refer to cleaned series, not original rows

Evidence:
- `intelligence/analyzers/baseline_shift.py:52-55`
- `intelligence/analyzers/ruptures.py:101-123`

Current behavior:
Rows with invalid values are dropped before detection. The returned change-point index is then based on the cleaned array, which can differ from the original row index.

Recommended test:
Insert missing values before a known change point and assert reported index/timestamp still maps to the original sample.

### 10. MEDIUM: STUMPY fallback ignores `motif_count`

Evidence:
- `intelligence/analyzers/stumpy.py:37-44`
- `intelligence/analyzers/stumpy.py:132-169`

Current behavior:
Fallback motif detection returns one best pair even when `motif_count` is greater than 1.

Recommended test:
Generate three repeated motifs, run fallback path, and assert either multiple motifs are returned or the limitation is explicit.

## Additional Bug Candidates

### MEDIUM: STUMPY installed-library exceptions are swallowed

Evidence:
- `intelligence/analyzers/stumpy.py:132-144`

Current behavior:
If STUMPY is installed but raises during `stump(...)`, the code returns `None` and does not use the fallback.

Recommended test:
Monkeypatch STUMPY to raise and assert the analyzer records a failure or falls back deterministically.

### MEDIUM: `RupturesAnalyzer` ignores several constructor/config knobs

Evidence:
- `intelligence/analyzers/ruptures.py:70-76`
- `config/analyzers.yaml:31-36`

Current behavior:
The standalone `RupturesAnalyzer` hardcodes algorithm/model/jump/n_bkps even though related config supports these values through the baseline-shift path.

Recommended test:
Instantiate `RupturesAnalyzer` with non-default algorithm parameters and assert they are propagated or rejected.

### LOW: Capability save deletes global capabilities per run

Evidence:
- `intelligence/storage/postgres_store.py:227-233`

Current behavior:
`save_capabilities(...)` deletes all rows before saving the current analyzer set.

Recommended test:
Run with a subset of analyzers and assert expected capability inventory is not unintentionally reduced.

## 4. Analyzer-by-Analyzer Test-Gap Table

| Analyzer | Implemented Runtime | Key Config Evidence | Current Tests Seen | Highest Test Gap |
| --- | --- | --- | --- | --- |
| `ruptures` | Yes | `config/analyzers.yaml:11-12`, `intelligence/pipeline.py:215-223` | CSV pipeline routing/execution tests | Config propagation and dirty-data index mapping |
| `baseline_shift` | Yes, legacy/custom ruptures-backed baseline logic | `intelligence/pipeline.py:200-213` | Aggregator precedence tests cover baseline narrative | Missing dirty-data index mapping, duplicate timestamp, off-edge change-point tests |
| `stumpy` | Yes, optional STUMPY plus fallback | `config/analyzers.yaml:13-23`, `intelligence/analyzers/stumpy.py:29-169` | `tests/test_stumpy_analyzer.py`, aggregator rule tests | Installed-library exception handling, multi-motif correctness, irregular timestamps |
| `prophet` | Yes, optional Prophet plus fallback | `config/analyzers.yaml:24-28`, `intelligence/analyzers/prophet.py:27-162` | `tests/test_prophet_analyzer.py` | Confidence semantics and forecast-vs-actual time alignment |
| `anomaly_zscore` | Yes, pandas/statistics | `config/analyzers.yaml:44-53`, `intelligence/analyzers/anomaly_zscore.py:10-108` | `tests/test_anomaly_zscore_analyzer.py` | NaN/Inf coercion, constant series, grouped false positives |
| `pyod_outlier` | Yes, optional PyOD plus fallback | `config/analyzers.yaml:54-66`, `intelligence/analyzers/pyod_outlier.py:27-157` | `tests/test_pyod_outlier_analyzer.py` | `finding_rules.window` enforcement, contamination edge cases, missing dependency behavior |
| `trend` / router `trend_regression` | Yes, numpy/stats-style regression | `config/analyzers.yaml:67-73`, `intelligence/pipeline.py:451-453`, `intelligence/analyzers/trend.py:12-118` | `tests/test_trend_analyzer.py`, CSV pipeline routing tests | Constant series, NaN/Inf, slope percent denominator near zero |
| `adtk` router | No direct ADTK runtime | `intelligence/pipeline.py:451-453` | Router tests only | Must assert displayed ADTK remains recommendation-only unless backend runtime is added |
| `pyod` router | No direct generic PyOD runtime | `intelligence/pipeline.py:451-453` | Router tests only | Must prevent library/runtime misattribution |
| `kats` router | No Kats runtime | `intelligence/pipeline.py:451-453` | Router tests only | Must ensure recommended Kats is skipped/unavailable, not silently substituted |
| `darts` router | No Darts runtime | `intelligence/pipeline.py:451-453` | Router tests only | Must ensure recommended Darts is skipped/unavailable, not silently substituted |
| custom `statsforecast_forecast` | Stub only | `config/custom_analyzers.yaml:1-42`, `backend/app/analyzers/custom/statsforecast_forecast.py:37-56` | Add Analyzer lifecycle tests | Must assert pending implementation cannot emit real signals/findings |

## 5. Recommended Common Analyzer Contract Test Suite

Every analyzer runtime should pass the same contract cases:

1. Empty dataframe returns `[]` or a typed rejection, not an exception.
2. Short series below `min_samples` returns no signals and records a clear skip reason when possible.
3. Constant series returns no false positive findings.
4. NaN/Inf values are either dropped or rejected consistently; no NaN/Inf appears in persisted signal evidence.
5. Duplicate timestamps are rejected or normalized before analyzers that require regular sampling.
6. Irregular timestamps are rejected for regular-only analyzers and accepted for analyzers that support irregular series.
7. Timestamps are sorted before analysis, and evidence indexes map back to original timestamps.
8. Config overrides change analyzer behavior in a measurable way.
9. Analyzer failure is isolated and does not fail unrelated analyzers.
10. `finding_rule_matched: false` signals do not create or contribute to findings.
11. Confidence fields have analyzer-specific monotonicity tests and documented meaning.
12. Output signals always contain valid `signal_type`, `analyzer_id`, `metric_name`, time range, severity, confidence, summary, and evidence.

## 6. Suggested First 10 Regression Tests

1. [done] Pipeline partial failure: one analyzer raises, another succeeds.
2. [done] Analysis run status transitions to `completed_with_errors` when one selected analyzer fails.
3. [done] Router `darts`, `kats`, and `pyod` cannot silently execute substitute implementations.
4. [done] `recommended_threshold` runs only top `RECOMMENDED` analyzers above `min_score`, capped by `max_analyzers`.
5. [done] New Analysis response/UI exposes executed, skipped, failed, and unavailable analyzer execution states.
6. [remaining] Custom `statsforecast_forecast` pending implementation is recommendation-only and never persists signals.
7. [remaining] PyOD: 8 outliers outside 15 minutes should not match `finding_rules.window`.
8. [remaining] PyOD: 8 outliers inside 15 minutes should match `finding_rules.window`.
9. [remaining] Aggregator: non-matching PyOD/STUMPY/Prophet/Z-score signal mixed with trend/baseline is excluded from finding evidence.
10. [remaining] Z-score: NaN/Inf values are cleaned or rejected without malformed evidence.

## 7. Bugs To Confirm With Existing Analyzer Labs

| Lab | Bug to Confirm | Why Lab Helps |
| --- | --- | --- |
| PyOD Outlier Lab | `finding_rules.window` not enforced | Lab already generates expected outlier timestamps and can vary outlier spacing |
| PyOD Outlier Lab | Contamination vs generated outlier count mismatch | Lab already shows expected vs detected outlier counts |
| Ruptures Change Point Lab | Missing values before change point shift detected index | Lab can inject missing samples before the known change point |
| STUMPY Motif Lab | `motif_count > 1` only produces one fallback match | Lab already generates multiple motif windows |
| STUMPY Motif Lab | Installed STUMPY error path silently returns no signal | Lab can run with window sizes near boundaries |
| Prophet Forecast Lab | Confidence decreases as relative error increases | Lab can vary future shock/deviation while keeping sample count fixed |
| Z-Score Anomaly Lab | NaN/Inf can suppress or corrupt anomaly detection | Lab can inject invalid values into otherwise obvious spikes |
| Trend Lab | Near-zero baseline makes slope percent unstable | Lab can generate tiny baseline values with small absolute slope |

## 8. Areas Requiring Synthetic Execution

Static review is insufficient for these:

1. Optional library behavior: PyOD, STUMPY, Prophet, StatsForecast, Darts, Kats, and ADTK behavior depends on installed versions and import availability.
2. Boundary windows: exact grouping behavior around `15m`, `5m`, and sample-count thresholds needs timestamped synthetic data.
3. Confidence semantics: monotonicity must be checked across controlled positive/negative magnitudes.
4. Router profile extraction: detected profiles depend on generated values, interpolation, sampling regularity, and timestamp quality.
5. Persistence correctness: partial failures and duplicate findings need a real test DB or transaction-backed integration tests.
6. Frontend lab truth tables: expected-vs-actual labels need API-backed execution to avoid displaying synthetic truth as real analyzer success.
7. Recommendation-threshold behavior: multi-analyzer execution should be validated on positive and negative lab datasets where more than one analyzer scores above `0.80`.

## Summary Recommendation

The first stabilization checkpoint is complete: analyzer failures are isolated, run status is truthful, and router recommendation no longer silently substitutes unrelated runtime analyzers. The next stabilization work should focus on correctness of finding creation: PyOD time-window rules, aggregator filtering of non-matching signals, Z-score invalid-value handling, and synthetic lab regression tests for false positives and false negatives.
