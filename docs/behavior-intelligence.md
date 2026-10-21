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

- **Findings** leads with *Combined patterns*: each matched behavior with every metric it combined
  (shape, change, window), how long they overlapped and how many conditions passed. The
  single-metric findings it was made from carry a "Part of" tag, and the Overview's Needs Attention
  lists it first as "<service> / N metrics".
- **Behavior Intelligence → Detected** shows the same evidence for the selected behavior, whether it
  is still active (seen in the last 24 hours) and a link to its card on Findings.
- **Behavior Intelligence → Patterns** lists every rule with its proof, the analyzers it needs and
  when it last fired; the known patterns to start from; and the pairs mined from your data. Admins
  open the builder there to write a rule, test it on a past run and save it to a pack.

## Rule Facts That Do Not Depend On One Analyzer

The router runs only some analyzers on a series, and often reports a steady climb as a ruptures
level change rather than a trend. A rule that means "went up" should ask `<alias>.change.upward`
(or `change.downward`), which is true when a trend, a baseline shift or a ruptures change of more
than 25% saw it, and list `trend`, `baseline_shift` and `ruptures` in that input's `analyzers`. The
shipped rules do. A rule input whose analyzers all missed the metric is skipped, and the rule
cannot match.

## Known Patterns Catalog

`config/behavior_patterns_catalog.yml` describes patterns in plain words for the Patterns tab:

- every shipped rule, with its proof: **Tested here** when benchmark scenarios require it to match
  (`tests/test_behavior_catalog.py` checks each one), otherwise **Shipped rule**;
- templates for well-known problems (consumer lag, cache misses, disk filling, saturated workers,
  retry storms), marked **Common pattern**: not tested here. *Use this pattern* opens the builder
  on a draft made from the template's signals, suggests a stored metric for each by keyword, and
  holds Test Pattern back until every signal points at one.

A template signal is `rising`, `falling` or `unusual`. "Stayed flat" and "an event at that moment"
can't be expressed: an input with no signals makes the whole rule skip.

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
