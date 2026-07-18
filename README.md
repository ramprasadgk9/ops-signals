# Ops Signals

Ops Signals is a vendor-neutral Operational Intelligence framework that transforms time-series data into explainable findings, investigation cases, and searchable operational memory.

It is designed to help teams move from raw metrics to actionable operational context without replacing existing observability or incident platforms.

## Problem

Raw time-series points are noisy, high-volume, and hard to reason about directly. Detector outputs alone can tell you that something changed, but not what it means, how severe it is, or how it relates to prior incidents.

Ops Signals adds structure around that data by turning canonical CSV inputs into:

- normalized time-series points
- analyzer-generated signals
- aggregated operational findings
- behavior findings from declarative multi-signal rules
- operational cases with investigation and RCA lifecycle fields
- Qdrant-backed semantic retrieval for similar cases
- analyzer recommendations for selecting suitable metric analyzers from a sample

## What It Does

- Ingests canonical CSV time-series data
- Normalizes and stores points in PostgreSQL
- Runs pluggable analyzers for baseline shift, anomaly, and trend detection
- Aggregates signals into operational findings
- Evaluates declarative behavior definitions across multiple signals
- Creates operational cases for investigation, RCA, resolution, and outcome tracking
- Indexes case summaries into Qdrant for historical similarity search
- Serves a React frontend and FastAPI backend for review and exploration

## What Makes It Different

- It separates **source of truth** storage from **semantic retrieval**
- It treats detector output as input to higher-level operational interpretation
- It adds a separate behavior reasoning layer for cross-metric patterns
- It emphasizes deterministic, explainable answers over free-form generation
- It keeps PostgreSQL as the system of record and Qdrant as a retrieval index

This is not a replacement for Prometheus, Datadog, Grafana, or incident-management platforms.
It does not currently perform autonomous remediation.
Historical similarity does not prove two cases share the same root cause.

## Current Capabilities

- Canonical CSV ingestion
- Normalization into PostgreSQL
- Analyzer registry and capability-driven question model
- Signal generation and aggregation into findings
- Behavior intelligence for cross-metric operational patterns
- Operational case lifecycle fields for investigation, RCA, corrective action, and outcome
- Qdrant-based operational memory for similar-case retrieval
- Analyzer recommendation flow for profiling metric samples and ranking analyzers
- React UI for findings, questions, signals, cases, and history

## Operational Intelligence Assistant

Ops Signals includes a single chat interface that routes questions across historical cases and application knowledge.
The assistant should be treated as a retrieval and explanation layer, not as an oracle.

### What users can expect

- Ask natural-language questions about findings, cases, signals, behaviors, analyzers, and architecture
- Retrieve relevant cases, documentation, and evidence from vector search
- Get plain-language summaries grounded in stored operational data and repo docs
- Ask follow-up questions like "what changed?", "have we seen this before?", or "what is behavior intelligence?"
- See source links, case IDs, or documentation references used in the answer

### What users should not expect

- Guaranteed root-cause truth from the chat output alone
- Autoremediation or direct system changes
- Free-form guesses without evidence
- Answers that go beyond the stored data, docs, and retrieval context
- Replacement for the underlying analyzers, rules, or source observability tools

## High-Level Architecture

```text
Canonical CSV
  -> Validation
  -> Normalization
  -> PostgreSQL
  -> Analyzer Registry
  -> Signals
  -> Finding Aggregator
  -> Operational Findings
  -> Operational Cases
  -> Embedding Service
  -> Qdrant
  -> Similar-Case Retrieval
  -> Analyzer Recommendation
  -> React UI
```

## Quick Start

```bash
docker compose up -d postgres qdrant
python -m intelligence.cli init-db --config config.yaml
python -m intelligence.cli run --config config.yaml
uvicorn backend.app.main:app --reload --port 8000
cd frontend
npm install
npm run dev
```

## Canonical CSV Input

```csv
timestamp,service,metric_name,value,env,host,namespace,pod,unit,metric_type
2026-07-12T14:00:00Z,payments-api,cpu_usage,78.2,prod,ip-10-0-1-5,,payments-7d8c9,percent,gauge
2026-07-12T14:01:00Z,payments-api,cpu_usage,84.6,prod,ip-10-0-1-5,,payments-7d8c9,percent,gauge
```

## YAML Configuration

```yaml
output:
  save_signals: true
  save_findings: true
  save_embeddings: true
memory:
  enabled: true
  provider: qdrant
  vector_store:
    url: http://localhost:6333
    collection_name: operational_cases
  embedding:
    model: sentence-transformers/all-MiniLM-L6-v2
    normalize_embeddings: true
```

## Example Operational Finding

```json
{
  "title": "CPU spike on payments-api",
  "summary": "The current window is materially above the previous baseline and shows sustained elevated utilization.",
  "category": "anomaly",
  "health_status": "critical",
  "importance_score": 0.93
}
```

## Example Operational Case Lifecycle

1. A finding is promoted into a case.
2. Investigation notes are added during review.
3. RCA fields are filled in when a cause is known.
4. Corrective action and outcome are recorded.
5. The case is indexed into Qdrant for future retrieval.

## PostgreSQL Versus Qdrant

- PostgreSQL stores analysis runs, normalized points, signals, findings, cases, and investigation state.
- Qdrant stores embeddings and retrieval metadata for semantic lookup.
- PostgreSQL is the system of record.
- Qdrant is the semantic retrieval index.

## Screenshots

No screenshots are checked into this repository yet. Add UI captures here when stable screenshots are available.

## Current Limitations

- No autonomous remediation
- No claim that similarity equals root-cause equivalence
- Historical retrieval depends on the quality of stored summaries and metadata
- Some memory workflows are still evolving and should be treated as operational assistance, not automation
- Analyzer recommendation scoring is deterministic and currently profile-based; it does not yet run deeper analyzer-specific probes

## Roadmap

- Expand analyzer coverage
- Improve operational memory retrieval filters
- Add richer case comparison and retrieval views
- Extend evaluation datasets for regression checks
- Document release and contribution workflows more fully

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

See [LICENSE](LICENSE).
