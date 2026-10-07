# Core Domain Model

## Canonical Point

The normalized timeseries point is the base unit of analysis.

## Signal

Signals are analyzer outputs stored in `ops_operational_signals`.

Key fields include:

- `signal_id`
- `signal_type`
- `analyzer_id`
- `metric_name`
- `service`
- `severity`
- `confidence`
- `summary`
- `evidence_json`
- `importance_score`

## Finding

Findings are aggregated operational interpretations stored in `ops_operational_findings`.

Key fields include:

- `title`
- `summary`
- `category`
- `health_status`
- `importance_score`
- `signal_ids`
- `comparison_json`

## Case

Cases track the operational lifecycle.

Key fields include:

- `case_title`
- `case_status`
- `finding_snapshot`
- `investigation_status`
- `investigation_notes`
- `root_cause_status`
- `root_cause_summary`
- `root_cause_confidence`
- `root_cause_verified`
- `corrective_action`
- `outcome_status`
- `outcome_summary`
- `memory_status`

## Memory

Memory stores the embedding and retrieval payload for a case in Qdrant.

It is useful for:

- similar-case search
- recall of prior investigation context
- future RCA assistance

It is not proof of identical root cause.
