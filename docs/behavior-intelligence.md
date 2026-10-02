# Behavior Intelligence

Behavior Intelligence is a higher-level reasoning layer that consumes analyzer-generated signals from one or more metrics and evaluates declarative behavior definitions.

It is separate from analyzers:

- analyzers produce low-level signals from a single metric
- behavior definitions combine signals across metrics
- behavior findings capture the higher-level operational condition

## Why It Exists

Metric-level findings are useful, but some operational problems only become clear when multiple metrics are considered together.

Examples:

- CPU throttling: CPU anomaly plus throttling trend or anomaly in the same window
- Server slowness: CPU abnormality plus memory trend or baseline shift over the same analysis period

## Behavior Definition Model

Behavior definitions are YAML-driven and deterministic.

They describe:

- enabled state and version
- title and description
- metric inputs and analyzer requirements
- conditions over normalized facts
- correlation constraints
- output category, severity, title, summary, and evidence fields

The feature does not use `eval`, `exec`, LLM-generated rules, or embedded scripts.

## Evaluation Flow

```text
Signals
-> Fact Extraction
-> Condition Evaluation
-> Temporal Correlation
-> Confidence Calculation
-> Behavior Finding
```

## Configuring a Behavior Definition

A minimal, real example - `config/behavior_definitions.d/memory_pressure.yml` in full:

```yaml
behavior_definitions:
  memory_pressure_with_errors:
    enabled: true
    version: 1
    title: Possible memory pressure impacting requests
    description: >
      Detects sustained upward memory pressure (trend or baseline shift) occurring together
      with an error-rate anomaly, suggestive of memory exhaustion starting to affect requests.
    scope:
      service: "*"
    inputs:
      - alias: memory
        metric_name: memory_usage
        analyzers:
          - trend
          - baseline_shift
      - alias: errors
        metric_name: error_rate
        analyzers:
          - anomaly_zscore
    conditions:
      all:
        - fact: errors.anomaly.present
          operator: equals
          value: true
      any:
        - fact: memory.trend.direction
          operator: equals
          value: upward
        - fact: memory.baseline_shift.signed_change_percent
          operator: greater_than
          value: 0
    correlation:
      same_analysis_context: true
      max_time_gap: 20m
      minimum_overlap: 5m
    output:
      category: resource_constraint
      severity: high
      title: Possible memory pressure impacting requests
      summary: >
        Memory usage is trending upward or shifted to a new baseline while errors are also
        anomalous in the same window — worth checking for memory exhaustion.
      evidence:
        - memory.trend.direction
        - memory.trend.change_percent
        - memory.baseline_shift.signed_change_percent
        - errors.anomaly.count
```

Reading it top to bottom: `inputs` names the metrics involved and which analyzers must have run
against them (`memory` needs `trend` or `baseline_shift`, `errors` needs `anomaly_zscore`).
`conditions` reference *facts* those analyzers produce (`errors.anomaly.present`,
`memory.trend.direction`, and `memory.baseline_shift.signed_change_percent`, positive when memory
moved up - a level change counts in either direction unless a condition says which) - `all` must hold, plus at least one of `any`. `correlation` bounds how
close in time the two signals need to be to count as related. `output` is what gets written as the
Behavior Finding if everything matches.

Drop a new file into `config/behavior_definitions.d/` (any filename - it's a directory of
independent packs, not one shared file) and restart the backend to pick it up.

## Current Implementation

- Behavior definitions live in `config/behavior_definitions.d/*.yml` - a directory of files (not
  one shared file), so a new definition pack can be added without editing an existing one
- The backend exposes behavior definition and evaluation APIs
- The batch pipeline can evaluate matching behaviors after signals are generated
- Behavior findings are stored in PostgreSQL
- The React UI includes an inline collapsible reasoning block for each matched finding

## What Users Can See

The UI explanation includes:

- why the finding matched
- which facts were extracted
- which conditions passed or failed
- evidence fields used by the rule
- correlation summary
- confidence score

## Limitations

- Behavior findings are assistance, not autonomous action
- Similarity or correlation does not prove root cause
- Rules only evaluate normalized facts available in the signal record

## Future Direction

- promote behavior findings into cases when useful
- improve explanation formatting
- add more reusable behavior definitions
- expand test coverage for evaluation and correlation
