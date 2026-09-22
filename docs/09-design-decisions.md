# Design Decisions

## PostgreSQL as System of Record

PostgreSQL stores the durable operational record because the project needs structured, transactional state for points, signals, findings, cases, and lifecycle data.

## Qdrant as Retrieval Index

Qdrant is used for similarity search over case embeddings. It is deliberately not the source of truth.

## Deterministic Composition

The question-answer path is designed to be deterministic instead of relying on free-form generation.

## Canonical Input

CSV is used as the portable input contract so different providers can map into the same downstream pipeline.

OTLP push ingestion is a deliberate exception: the receiver controls the shape of the DataFrame it
builds (unlike CSV, where an arbitrary uploaded file's column names are unknown ahead of time), so
it constructs canonical columns directly rather than mapping through the CSV contract. See
[`docs/otlp-metrics-ingestion-plan.md`](otlp-metrics-ingestion-plan.md).

## Explicit Metadata

The project prefers explicit fields such as service, metric, category, and status because they are easier to filter, explain, and evaluate.
