# Analyzer Selection and `recommended_only` Mode

Ops Signals analyzes operational time-series data such as CPU, memory, request rate, latency, and network traffic. Different analyzers are designed for different signal shapes. A change-point analyzer may work well for a baseline shift, while a motif detector may be more appropriate for repeating patterns.

Ops Signals therefore profiles the series first and then selects analyzers whose capabilities match the observed behavior.

```text
Select analyzers
→ Execute selected analyzers
```

Selection and execution are separate concerns:

- **Analyzer:** A component that inspects a time series for a particular kind of behavior.
- **Router:** The explainable, rule-based analyzer selection engine.
- **Series profile:** A measurable summary of the signal shape and data quality.
- **Eligibility:** Whether an analyzer can technically operate on the data.
- **Suitability:** Whether an eligible analyzer is a useful match for the observed signal shape.
- **Recommendation:** The router category assigned to an analyzer.
- **Pipeline analyzer:** The executable analyzer implementation used by the main analysis pipeline.
- **Operational finding:** A user-facing result produced from analyzer signals and evidence.

The router is not a trained machine-learning model, an LLM router, or a guarantee of the objectively best analyzer. It extracts measurable characteristics from the time series, checks analyzer eligibility, calculates suitability scores using configurable rules, places analyzers into recommendation categories, and lets the execution pipeline run only the selected analyzers.

> **Important:** Recommendation scores are suitability scores used for routing, not probabilities or statistical confidence values. A score of `0.86` does not mean the analyzer has an 86% chance of being correct.

## Why Analyzer Selection Exists

Running every analyzer on every metric is useful during benchmarking, but it can create unnecessary execution and noisy or duplicate output in normal operation. `recommended_only` makes analyzer execution more selective.

| Run Every Analyzer | Recommended-Only Selection |
| --- | --- |
| Every enabled analyzer executes | Only strong matches execute |
| Higher compute usage | Lower unnecessary execution |
| More duplicate or irrelevant output | More focused findings |
| Harder to explain analyzer choice | Selection reasons are recorded |
| Useful for benchmarking | Better suited for normal operation |

This document does not claim a fixed performance improvement. Actual runtime depends on data size, enabled analyzers, deployment environment, and future implementation changes.

## Quick Start

The main runtime configuration lives in [`../config/analyzers.yaml`](../config/analyzers.yaml).

```yaml
analysis:
  selection_mode: recommended_only
  selected_analyzers: []
```

Settings:

- `selection_mode: recommended_only` tells the runtime pipeline to execute only analyzers that the router marks as `RECOMMENDED`.
- `selected_analyzers: []` is empty because no manual additions are requested.

Conceptual result:

```text
Recommended and executed:
- Ruptures
- Prophet

Visible but not executed:
- River: OPTIONAL
- STUMPY: NOT_RECOMMENDED
- PyOD: REJECTED
```

In the Grafana plugin, the run details can show recommended, optional, not recommended, rejected, and executed analyzers so users can understand both what ran and what did not run.

## How It Works

```text
Time-series samples
        ↓
Feature extraction
        ↓
Series profile
        ↓
Eligibility checks
        ↓
Suitability scoring
        ↓
Recommendation category
        ↓
Router-to-pipeline mapping
        ↓
Analyzer execution
        ↓
Operational findings
```

The stages are:

| Stage | What happens |
| --- | --- |
| Time-series samples | The pipeline receives timestamped numeric observations. |
| Feature extraction | The router calculates measurable properties such as sample count, regularity, trend, seasonality, spikes, and shifts. |
| Series profile | Those properties are stored as a structured profile. |
| Eligibility checks | Each analyzer is checked against technical requirements such as minimum samples or regular timestamps. |
| Suitability scoring | Eligible analyzers receive a score based on configurable YAML rules. |
| Recommendation category | Scores are converted into `RECOMMENDED`, `OPTIONAL`, or `NOT_RECOMMENDED`; failed eligibility becomes `REJECTED`. |
| Router-to-pipeline mapping | Router analyzer IDs are mapped to executable pipeline analyzer IDs. |
| Analyzer execution | The pipeline executes only the analyzers allowed by the configured selection mode. |
| Operational findings | Signals from executed analyzers are converted into findings for investigation. |

Implementation references:

- Runtime config: [`../config/analyzers.yaml`](../config/analyzers.yaml)
- Router implementation: [`../experiments/analyzer_router/router.py`](../experiments/analyzer_router/router.py)
- Feature extraction: [`../experiments/analyzer_router/feature_extractor.py`](../experiments/analyzer_router/feature_extractor.py)
- Eligibility checks: [`../experiments/analyzer_router/eligibility.py`](../experiments/analyzer_router/eligibility.py)
- Registry rules: [`../experiments/analyzer_router/analyzer_registry.yaml`](../experiments/analyzer_router/analyzer_registry.yaml)
- Runtime pipeline: [`../intelligence/pipeline.py`](../intelligence/pipeline.py)

## Series Profile

The series profile describes the signal. These characteristics do not directly represent failures or incidents.

| Profile property | Simple meaning |
| --- | --- |
| `sample_count` | Number of observations available |
| `regular_sampling` | Whether samples arrive at consistent intervals |
| `irregular_sampling_percentage` | Degree of inconsistent spacing |
| `missing_percentage` | Amount of missing data |
| `trend_strength` | Strength of sustained upward or downward movement |
| `seasonality_strength` | Strength of repeating behavior |
| `spikiness` | Degree of short, sudden changes |
| `shift_index` | Evidence of movement between operating levels |
| `constant_value_percentage` | Portion of the series that remains unchanged |

Additional profile fields exist for implementation use, including `valid_sample_count`, `duplicate_timestamp_count`, `sampling_interval_seconds`, `duration_seconds`, `mean`, `stddev`, `minimum`, `maximum`, `variance`, `trend_slope`, and `autocorrelation`.

## Eligibility vs. Suitability

This distinction is central to understanding the router.

| Concept | Question it answers | Example |
| --- | --- | --- |
| Eligibility | Can this analyzer technically operate on the data? | Does Prophet have enough regularly sampled timestamped points? |
| Suitability | Is this analyzer a useful match for the signal shape? | Does the series contain enough trend or seasonality for forecasting to be informative? |

Example:

```text
Prophet may be eligible because enough regularly sampled data exists,
but not recommended because the series contains little trend or seasonality.
```

A valid metric can therefore have good data quality while still producing weak analyzer fit.

## Recommendation Categories

| Category | Meaning | Executes in `recommended_only` |
| --- | --- | --- |
| `RECOMMENDED` | Eligible and a strong match | Yes |
| `OPTIONAL` | Eligible and potentially useful, but below the strict threshold | No |
| `NOT_RECOMMENDED` | Eligible, but currently a weak match | No |
| `REJECTED` | Technical eligibility requirements failed | No |

Current default thresholds in [`../experiments/analyzer_router/router.py`](../experiments/analyzer_router/router.py):

```text
RECOMMENDED: final_score >= 0.80
OPTIONAL: 0.55 <= final_score < 0.80
NOT_RECOMMENDED: final_score < 0.55
REJECTED: eligibility failed
```

These thresholds are current defaults and may evolve as the project gathers more evidence.

## Scoring Model

For eligible analyzers, the current scoring formula is:

```text
final_score = min(1.0, eligibility_score × suitability_score)
```

How to read it:

- `eligibility_score` represents technical compatibility.
- `suitability_score` starts with an analyzer-specific base score.
- Matching rules add configured scoring weight.
- The result is capped at `1.0`.
- Recommendation thresholds convert the score into a category.

Most scoring behavior is configured in [`../experiments/analyzer_router/analyzer_registry.yaml`](../experiments/analyzer_router/analyzer_registry.yaml). This keeps the router explainable and easier to tune.

The current weights are expert-defined heuristics. They have not been validated across every metric type, organization, or incident pattern.

## Analyzer Examples

The examples below describe the current router intent. They are not universal mathematical truths.

### Ruptures

**Designed for:** Change points, baseline shifts, and regime changes.

**Works best when:**

- sampling is sufficiently regular
- enough history exists
- there is strong evidence of movement between operating levels

**May be a weak fit when:**

- the series is nearly constant
- the signal is dominated only by isolated spikes
- there are too few samples

### STUMPY

**Designed for:** Repeating patterns, motifs, and shape-based similarity.

**Works best when:**

- sampling is regular
- enough samples exist
- the series has strong repeating or seasonal structure

**May be a weak fit when:**

- sampling is irregular
- the series is short
- there is little repeated shape information

### Prophet

**Designed for:** Forecast-oriented analysis of trend and seasonal structure.

**Works best when:**

- timestamps are usable
- sampling is regular
- enough history exists
- trend or seasonality evidence is strong

**May be a weak fit when:**

- the metric is short-lived
- the signal is mostly flat
- the series has little predictable structure

### River

**Designed for:** Online or streaming-style anomaly and drift handling.

**Works best when:**

- the signal is spiky
- sampling is irregular
- the use case benefits from point-by-point or streaming interpretation

**May be a weak fit when:**

- the data is a clean, regular batch with a simple baseline shift
- there is little spike or drift-like behavior
- the current pipeline does not have a native River execution implementation wired for the route

### Kats

**Designed for:** Flexible time-series analysis across mixed behavior types.

**Works best when:**

- the series shows a genuine mix of shift, trend, seasonality, or anomaly behavior
- enough samples exist
- no single simpler analyzer clearly dominates the signal shape

**May be a weak fit when:**

- the series is clean and regular but not mixed
- the metric has too few samples
- a specialized analyzer is a clearer match

## Router-to-Pipeline Mapping

Router recommendations and executable analyzers are not always one-to-one. The router may recommend a conceptual analyzer family, while the runtime pipeline maps that recommendation to one or more currently available implementations.

Current mapping in [`../intelligence/pipeline.py`](../intelligence/pipeline.py):

| Router analyzer | Pipeline analyzer or analyzers |
| --- | --- |
| `ruptures` | `ruptures`, `baseline_shift` |
| `stumpy` | `stumpy` |
| `prophet` | `prophet` |
| `darts` | `prophet` |
| `trend_regression` | `trend` |
| `adtk` | `anomaly_zscore` |
| `pyod` | `anomaly_zscore` |

> **Compatibility fallback:** Some mappings currently represent compatibility fallbacks. For example, recommending ADTK or PyOD may execute the existing `anomaly_zscore` implementation rather than the original external library.

Future contributors may add native implementations and replace these fallback mappings.

If a recommended router analyzer has no explicit mapping, the pipeline currently falls back to using the same analyzer ID. That only works if a pipeline analyzer with that ID exists and is enabled.

## Selection Modes

The main runtime selection mode is configured in [`../config/analyzers.yaml`](../config/analyzers.yaml).

| Mode | Router used | Execution behavior | Recommended use |
| --- | --- | --- | --- |
| `all` | Yes, for metadata | Runs all enabled analyzers | Benchmarking and debugging |
| `recommended_only` | Yes | Runs only `RECOMMENDED` analyzers | Normal selective execution |
| `manual_override` | Yes | Runs recommended analyzers plus explicitly selected analyzers | Controlled testing and troubleshooting |

When `selected_analyzers` is empty:

- `all` still runs all enabled pipeline analyzers.
- `recommended_only` runs only router decisions marked `RECOMMENDED`.
- `manual_override` behaves like recommended-only unless explicit analyzer IDs are listed.

Current implementation note: an unknown runtime `selection_mode` does not fail validation. In [`../intelligence/pipeline.py`](../intelligence/pipeline.py), unknown modes fall back to unrestricted execution, which is effectively closer to `all`. Contributors may want to make this stricter later.

### Experiment Router Modes

The CSV experiment router also has request-level modes in [`../experiments/analyzer_router/models.py`](../experiments/analyzer_router/models.py):

| Experiment mode | Meaning |
| --- | --- |
| `automatic` | Return all router decisions without manual filtering. |
| `manual` | Return only explicitly selected router analyzers. |
| `automatic_with_override` | Return automatic decisions and allow selected analyzers to be marked as overridden when needed. |

These experiment modes are related, but they are not the same as the main runtime `analysis.selection_mode`.

## Realistic Scenarios

These outcomes are likely examples, not guarantees.

### 1. Baseline Shift

| Field | Example |
| --- | --- |
| Observed profile | Regular sampling, enough history, clear jump or drop, elevated `shift_index` |
| Likely recommendations | Ruptures becomes `RECOMMENDED`; Trend Regression or Kats may be `OPTIONAL` |
| Likely execution | `ruptures`, `baseline_shift` |
| Reason | Change-point and baseline-shift analyzers match movement between operating levels. |

### 2. Repeating or Seasonal Pattern

| Field | Example |
| --- | --- |
| Observed profile | Regular sampling, high `seasonality_strength`, enough samples |
| Likely recommendations | STUMPY becomes `RECOMMENDED`; Prophet may be `RECOMMENDED` or `OPTIONAL` |
| Likely execution | `stumpy`; maybe `prophet` |
| Reason | Motif and forecast analyzers are stronger fits when repeated structure exists. |

### 3. Irregular Spiky Stream

| Field | Example |
| --- | --- |
| Observed profile | Irregular sampling, high `spikiness`, weaker seasonality |
| Likely recommendations | River, ADTK, or PyOD may become stronger |
| Likely execution | Today, `adtk` and `pyod` map to `anomaly_zscore`; River requires a matching executable analyzer to run natively |
| Reason | Spike and online-style behavior can make anomaly-oriented analyzers more suitable than forecast or motif analyzers. |

### 4. Short, Invalid, or Low-Information Series

| Field | Example |
| --- | --- |
| Observed profile | Too few samples, invalid timestamps, mostly constant values, or high missingness |
| Likely recommendations | Many analyzers become `REJECTED`; others may be `NOT_RECOMMENDED` |
| Likely execution | In `recommended_only`, possibly nothing |
| Reason | The data may be valid enough to display, but not informative enough for analyzer execution. |

## No Analyzer Was Executed

No analyzer execution is not automatically a bug.

It can mean:

- the data was valid
- analyzers passed basic technical checks
- no analyzer reached the strict `RECOMMENDED` threshold

It can also be caused by:

- insufficient samples
- unsupported or invalid values
- mostly constant series
- missing router-to-pipeline mapping
- a recommended analyzer being disabled in pipeline configuration
- a configuration error

How to investigate:

1. Inspect the series profile.
2. Inspect router decisions and scores.
3. Check eligibility failure reasons.
4. Check router-to-pipeline mappings.
5. Temporarily use `manual_override`.
6. Use `all` only for debugging or comparison.

A useful mental model is:

```text
data quality: good
analyzer fit: weak
```

That is often better than forcing analyzers to run and generating noisy false positives.

## Adding a New Analyzer

Adding a new analyzer involves four contracts.

### A. Selection Contract

The analyzer declares how the router should reason about it.

Add an entry to [`../experiments/analyzer_router/analyzer_registry.yaml`](../experiments/analyzer_router/analyzer_registry.yaml):

- identity
- display name
- supported profiles
- eligibility requirements
- suitability and scoring rules
- explanation templates

Minimum example:

```yaml
my_new_analyzer:
  display_name: My New Analyzer
  supported_profiles:
    - anomaly
    - trend
  eligibility_rules:
    min_samples: 40
    requires_numeric: true
  suitability_rules:
    prefer_regular_sampling: true
  scoring_rules:
    base: 0.30
    rules:
      - metric: trend_strength
        gte: 0.20
        add: 0.20
        reason: Trend evidence supports this analyzer.
      - metric: spikiness
        gte: 0.25
        add: 0.10
        reason: Spike behavior supports this analyzer.
  explanation_templates:
    selected: The series matches the behavior this analyzer is designed for.
    excluded: The series does not meet the technical prerequisites for this analyzer.
```

### B. Feature Contract

The router requires measurable profile properties.

If your rules use existing profile metrics such as `trend_strength`, `seasonality_strength`, `shift_index`, or `spikiness`, no feature-extractor change is needed.

If you need a new measurable property:

- add it to [`../experiments/analyzer_router/feature_extractor.py`](../experiments/analyzer_router/feature_extractor.py)
- add it to [`../experiments/analyzer_router/models.py`](../experiments/analyzer_router/models.py) if it should be part of `SeriesProfile`
- document what it means in this file

### C. Execution Contract

The router analyzer ID must map to one or more executable pipeline analyzers.

If the analyzer already exists in the main pipeline, map it in [`../intelligence/pipeline.py`](../intelligence/pipeline.py):

```python
router_to_pipeline = {
    "my_new_analyzer": {"my_new_analyzer"},
}
```

If it is only a conceptual router recommendation and should reuse an existing pipeline analyzer, map it explicitly and document the fallback:

```python
router_to_pipeline = {
    "my_new_analyzer": {"anomaly_zscore"},
}
```

### D. Result Contract

The analyzer implementation must produce output compatible with the project’s normalized signal and finding models. That means the pipeline should be able to turn the analyzer result into operational signals, findings, evidence, and run metadata.

Contributor checklist:

```text
[ ] Registry entry added
[ ] Eligibility behavior tested
[ ] Suitability rules tested
[ ] Router mapping added
[ ] Native implementation added or fallback documented
[ ] Analyzer enabled in configuration
[ ] Unit tests added
[ ] Scenario test added
[ ] Documentation updated
```

## Tuning Existing Recommendation Logic

Most tuning does not need Python code changes.

You can often adjust the following in [`../experiments/analyzer_router/analyzer_registry.yaml`](../experiments/analyzer_router/analyzer_registry.yaml):

- base scores
- threshold comparisons such as `gte`, `gt`, `lte`, and `lt`
- additive score weights
- explanation text

You usually need code changes when:

- you need a new profile metric
- you need new eligibility behavior
- you need a new router-to-pipeline mapping
- you need a brand-new executable analyzer

## Testing Recommendations

Testing only one CSV is insufficient for validating routing rules. Contributors should test controlled series shapes:

- stable series
- baseline shift
- linear trend
- repeating seasonal pattern
- isolated spikes
- irregular sampling
- missing values
- mostly constant series
- short series
- mixed behavior

For each analyzer, test:

- eligibility outcome
- suitability score movement
- recommendation category
- explanation text
- router-to-pipeline mapping
- actual execution in every selection mode

Use realistic operational metrics when possible, such as CPU, memory, network throughput, request rate, and latency.

## Current Limitations

The current router is intentionally transparent, but it is still early.

Known limitations:

- scoring weights are currently expert-defined heuristics
- thresholds are not probabilities
- recommendation does not guarantee the best analytical result
- different metrics and domains may need different tuning
- some router analyzers map to fallback pipeline implementations
- router performance still requires broader benchmark validation
- no historical-outcome-based weight adjustment is active yet
- `recommended_only` can intentionally execute nothing
- multiple analyzers can detect overlapping evidence
- unknown runtime selection modes currently fall back to unrestricted execution instead of failing fast

These limitations are not reasons to avoid the router. They are the boundaries contributors should understand before tuning or extending it.

## Future Direction

The following are possible future capabilities, not current behavior:

- benchmark-driven rule calibration
- metric-type-specific profiles
- cost-aware routing
- historical outcome learning
- organization-specific score adjustments
- recommendation confidence calibration
- analyzer portfolio or analysis-plan selection

Future learning should be treated as evidence-informed tuning, not as a replacement for transparent router explanations.

## FAQ

### Why did no analyzer run?

Usually because no analyzer reached `RECOMMENDED` in `recommended_only`. Also check sample count, invalid values, constant signals, mappings, disabled analyzers, and configuration errors.

### Is the score a probability?

No. It is a suitability score used for routing. A score of `0.86` does not mean 86% confidence.

### Can multiple analyzers be recommended?

Yes. A metric can show multiple behaviors, such as a trend plus a baseline shift.

### Can I force an analyzer?

Yes. Use `manual_override` with `selected_analyzers` in [`../config/analyzers.yaml`](../config/analyzers.yaml).

### Does `OPTIONAL` execute?

Not in `recommended_only`. `OPTIONAL` is visible for explanation, but it is not executed by that mode.

### Why does one recommendation execute two analyzers?

Some router analyzer IDs map to multiple pipeline analyzers. For example, `ruptures` maps to both `ruptures` and `baseline_shift`.

### Does the router use an LLM?

No. The router is an explainable, rule-based analyzer selection engine.

### Are YAML rules automatically learned?

No. Current YAML rules are manually configured. Historical outcome learning is documented as a future direction, not active scoring behavior.

### How can I add my own analyzer?

Add a registry entry, ensure required profile features exist, map the router ID to executable pipeline analyzers, implement or document the execution behavior, add tests, and update docs.

### Should I use `all` in production?

Use `all` when you need benchmarking or maximum diagnostic coverage. For normal selective execution, prefer `recommended_only` once your router rules fit your metric domain.

## Summary

`recommended_only` profiles the time series, checks analyzer eligibility, calculates explainable suitability scores, and executes only strong matches.

It is designed to reduce unnecessary analyzer execution while preserving visibility into why each analyzer was selected or skipped.
