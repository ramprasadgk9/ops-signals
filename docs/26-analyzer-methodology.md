# Analyzer & Router Methodology

This document exists to answer one question honestly: **when a claim is made about how a
detection or a recommendation was produced, what's it actually based on?** Some parts of this
pipeline rest on published, peer-reviewed methods. One part - the router's analyzer suitability
scores - does not, and this page says so plainly rather than leaving that gap to be discovered.

## The 7 detection analyzers: published methods, not invented here

Every analyzer that actually detects something in the data is a real, established, cited
technique - Ops Signals applies them to operational time series, it doesn't invent new statistics.

| Analyzer | Detects | Method | Citation | Source |
| --- | --- | --- | --- | --- |
| `ruptures` | Regime changes, structural breaks | Offline change-point detection (binary segmentation) | Truong, C., Oudre, L., & Vayatis, N. (2020). *Selective review of offline change point detection methods.* Signal Processing, 167, 107299. | [`intelligence/analyzers/ruptures.py`](../intelligence/analyzers/ruptures.py) |
| `baseline_shift` | Sustained shift between two segments | Same binary-segmentation foundation as `ruptures` (`ruptures_algorithm: binseg`, `ruptures_model: l2`), applied to compare a before/after window rather than find an arbitrary number of breakpoints | Truong, Oudre & Vayatis (2020), as above | [`intelligence/analyzers/baseline_shift.py`](../intelligence/analyzers/baseline_shift.py) |
| `stumpy` | Repeating patterns, motifs, seasonality | Matrix Profile | Yeh, C-C. M., et al. (2016). *Matrix Profile I: All Pairs Similarity Joins for Time Series.* IEEE ICDM 2016. &nbsp;+&nbsp; Law, S. M. (2019). *STUMPY: A Powerful and Scalable Python Library for Time Series Data Mining.* JOSS, 4(39), 1504. | [`intelligence/analyzers/stumpy.py`](../intelligence/analyzers/stumpy.py) |
| `prophet` | Trend + seasonal forecasting, forecast-band deviation | Additive regression forecasting | Taylor, S. J., & Letham, B. (2018). *Forecasting at scale.* The American Statistician, 72(1), 37-45. | [`intelligence/analyzers/prophet.py`](../intelligence/analyzers/prophet.py) |
| `pyod_outlier` | Isolated outlier points | KNN-based outlier scoring | Zhao, Y., Nasrullah, Z., & Li, Z. (2019). *PyOD: A Python Toolbox for Scalable Outlier Detection.* JMLR, 20(96), 1-7. | [`intelligence/analyzers/pyod_outlier.py`](../intelligence/analyzers/pyod_outlier.py) |
| `anomaly_zscore` | Points far from the recent mean | Standard-score / sigma-threshold control | Shewhart, W. A. (1931). *Economic Control of Quality of Manufactured Product.* The foundational statistical-process-control concept behind sigma-threshold anomaly detection. | [`intelligence/analyzers/anomaly_zscore.py`](../intelligence/analyzers/anomaly_zscore.py) |
| `trend` | Sustained upward/downward slope | Ordinary Least Squares regression | Classical least-squares regression, implemented via Seabold, S., & Perktold, J. (2010). *statsmodels: Econometric and statistical modeling with Python.* Proceedings of the 9th Python in Science Conference. | [`intelligence/analyzers/trend.py`](../intelligence/analyzers/trend.py) |

If you're evaluating whether the *detection* math is legitimate: yes - every one of these is a
citable, independently-published method, not something invented for this project.

## The router's suitability scores: heuristic, and we say so

This is the part that does **not** carry a citation, and it would be dishonest to imply otherwise.

Before any analyzer runs, the router computes a 0-1 "suitability score" for each one, from
additive threshold rules against a handful of pre-computed series features (`shift_index`,
`spikiness`, `seasonality_strength`, `trend_strength`, `regular_sampling`, `sample_count`).
`ruptures`' actual current formula (`experiments/analyzer_router/analyzer_registry.yaml`):

```yaml
scoring_rules:
  base: 0.45
  rules:
    - metric: shift_index,      gte: 0.12, add: 0.18
    - metric: shift_index,      gte: 0.22, add: 0.22
    - metric: shift_index,      gte: 0.32, add: 0.08
    - metric: regular_sampling, equals: true, add: 0.08
    - metric: spikiness,        gt: 0.35,  add: 0.04
```

**These specific numbers - the `0.45`, the `0.18`, the `0.22` - were chosen by hand, using domain
intuition when the registry was written.** They are not fit against outcome data, not benchmarked
against a published calibration methodology, and not derived from any paper. The production
execution cutoff that decides whether an analyzer actually runs at all
(`config/analyzers.yaml`'s `recommendation_execution.min_score: 0.80`) is compared directly
against these hand-picked scores.

This matters in practice, not just in principle: a known issue (GitHub #21) shows PyOD's
suitability score not responding to how severe an actual outlier is, because the scoring inputs
are computed *before* the analyzer ever runs - a structural consequence of scoring this way, not
a one-off bug.

### A second, more direct bug found while checking this

Verifying the above against the real `ruptures` documentation surfaced something more concrete
than a citation nuance. The router's scoring rules run against `shift_index` and `spikiness` for
nearly every analyzer (`ruptures`, `stumpy`, `prophet`, `pyod_outlier`, and others), computed once
per series. Two separate implementations of those features existed:

- **The real production pipeline** (`experiments/analyzer_router/feature_extractor.py`) computes
  `shift_index` by actually searching for the best split point in the series and measuring the
  size of the jump there - conceptually close to what change-point detection itself is doing.
- **The standalone Analyzer Recommendation workbench** (`/evaluate`, `/chat` -
  `backend/app/metric_analyzer_recommendations/service.py`) had its own separate, much weaker
  stand-in: `shift_index` was approximated as `variance / mean` over the whole series (which
  cannot distinguish "there's a real regime change" from "this series is just noisy"), and
  **`spikiness` was hardcoded to `0.0` for every series, unconditionally** - never computed at all.

Since `pyod_outlier`'s formula earns up to `0.30` of its score from `spikiness` alone, this meant
PyOD could never receive that credit in the workbench, for any data, regardless of how spiky the
real series actually was - a second, more direct explanation for the severity-insensitivity in
GitHub #21, on top of the router-scoring-is-pre-execution point above.

**Fixed**: `_build_router_profile()` now computes both features from the real underlying values,
using the same `_spikiness()`/`_shift_index()` functions the production pipeline uses, whenever a
real sample is available (falling back to the previous safe defaults only when there's no
underlying data at all, e.g. the workbench's preliminary chat state before a sample is selected).
See `tests/api_backend/test_router_profile_uses_real_shape_features.py`.

One further, deeper property surfaced while fixing this, left as a separate open item rather than
chased down immediately: `_spikiness()`'s own threshold formula mixes a robust statistic
(median/MAD) with a non-robust one (`stddev(diffs) * 6`) inside a `max()`. When a series has only
a handful of large spikes among many points, those spikes inflate the standard-deviation term
enough that the threshold can become harder to clear than the spikes themselves - a case where the
detector can fail to register spikes that are visually obvious. Worth its own investigation.

## How we're closing that gap

Rather than leave "heuristic" as a permanent state, three pieces of real infrastructure now exist
specifically to validate and eventually recalibrate these weights against actual outcomes:

1. **`AnalyzerLearningOutcomeEntity`** (`backend/app/models/entities.py`) - records, for every
   resolved case, whether the analyzers that flagged it were `confirmed` real or `rejected` as
   noise. This is the ground truth: a ranked score should correlate with a higher confirmed rate,
   and this table is what actually lets you check that instead of assuming it.
2. **`AnalyzerDivergenceEntity`** (`backend/app/models/entities.py`, `analyzer_recommendation_divergences`
   table) - logs every time the optional AI second opinion agrees or disagrees with the router's
   pick, for every evaluation, not just the disagreements. Joined against outcome #1 on
   `analysis_run_id`, this answers "when the AI and the router disagree, which one tends to be
   right" - a live, continuously-available signal for whether the hand-picked weights above are
   drifting from reality.
3. **The benchmark suite** ([`benchmark/README.md`](../benchmark/README.md)) - currently validates
   whether the router picks the *right* analyzer for known scenarios. It does not yet validate
   whether the *score's magnitude* is proportional to severity (the specific gap #21 exposes).
   Extending it with severity-graded scenarios is a known, scoped next step.

**This is an open invitation, not just a status note.** Calibrating the router's scoring weights
against real outcome data - once enough of it accumulates via #1 and #2 above - is exactly the
kind of well-scoped, concrete contribution this project needs and doesn't yet have anyone assigned
to. If you're looking for a substantive way to contribute, this is one.

## Current status, at a glance

| Component | Status |
| --- | --- |
| The 7 detection algorithms | Published, peer-reviewed methods (see table above) |
| Router suitability scoring weights (the `base`/`add` numbers themselves) | Heuristic, hand-authored, not yet validated against outcomes |
| Workbench feeding the scoring formula real `shift_index`/`spikiness` (not a crude shim or a hardcoded `0.0`) | **Fixed** - see above |
| `_spikiness()`'s own threshold calibration (robust vs. non-robust statistic mixed in one formula) | Open item, not yet investigated |
| Ground truth to validate against | Exists (`analyzer_learning_outcomes`), depends on cases actually being resolved through the UI |
| AI-vs-router divergence tracking | Exists (`analyzer_recommendation_divergences`), accumulating from real traffic |
| Benchmark coverage of score calibration (not just selection accuracy) | Not yet built |
| Weights recalibrated from real data | Not yet done - blocked on enough accumulated outcome data |
