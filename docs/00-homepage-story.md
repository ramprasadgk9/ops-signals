# Ops Signals Story

Ops Signals helps teams move from raw metric streams to explainable operational decisions.

## The Problem

Most observability tools can tell you that a metric moved. Fewer tools explain why it matters, how it relates to past incidents, or how to turn it into an investigation path that a human can follow.

## The Workflow

```text
Metric data
  -> analyzers
  -> signals
  -> findings
  -> cases
  -> assistant / memory
```

```mermaid
flowchart LR
  A[Upload or ingest data] --> B[Normalize points]
  B --> C[Run analyzers]
  C --> D[Produce signals]
  D --> E[Create findings]
  E --> F[Open case]
  F --> G[Ask assistant questions]
  G --> H[Reuse prior cases]
```

## What Users Gain

- Faster triage from raw data to explainable findings
- A consistent investigation lifecycle
- Clear visibility into which signals supported each result
- Historical context through searchable operational memory
- A self-hosted, open framework instead of a black box

## What It Is Not

- Not an autopilot for remediation
- Not a guarantee that similarity means identical root cause
- Not a replacement for Prometheus, Datadog, Grafana, or incident tools

## Assistant Framing

The assistant is a retrieval and explanation layer. It can summarize cases, explain repository docs, and ground answers in stored operational context, but it should not be treated as an oracle.
