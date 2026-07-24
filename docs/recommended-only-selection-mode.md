# Recommended Only Selection Mode

This document explains what `selection_mode: recommended_only` does in Ops Signals, how analyzers become `RECOMMENDED`, how that affects actual execution, and how to extend the system with new analyzers.

Current config reference:

- [analyzers.yaml](/Users/ramprasad/Documents/workspace/github/ops-signals/config/analyzers.yaml)
- [analyzer_registry.yaml](/Users/ramprasad/Documents/workspace/github/ops-signals/experiments/analyzer_router/analyzer_registry.yaml)
- [pipeline.py](/Users/ramprasad/Documents/workspace/github/ops-signals/intelligence/pipeline.py)
- [router.py](/Users/ramprasad/Documents/workspace/github/ops-signals/experiments/analyzer_router/router.py)

## Goal

`recommended_only` exists to avoid running every analyzer on every metric.

Instead of treating all analyzers as equally useful, Ops Signals first profiles the series, scores analyzer fit, and only executes analyzers that the router marks as strong matches.

This gives you:

- less noise
- fewer weak detections
- better runtime discipline
- clearer evidence about why a particular analyzer was chosen

## Current Config

The current setting lives in [analyzers.yaml](/Users/ramprasad/Documents/workspace/github/ops-signals/config/analyzers.yaml):

```yaml
analysis:
  selection_mode: recommended_only
  selected_analyzers: []
```

Meaning:

- router evaluation always happens first
- only router decisions marked `RECOMMENDED` are allowed into the main pipeline
- `OPTIONAL` analyzers are visible in metadata but do not execute
- `NOT_RECOMMENDED` analyzers do not execute
- `REJECTED` analyzers fail eligibility and do not execute

## How The Decision Flow Works

The runtime path is:

1. Normalize the incoming time series
2. Build a series profile
3. Evaluate each analyzer against eligibility rules
4. Score fit using scoring rules
5. Convert the score into a recommendation bucket
6. Map recommended router analyzers to actual pipeline analyzers
7. Execute only the allowed analyzers

The pipeline code that applies this lives in [pipeline.py](/Users/ramprasad/Documents/workspace/github/ops-signals/intelligence/pipeline.py).

## Recommendation Thresholds

The actual thresholds are defined in [router.py](/Users/ramprasad/Documents/workspace/github/ops-signals/experiments/analyzer_router/router.py):

- `REJECTED`
  Eligibility failed
- `RECOMMENDED`
  `final_score >= 0.80`
- `OPTIONAL`
  `0.55 <= final_score < 0.80`
- `NOT_RECOMMENDED`
  `final_score < 0.55`

This is important:

- `REJECTED` is not the same as weak fit
- `REJECTED` means the analyzer was not technically eligible
- `NOT_RECOMMENDED` means eligible, but not strong enough

## What The Router Profiles

The router extracts a signal profile from the series in [feature_extractor.py](/Users/ramprasad/Documents/workspace/github/ops-signals/experiments/analyzer_router/feature_extractor.py).

Important metrics include:

- `sample_count`
- `regular_sampling`
- `irregular_sampling_percentage`
- `missing_percentage`
- `trend_strength`
- `seasonality_strength`
- `spikiness`
- `shift_index`
- `constant_value_percentage`

These are the core signals used by analyzer scoring rules.

## How Final Score Is Calculated

For eligible analyzers:

```text
final_score = min(1.0, eligibility_score * suitability_score)
```

Where:

- `eligibility_score` comes from technical requirements
- `suitability_score` starts from a base value and increases when configured rules match

The scoring rules are externalized in [analyzer_registry.yaml](/Users/ramprasad/Documents/workspace/github/ops-signals/experiments/analyzer_router/analyzer_registry.yaml).

## Examples Of Current Logic

### Ruptures

Ruptures starts with a base score of `0.45`.

It gets stronger when:

- `shift_index` is high
- sampling is regular
- spike behavior is present but not dominant

Interpretation:

- good for baseline shifts and regime changes
- strong choice when the metric clearly moves from one operating level to another

### STUMPY

STUMPY starts with a base score of `0.30`.

It gets stronger when:

- `seasonality_strength` is high
- sampling is regular
- sample count is large enough

Interpretation:

- good for repeating patterns and motif-like structure
- weak fit on messy or irregularly sampled data

### Prophet

Prophet starts with a base score of `0.28`.

It gets stronger when:

- sample count is at least `60`
- sampling is regular
- trend or seasonality evidence is strong

Interpretation:

- forecasting should not be recommended only because the data exists
- it should be recommended when there is enough history plus predictable structure

### River

River starts with a base score of `0.35`.

It gets stronger when:

- irregular sampling is higher
- spikiness is higher
- the series looks more streaming or drift-oriented

Interpretation:

- good for online or irregular anomaly handling
- not the best choice for a clean regular baseline-shift signal

### Kats

Kats starts with a base score of `0.28`.

It gets stronger when:

- there is mixed behavior
- some shift, seasonality, and trend evidence co-exist

Interpretation:

- useful when the metric is not dominated by a single simple shape

## What Actually Runs In The Main Pipeline

The router IDs are not always one-to-one with pipeline analyzers.

Current mapping in [pipeline.py](/Users/ramprasad/Documents/workspace/github/ops-signals/intelligence/pipeline.py):

```text
ruptures -> ruptures, baseline_shift
stumpy -> stumpy
prophet -> prophet
darts -> prophet
trend_regression -> trend
adtk -> anomaly_zscore
pyod -> anomaly_zscore
```

This means:

- if router recommends `ruptures`, the pipeline executes both `ruptures` and `baseline_shift`
- if router recommends `adtk`, the pipeline currently executes `anomaly_zscore`
- some router analyzers are conceptual recommendations that map to currently available pipeline analyzers

## Example Scenarios

### Scenario 1: Baseline Shift

Series shape:

- regular sampling
- clear drop or jump
- enough history
- moderate shift index

Likely result:

- `Ruptures` becomes `RECOMMENDED`
- `Trend Regression` may be `OPTIONAL`
- `STUMPY` may be `NOT_RECOMMENDED`

Pipeline effect:

- `ruptures`
- `baseline_shift`

### Scenario 2: Strong Repeating Pattern

Series shape:

- regular sampling
- high seasonality strength
- enough samples

Likely result:

- `STUMPY` becomes `RECOMMENDED`
- `Prophet` may also be `RECOMMENDED` or `OPTIONAL`
- `Ruptures` may fall to `OPTIONAL`

Pipeline effect:

- `stumpy`
- maybe `prophet` if Prophet is also recommended

### Scenario 3: Irregular Spiky Stream

Series shape:

- irregular sampling
- higher spikiness
- weaker seasonality

Likely result:

- `River` becomes stronger
- `ADTK` or `PyOD` may become stronger
- `STUMPY` often weakens

Pipeline effect:

- today, `adtk` and `pyod` map to `anomaly_zscore`

### Scenario 4: Short Or Low-Quality Series

Series shape:

- too few samples
- invalid timestamps
- mostly constant

Likely result:

- many analyzers become `REJECTED`
- others may remain `NOT_RECOMMENDED`

Pipeline effect:

- in `recommended_only`, almost nothing runs

This is expected behavior, not necessarily a bug.

## Why A Good Metric Can Still Execute Nothing

A metric can be technically valid but still run no analyzers in `recommended_only`.

That usually means:

- data quality is acceptable
- no analyzer reached the `RECOMMENDED` threshold

This is a key distinction:

- `data quality: good`
- `analyzer fit: weak`

That is often better than forcing analyzers to run and generating noisy false positives.

## Current Selection Modes

### `all`

Meaning:

- router metadata may still be calculated
- analyzer routing does not restrict execution
- everything enabled in the pipeline config can run

Use this when:

- you are debugging analyzers
- you want maximum coverage

### `recommended_only`

Meaning:

- only `RECOMMENDED` router analyzers are allowed to execute

Use this when:

- you want stricter routing discipline
- you want less noise and clearer analyzer intent

### `manual_override`

Meaning:

- recommended analyzers run
- plus anything explicitly listed in `selected_analyzers`

Use this when:

- you want routing, but need to force one or two analyzers during testing

## How To Add A New Analyzer

There are three layers to think about:

1. Router registry
2. Pipeline mapping
3. Actual analyzer implementation

### Step 1: Add The Analyzer To The Router Registry

Edit [analyzer_registry.yaml](/Users/ramprasad/Documents/workspace/github/ops-signals/experiments/analyzer_router/analyzer_registry.yaml).

Add:

- `display_name`
- `supported_profiles`
- `eligibility_rules`
- `suitability_rules`
- `scoring_rules`
- `explanation_templates`

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
      - metric: spikiness
        gte: 0.25
        add: 0.10
  explanation_templates:
    selected: The series matches the behavior this analyzer is designed for.
    excluded: The series does not meet the technical prerequisites for this analyzer.
```

### Step 2: Make Sure The Router Can Score It

If your rules use existing metrics like:

- `trend_strength`
- `seasonality_strength`
- `shift_index`
- `spikiness`

then no code change is needed in the feature extractor.

If you need a brand-new metric:

- add it to [feature_extractor.py](/Users/ramprasad/Documents/workspace/github/ops-signals/experiments/analyzer_router/feature_extractor.py)
- add it to the series profile model if required

### Step 3: Decide How It Maps To Execution

If the analyzer already exists in the main pipeline, map it in [pipeline.py](/Users/ramprasad/Documents/workspace/github/ops-signals/intelligence/pipeline.py).

Current pattern:

```python
router_to_pipeline = {
    "my_new_analyzer": {"my_new_analyzer"},
}
```

If it is only a conceptual router recommendation and should reuse an existing pipeline analyzer, map it that way:

```python
router_to_pipeline = {
    "my_new_analyzer": {"anomaly_zscore"},
}
```

### Step 4: Add The Actual Analyzer Implementation If Needed

If no pipeline analyzer exists yet:

- implement it in the main analyzer layer
- wire it into analyzer construction in the pipeline
- add config support in [analyzers.yaml](/Users/ramprasad/Documents/workspace/github/ops-signals/config/analyzers.yaml)

### Step 5: Test It In Isolation First

Use:

- analyzer router experiment pages
- local sample CSVs
- mock Prometheus lab services

Validate:

- eligible vs rejected behavior
- score movement with different time series shapes
- actual pipeline execution under `recommended_only`

## How To Tune Existing Recommendation Logic

Most tuning does not need Python code changes.

You can often adjust:

- base scores
- thresholds like `gte`
- additive score weights
- explanation text

in [analyzer_registry.yaml](/Users/ramprasad/Documents/workspace/github/ops-signals/experiments/analyzer_router/analyzer_registry.yaml).

You only need code changes when:

- you need a new profile metric
- you need new eligibility behavior
- you need a new pipeline mapping
- you need a brand-new execution analyzer

## Practical Advice For `recommended_only`

Use `recommended_only` when you want the product to behave like a selective router, not a brute-force analyzer runner.

It is a good default when:

- metrics vary widely
- you want explainability
- you want to reduce noisy detections
- you plan to route analyzer cost based on signal shape

It is a bad fit when:

- you are still benchmarking every analyzer on every metric
- you want exhaustive experimental coverage
- router rules are still too immature for your domain

## Summary

`recommended_only` means:

- profile first
- recommend based on real signal shape
- execute only strong analyzer matches

The real decision logic lives mostly in YAML, not hardcoded Python.

That is good for your long-term goal because it means:

- adding analyzers is easier
- tuning rules is faster
- moving this router into the main operational path is realistic
