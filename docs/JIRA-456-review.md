# JIRA-456 Analyzer Stabilization Review

Date: 2026-08-30

Scope: static repository review of analyzer execution, routing, labs, configuration, persistence, and tests. No source changes were made as part of this review.

## 1. Architecture Map

Analyzer execution currently flows through these layers:

1. Input normalization
   - CSV/API input is normalized by `normalize_timeseries(...)`, then passed to `SignalPipeline.run_normalized(...)`.
   - Evidence: `intelligence/pipeline.py:67-74`, `backend/app/services/timeseries_routing_service.py:28-40`.

2. Router profiling and analyzer selection
   - `TimeSeriesRoutingService.route_normalized(...)` profiles the normalized dataframe and calls `UniversalTimeSeriesRouter.recommend_analyzers_for_profile(...)`.
   - Evidence: `backend/app/services/timeseries_routing_service.py:36-51`, `experiments/analyzer_router/router.py:78-86`.

3. Router scoring
   - Analyzer capability definitions come from `experiments/analyzer_router/analyzer_registry.yaml` plus custom analyzer YAML.
   - Suitability is computed from base score, scoring rules, and behavioral profile match/mismatch caps.
   - Evidence: `experiments/analyzer_router/router.py:102-115`, `experiments/analyzer_router/router.py:131-148`, `experiments/analyzer_router/router.py:167-174`.

4. Router-to-runtime mapping
   - Pipeline maps router analyzer IDs to executable pipeline analyzer IDs.
   - Evidence: `intelligence/pipeline.py:263-283`, `intelligence/pipeline.py:346-358`.

5. Analyzer construction
   - Runtime analyzers are constructed from `config/analyzers.yaml` params and nested `implementation` / `finding_rules`.
   - Evidence: `intelligence/pipeline.py:158-239`, `intelligence/pipeline.py:360-411`.

6. Analyzer execution
   - Each analyzer receives the same normalized dataframe and returns `OperationalSignal` objects.
   - Evidence: `intelligence/analyzers/base.py:11-23`, `intelligence/pipeline.py:105-110`.

7. Signal scoring and finding aggregation
   - Signals are scored, persisted, and aggregated into findings.
   - Evidence: `intelligence/pipeline.py:116-130`, `intelligence/finding_aggregator.py:25-78`.

8. Persistence
   - Analysis run, normalized points, signals, findings, capabilities, and learning snapshots are persisted through the store.
   - Evidence: `intelligence/pipeline.py:79-103`, `intelligence/storage/postgres_store.py:41-113`, `intelligence/storage/postgres_store.py:227-233`.

9. Labs and Add Analyzer workbench
   - Labs create controlled analyzer scenarios and save config suggestions.
   - Add Analyzer creates DB drafts, validates routing, promotes custom recommendation-only YAML, and can create adapter stubs.
   - Evidence: `backend/app/api/analyzer_labs.py:380-484`, `backend/app/api/analyzer_labs.py:568-640`, `backend/app/api/analyzer_labs.py:643-698`, `backend/app/api/analyzer_labs.py:782-816`.

## 2. Top 10 Highest-Risk Bug Candidates

### 1. HIGH: One analyzer exception can fail the entire run

Evidence:
- `intelligence/pipeline.py:105-110`
- `backend/app/api/ingestion.py:338-343`
- `intelligence/analyzers/pyod_outlier.py:44-46`

Current behavior:
`SignalPipeline.run_normalized(...)` calls each analyzer without a per-analyzer `try/except`. If one analyzer raises, the whole pipeline exits and the API returns a 500.

Why it may be incorrect:
A single bad analyzer config, unsupported detector, dependency issue, or data edge case can prevent other healthy analyzers from running and can turn a partial analysis into a total failure.

Minimal scenario:
Set `pyod_outlier.implementation.detector_type: unknown` and run with `selection_mode: all`.

Expected behavior:
The PyOD execution should be marked failed, other analyzers should still run, and the run should record partial success/failure metadata.

Recommended test:
Pipeline contract test with two analyzers: one raises, one returns a signal. Assert API/run result contains the successful signal and a failed execution record for the broken analyzer.

### 2. HIGH: Analysis runs are created as completed before analyzer execution

Evidence:
- `intelligence/pipeline.py:79`
- `intelligence/pipeline.py:427-448`
- `backend/app/autonomous/metric_executor.py:150-155`

Current behavior:
`_create_analysis_run(...)` writes `status: "completed"` before routing, analyzer construction, analyzer execution, finding aggregation, or persistence has completed.

Why it may be incorrect:
If routing or analyzer execution fails afterward, the stored run can still look completed. This hides operational failures and can confuse dashboards.

Minimal scenario:
Run a dataset that triggers an analyzer constructor or runtime exception after `_create_analysis_run(...)`.

Expected behavior:
Run status should start as `running` or `created`, then transition to `completed`, `completed_with_errors`, or `failed`.

Recommended test:
Force an analyzer exception after run creation and assert persisted `analysis_runs.status` is not `completed`.

### 3. HIGH: Router can recommend one analyzer while pipeline executes another analyzer

Evidence:
- `intelligence/pipeline.py:346-358`
- `intelligence/pipeline.py:290-298`
- `config/analyzers.yaml:29-43`

Current behavior:
Router ID `ruptures` runs `baseline_shift`; `darts` runs `prophet`; `kats` runs several unrelated analyzers; `pyod` runs `anomaly_zscore`.

Why it may be incorrect:
User-facing routing says one library/analyzer was selected, but execution may use a different implementation. This can make evidence, confidence, and finding attribution misleading.

Minimal scenario:
Route a profile where `darts` is recommended. The pipeline can execute `prophet` instead of Darts.

Expected behavior:
If Darts/Kats/PyOD are not implemented, they should be `config_only` / `not_executable`, not silently substituted with other analyzers.

Recommended test:
For each router ID, assert executed runtime implementation matches declared library, or assert it is skipped with an explicit non-executable reason.

### 4. HIGH: Custom recommendation-only analyzers can appear routable but cannot execute

Evidence:
- `config/custom_analyzers.yaml:1-42`
- `backend/app/analyzers/custom/statsforecast_forecast.py:37-56`
- `backend/app/api/admin_analyzers.py:116-119`
- `backend/app/api/analyzer_labs.py:717-731`

Current behavior:
`statsforecast_forecast` is routable in custom YAML and has a generated adapter stub, but runtime mapping is `not_implemented` and `analyze(...)` returns an empty list.

Why it may be incorrect:
This is acceptable as recommendation-only, but unsafe if any UI/API path labels it executable or treats empty stub execution as success.

Minimal scenario:
Promote a custom analyzer, create backend support, then run an execution test or recommendation flow.

Expected behavior:
Recommendation-only custom analyzers should be clearly marked as unable to emit signals/findings until implementation status is complete and runtime mapping is executable.

Recommended test:
Promoted custom analyzer with `implementation.status: pending` must never produce persisted signals/findings and must not show as execution-ready.

### 5. HIGH: Analyzer-specific finding rules can be bypassed in mixed-signal groups

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
The non-matching PyOD signal should be filtered out or excluded from finding evidence.

Recommended test:
Aggregate `[trend_signal, pyod_signal(finding_rule_matched=False)]` and assert the finding does not include the PyOD signal ID/evidence.

### 6. HIGH: PyOD `finding_rules.window` is recorded but not enforced

Evidence:
- `config/analyzers.yaml:63-66`
- `intelligence/analyzers/pyod_outlier.py:24`
- `intelligence/analyzers/pyod_outlier.py:145-153`

Current behavior:
The PyOD finding rule stores `window: 15m`, but `finding_rule_matched` only checks group point count and confidence. The count window itself is not applied as a sliding or bounded 15-minute window.

Why it may be incorrect:
The stated rule “more than 8 high-confidence outliers in 15 minutes” can become “more than 8 outliers in whatever group was formed by `grouping_gap`.”

Minimal scenario:
Eight outliers spread over one hour but connected by `grouping_gap`.

Expected behavior:
Rule should match only if the required outlier count occurs inside the configured time window.

Recommended test:
Create 8 outliers outside 15 minutes and assert no finding; create 8 inside 15 minutes and assert finding.

### 7. HIGH: Z-score analyzer does not clean NaN/Inf before statistics

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

### 8. HIGH: Feature profiling separates valid values from valid timestamps, which can misalign evidence

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

### 9. MEDIUM: Interpolated sample count reports remaining missing values, not interpolated values

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

### 10. MEDIUM: Prophet confidence decreases as deviation increases

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

## Additional Bug Candidates

### MEDIUM: Duplicate timestamps can make regular sampling appear valid

Evidence:
- `experiments/analyzer_router/feature_extractor.py:94-101`
- `experiments/analyzer_router/eligibility.py:17-59`

Current behavior:
Duplicate timestamps are counted, but eligibility does not reject or penalize duplicates. If duplicate diffs dominate, median interval can be 0 and regularity math becomes unreliable.

Recommended test:
Profile a dataset with duplicate timestamps and assert analyzers requiring regular sampling are rejected or warned.

### MEDIUM: Baseline/ruptures change index can refer to cleaned series, not original rows

Evidence:
- `intelligence/analyzers/baseline_shift.py:52-55`
- `intelligence/analyzers/ruptures.py:101-123`

Current behavior:
Rows with invalid values are dropped before detection. The returned change-point index is then based on the cleaned array, which can differ from the original row index.

Recommended test:
Insert missing values before a known change point and assert reported index/timestamp still maps to the original sample.

### MEDIUM: STUMPY fallback ignores `motif_count`

Evidence:
- `intelligence/analyzers/stumpy.py:37-44`
- `intelligence/analyzers/stumpy.py:132-169`

Current behavior:
Fallback motif detection returns one best pair even when `motif_count` is greater than 1.

Recommended test:
Generate three repeated motifs, run fallback path, and assert either multiple motifs are returned or the limitation is explicit.

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

## 3. Analyzer-by-Analyzer Test-Gap Table

| Analyzer | Implemented Runtime | Key Config Evidence | Current Tests Seen | Highest Test Gap |
| --- | --- | --- | --- | --- |
| `baseline_shift` / router `ruptures` | Yes, custom ruptures-backed baseline logic | `config/analyzers.yaml:29-43`, `intelligence/pipeline.py:161-174` | Aggregator precedence tests cover baseline narrative | Missing dirty-data index mapping, duplicate timestamp, off-edge change-point tests |
| `ruptures` standalone | Yes, but not primary runtime path | `intelligence/analyzers/ruptures.py:67-153` | Not clearly covered in direct tests | Config propagation and line-index correctness |
| `stumpy` | Yes, optional STUMPY plus fallback | `config/analyzers.yaml:9-19`, `intelligence/analyzers/stumpy.py:29-169` | `tests/test_stumpy_analyzer.py`, aggregator rule tests | Installed-library exception handling, multi-motif correctness, irregular timestamps |
| `prophet` | Yes, optional Prophet plus fallback | `config/analyzers.yaml:20-28`, `intelligence/analyzers/prophet.py:27-162` | `tests/test_prophet_analyzer.py` | Confidence semantics and forecast-vs-actual time alignment |
| `anomaly_zscore` | Yes, pandas/statistics | `config/analyzers.yaml:44-53`, `intelligence/analyzers/anomaly_zscore.py:10-108` | `tests/test_anomaly_zscore_analyzer.py` | NaN/Inf coercion, constant series, grouped false positives |
| `pyod_outlier` | Yes, optional PyOD plus fallback | `config/analyzers.yaml:54-66`, `intelligence/analyzers/pyod_outlier.py:27-157` | `tests/test_pyod_outlier_analyzer.py` | `finding_rules.window` enforcement, contamination edge cases, missing dependency behavior |
| `trend` | Yes, numpy/stats-style regression | `config/analyzers.yaml:67-73`, `intelligence/analyzers/trend.py:12-118` | `tests/test_trend_analyzer.py` | Constant series, NaN/Inf, slope percent denominator near zero |
| `adtk` router | No direct ADTK runtime, maps to z-score | `intelligence/pipeline.py:355` | Router tests only | Must assert displayed ADTK does not imply ADTK library execution |
| `pyod` router | No direct PyOD generic runtime, maps to z-score | `intelligence/pipeline.py:356` | Router tests only | Must prevent library/runtime misattribution |
| `kats` router | No Kats runtime, maps to multiple analyzers | `intelligence/pipeline.py:353` | Router tests only | Must stop silent substituted execution |
| `darts` router | No Darts runtime, maps to Prophet | `intelligence/pipeline.py:352` | Router tests only | Must stop silent substituted execution |
| custom `statsforecast_forecast` | Stub only | `config/custom_analyzers.yaml:1-42`, `backend/app/analyzers/custom/statsforecast_forecast.py:37-56` | API lifecycle tests | Must assert pending implementation cannot emit real signals/findings |

## 4. Recommended Common Analyzer Contract Test Suite

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

## 5. Suggested First 10 Regression Tests

1. Pipeline partial failure: one analyzer raises, another succeeds.
2. Analysis run status transitions to failed/partial when analyzer execution fails.
3. Router `darts`, `kats`, and `pyod` cannot silently execute substitute implementations.
4. Custom `statsforecast_forecast` pending implementation is recommendation-only and never persists signals.
5. PyOD: 8 outliers outside 15 minutes should not match `finding_rules.window`.
6. PyOD: 8 outliers inside 15 minutes should match `finding_rules.window`.
7. Aggregator: non-matching PyOD/STUMPY/Prophet/Z-score signal mixed with trend/baseline is excluded from finding evidence.
8. Z-score: NaN/Inf values are cleaned or rejected without malformed evidence.
9. Router feature extractor: interpolation count reports filled values, not remaining missing values.
10. Baseline/ruptures: missing values before a known change point do not shift reported timestamp/index.

## 6. Bugs To Confirm With Existing Analyzer Labs

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

## 7. Areas Requiring Synthetic Execution

Static review is insufficient for these:

1. Optional library behavior: PyOD, STUMPY, Prophet, StatsForecast, Darts, Kats, and ADTK behavior depends on installed versions and import availability.
2. Boundary windows: exact grouping behavior around `15m`, `5m`, and sample-count thresholds needs timestamped synthetic data.
3. Confidence semantics: monotonicity must be checked across controlled positive/negative magnitudes.
4. Router profile extraction: detected profiles depend on generated values, interpolation, sampling regularity, and timestamp quality.
5. Persistence correctness: partial failures and duplicate findings need a real test DB or transaction-backed integration tests.
6. Frontend lab truth tables: expected-vs-actual labels need API-backed execution to avoid displaying synthetic truth as real analyzer success.

## Summary Recommendation

Start stabilization with pipeline failure isolation and truthful runtime attribution. Those two risks affect every analyzer and every UI surface. Then use the analyzer labs as repeatable generators for the top false-positive/false-negative scenarios, especially PyOD window rules, Prophet confidence semantics, STUMPY multi-motif detection, and baseline change-point indexing.
