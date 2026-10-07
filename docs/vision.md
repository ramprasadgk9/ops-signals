# Vision

Ops Signals addresses a common operational problem: raw metric streams are too low-level for humans to use directly during incident review, and detector outputs alone usually stop at "something changed".

## From Operational Metrics to Operational Intelligence

Traditional observability platforms help engineers **see** what is happening through dashboards, alerts, and logs.

Ops Signals goes one step further—it helps teams **understand**, **learn**, and **improve** from operational behavior over time.

Instead of treating every incident as an isolated event, Ops Signals continuously builds operational intelligence from metrics, investigations, and historical experience.

## The Operational Problem

- Raw data is high-volume and noisy
- Detection tells you that a pattern exists, not what it means
- Teams need context, comparisons, and history to decide what matters

## The Five Layers of Operational Intelligence

### 1. Understand Operational Behavior

The first goal is to understand what is happening inside operational metrics.

Ops Signals applies multiple analyzers to the same metric and combines their outputs into explainable operational findings.

Example:

```text
Input Metric
cpu_throttled_seconds

Analyzer Results
Trend
✓ Sustained increase

Baseline Shift
✓ New operating level detected

Anomaly
✓ Two unusual windows

Operational Finding
CPU throttling behavior changed significantly compared to the previous period.
```

Instead of showing individual detector outputs, Ops Signals explains the operational significance of the metric.

### 2. Learn Operational Patterns

Every analyzed metric teaches the platform something about system behavior.

Unlike incident systems, this learning does **not** require an investigation or root cause analysis.

Ops Signals stores reusable operational patterns including:

- Metric type
- Analyzer combinations
- Statistical characteristics
- Behavior summary
- Typical evolution
- Services where the pattern occurred

Example:

```text
Pattern

Metric:
memory_usage

Behavior:
Gradual memory growth

Analyzer Evidence:
✓ Trend
✓ Baseline Shift

Summary:
Memory usage increased steadily over six hours with a permanent baseline shift.

Observed In:
checkout
payments
inventory
```

When another service shows the same analyzer pattern, Ops Signals recognizes it immediately—even if nobody has investigated it before.

This creates a continuously growing pattern memory for operational behavior.

### 3. Build Operational Knowledge

When engineers investigate important findings, they create structured operational knowledge.

Unlike pattern memory, operational knowledge captures verified human expertise.

Each completed investigation records:

- Investigation notes
- Root cause
- Resolution
- Verification
- Outcome
- Supporting evidence

Example:

```text
Finding
CPU throttling increased after deployment

↓

Investigation

↓

Root Cause
CPU requests were too low

↓

Resolution
Increase CPU requests to 1500m

↓

Verification
CPU throttling returned to normal

↓

Outcome
Resolved
```

Completed investigations become reusable knowledge for future engineers.

### 4. Operational Decision Intelligence

Pattern memory and operational knowledge work together to assist future investigations.

When a new operational issue appears, Ops Signals compares current behavior against previously learned patterns and historical investigations.

Example:

```text
Current Observation
cpu_throttled_seconds
✓ Trend
✓ Baseline Shift
✓ Anomaly

Ops Signals responds
Similar Pattern Found

Seen In:
payments
checkout
inventory

Typical Investigation
• Review CPU requests
• Review deployment history

Known Root Causes
• CPU limits too low
• Traffic increase

Successful Resolutions
• Increase CPU limits
• Scale worker replicas
```

Instead of starting every investigation from scratch, engineers begin with historical operational experience.

The goal is to reduce mean time to resolution.

### 5. Autonomous Operational Intelligence

As pattern memory and operational knowledge continue to grow, they become the foundation for autonomous operational workflows.

Rather than relying on a single AI model, specialized agents can collaborate using historical operational intelligence.

Future workflow:

```text
Alert

↓

Evidence Agent

↓

Pattern Matching Agent

↓

Historical RCA Agent

↓

Resolution Planning Agent

↓

Human Approval

↓

Automated Execution
```

This enables AI-assisted investigations while keeping humans in control.

## Core Distinctions

- Raw data: canonical time-series points
- Signal: analyzer output about a pattern or change
- Finding: aggregated operational interpretation of signals
- Behavior finding: a higher-level condition derived from multiple signals and behavior rules
- Case: a trackable investigation object with lifecycle fields
- Memory: an embedding-backed retrieval index for prior cases

## Two Types of Operational Learning

### Pattern Memory

Learns directly from analyzer evidence.

Stores:

- Operational behaviors
- Analyzer combinations
- Metric characteristics
- Pattern summaries
- Representative examples
- Cross-service observations

Answers questions such as:

- Have we seen this behavior before?
- What type of operational pattern is this?
- Which analyzers usually detect this pattern?
- Is this normal system behavior?

### Operational Knowledge

Learns from completed investigations.

Stores:

- Findings
- Investigation notes
- Root cause
- Resolution
- Verification
- Outcome

Answers questions such as:

- How was this solved previously?
- What root causes were confirmed?
- Which resolutions were successful?
- Who investigated similar incidents?

## Complete Operational Intelligence Lifecycle

```text
Operational Metrics
        │
        ▼
Multiple Analyzers
        │
        ▼
Operational Findings
        │
        ├──────────────► Pattern Memory
        │
        ▼
Investigation
        │
        ▼
Root Cause
        │
        ▼
Resolution
        │
        ▼
Verification
        │
        ▼
Operational Knowledge
        │
        ▼
Operational Assistant
        │
        ▼
Future Autonomous Operations
```

## Target Users

- Platform engineers
- SREs and operations teams
- Observability-oriented product teams
- Engineers who want a structured incident review workflow

## Principles

- Keep PostgreSQL authoritative
- Keep analysis deterministic and explainable
- Prefer explicit metadata over hidden heuristics
- Treat semantic retrieval as assistance, not proof

## Current Scope

- CSV, Prometheus, and OTLP metrics ingestion (see
  [`docs/design/otlp-metrics-ingestion-plan.md`](design/otlp-metrics-ingestion-plan.md) for the OTLP path)
- Analyzer-driven signal generation
- Finding aggregation
- Declarative behavior intelligence across multiple signals
- Operational cases
- Qdrant-backed retrieval
- Alert enrichment: Alertmanager alerts analyzed on arrival and posted to Slack with what happened,
  what changed (deploys and other change events), and whether it has been seen before (see
  [`docs/alert-enrichment.md`](alert-enrichment.md))
- Slack notifications for high-importance findings

## Non-Goals

- Autonomous remediation
- Replacing existing observability systems
- Claiming root cause from similarity alone
- Treating the assistant as an oracle: it is a retrieval and explanation layer, grounded in stored operational context

## Why Ops Signals?

Traditional observability platforms answer:

- What is happening?
- Where is the problem?

Ops Signals answers the next generation of operational questions:

- What changed?
- What does this behavior mean?
- Have we seen this operational pattern before?
- How was a similar incident resolved?
- What should I investigate next?
- Can operational knowledge be reused to reduce MTTR?
- Can future investigations become AI-assisted or autonomous?

Instead of treating every incident as a new problem, Ops Signals transforms operational observations into reusable operational intelligence—allowing every investigation to improve future operations.

## Future Direction

The project is moving toward richer case comparison, better retrieval filters, and more useful operational memory without losing determinism.
