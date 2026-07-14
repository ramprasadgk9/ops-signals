# Architecture

## Overview

```mermaid
flowchart LR
  A[Canonical Time Series] --> B[Validation]
  B --> C[Normalization]
  C --> D[PostgreSQL]
  D --> E[Analyzer Registry]
  E --> F[Signals]
  F --> G[Finding Aggregator]
  G --> H[Operational Findings]
  H --> I[Operational Cases]
  I --> J[Behavior Intelligence]
  J --> K[Behavior Findings]
  K --> L[Embedding Service]
  L --> M[Qdrant]
  M --> N[Similar-Case Retrieval]
  N --> O[React UI]
```

## Layer Responsibilities

- Canonical Time Series: source metric input
- Validation: checks structure and required fields
- Normalization: converts provider-specific inputs into a consistent schema
- PostgreSQL: persistent system of record
- Analyzer Registry: declares which analyzers and capabilities are available
- Signals: analyzer outputs
- Finding Aggregator: groups signals into higher-level findings
- Operational Findings: ranked interpretations of signal sets
- Operational Cases: investigation objects with lifecycle state
- Behavior Intelligence: deterministic rule evaluation across multiple signals
- Behavior Findings: higher-level operational conditions produced by behavior rules
- Embedding Service: converts case text into vectors
- Qdrant: semantic retrieval index for similar cases
- Similar-Case Retrieval: query-time search over indexed case vectors
- React UI: user-facing exploration and review surface

## Backend

The FastAPI backend exposes ingestion, analysis, finding, case, capability, and memory routes. It also initializes PostgreSQL and Qdrant services at startup.

## Frontend

The React frontend presents overview, findings, cases, signals, questions, history, and settings pages.

## Source of Truth and Retrieval Index

### PostgreSQL

PostgreSQL stores:

- analysis runs
- normalized points
- signals
- findings
- cases
- investigation notes and lifecycle fields

### Qdrant

Qdrant stores:

- embeddings for case documents
- retrieval metadata for semantic search

Qdrant should be treated as a retrieval index, not the authoritative record.

## Current State

Implemented:

- CSV ingestion into PostgreSQL
- analyzer-based signal generation
- operational findings and cases
- behavior intelligence rule evaluation
- Qdrant indexing for operational memory

Experimental:

- richer retrieval workflows
- similarity-guided RCA assistance
- behavior finding promotion into cases

Planned:

- deeper retrieval filtering
- broader analyzer coverage
- improved UI for case exploration
