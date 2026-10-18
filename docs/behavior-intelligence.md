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
        # OpenTelemetry names for the same metric (Kubernetes kubelet and Docker receivers), as sent over OTLP
        aliases: [container.memory.usage, container.memory.usage.total, k8s.pod.memory.usage]
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
close in time the two signals need to be to count as related: the inputs match when some pair of
their signals is within `max_time_gap` of each other, or overlaps by at least `minimum_overlap`
(with neither set, they must overlap). Only the signals the passing conditions name are compared
(the anomaly windows for `errors.anomaly.present`), so a trend spanning the whole window doesn't
make every anomaly look related. A level change counts from its change point to the end of the
window, since the new level persists. Each input's signal times are in its facts as `windows`. `output` is what gets written as the
Behavior Finding if everything matches.

A metric often arrives under a different name than the rule uses: OpenTelemetry sends
`container.memory.usage`, a Prometheus exporter `container_memory_working_set_bytes`. List those
under `aliases`. An input matches the first of `metric_name`, then each alias, that has signals in
the run, so a rule written once fires on any source. The shipped packs alias `memory_usage` and
`cpu_usage` to the per-workload OpenTelemetry names the Collector's Kubernetes (kubelet) and Docker
receivers send (`container.*`, `k8s.pod.*`). Running counters such as `container.cpu.usage.total`
are left out: they only ever rise, so they'd always read as an upward trend. Add your own
Prometheus or OTel names the same way; an input without `aliases` matches `metric_name` only.

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
- Rules match metric names exactly; a metric under a name that is neither the rule's `metric_name`
  nor one of its `aliases` is not matched

## Future Direction

- promote behavior findings into cases when useful
- improve explanation formatting
- add more reusable behavior definitions
- expand test coverage for evaluation and correlation
