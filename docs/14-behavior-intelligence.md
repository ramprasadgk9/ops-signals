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

## Current Implementation

- Behavior definitions live in `config/behavior_definitions.yml`
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
