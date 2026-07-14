Feature 1: Configurable Behavior Rules

Description (2 lines):

Allow users to define operational behaviors by combining outputs from multiple analyzers on one or more metrics. Instead of hardcoding rules, users configure which analyzer signals must occur together before generating a higher-level finding.

Example: CPU Throttling

CPU Usage
  ├─ Anomaly ✓
  ├─ Trend ↑
  └─ Change Point ✗

CPU Throttled Seconds
  ├─ Trend ↑
  └─ Anomaly ✓

↓ Behavior Rule

Finding:
Possible CPU throttling detected
Feature 2: Cross-Metric Behavior Analysis

Description (2 lines):

Analyze multiple related metrics together to identify operational conditions that cannot be detected from a single metric. The framework correlates analyzer outputs across metrics before producing a unified operational finding.

Example: Server Slow

CPU Usage
  ├─ Trend ↑
  └─ Anomaly ✓

Memory Usage
  ├─ Trend ↑
  └─ Baseline Shift ✓

↓ Cross-Metric Correlation

Finding:
Server performance degradation detected.
CPU and memory both show sustained abnormal behavior.

Why this is powerful

Currently:

Metric
   ↓
Analyzer
   ↓
Finding

Future:

Metric 1
      ↓
Analyzers
      ↓
Signals
           \
            \
Metric 2 ----> Behavior Rule Engine
            /
Metric 3 ---/
      ↓
Operational Finding

Now you're no longer saying:

"I wrap STUMPY and Kats."

You're saying:

"I provide a configurable behavior engine that synthesizes analyzer outputs across multiple metrics into higher-level operational findings."