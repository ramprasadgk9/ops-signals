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
  I --> J[Embedding Service]
  J --> K[Qdrant]
  K --> L[Similar-Case Retrieval]
  L --> M[React UI]
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
- Qdrant indexing for operational memory

Experimental:

- richer retrieval workflows
- similarity-guided RCA assistance

Planned:

- deeper retrieval filtering
- broader analyzer coverage
- improved UI for case exploration
