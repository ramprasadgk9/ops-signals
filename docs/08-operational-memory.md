# Operational Memory

## Purpose

Operational memory captures a case document, embeds it, and stores it in Qdrant for semantic retrieval.

## Flow

```mermaid
flowchart LR
  A[Operational Case] --> B[Document Builder]
  B --> C[Embedding Service]
  C --> D[Qdrant Point]
  D --> E[Similarity Search]
  E --> F[Retrieved Cases]
```

## Payload Versus Document

- The document text is what gets embedded.
- The payload stores retrieval metadata.
- PostgreSQL still stores the full case record.

## Current Payload Fields

- case and finding identifiers
- service, metric, provider, category
- severity and importance score
- case lifecycle fields
- title
- embedding model
- content version
- timestamps

## Retrieval Use

The retrieval index helps surface similar cases, but it does not determine final root cause.
