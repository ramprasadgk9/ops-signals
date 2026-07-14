# Vision

Ops Signals addresses a common operational problem: raw metric streams are too low-level for humans to use directly during incident review, and detector outputs alone usually stop at "something changed".

## Operational Problem

- Raw data is high-volume and noisy
- Detection tells you that a pattern exists, not what it means
- Teams need context, comparisons, and history to decide what matters

## Progression

```text
Detection
-> Interpretation
-> Investigation
-> Historical Knowledge
-> Future RCA Assistance
```

## Core Distinctions

- Raw data: canonical time-series points
- Signal: analyzer output about a pattern or change
- Finding: aggregated operational interpretation of signals
- Behavior finding: a higher-level condition derived from multiple signals and behavior rules
- Case: a trackable investigation object with lifecycle fields
- Memory: an embedding-backed retrieval index for prior cases

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

- CSV-based ingestion
- Analyzer-driven signal generation
- Finding aggregation
- Declarative behavior intelligence across multiple signals
- Operational cases
- Qdrant-backed retrieval

## Non-Goals

- Autonomous remediation
- Replacing existing observability systems
- Claiming root cause from similarity alone

## Future Direction

The project is moving toward richer case comparison, better retrieval filters, and more useful operational memory without losing determinism.
