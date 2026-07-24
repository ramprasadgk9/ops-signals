# Outcome-Based Learning

Outcome-based learning records what happened after an Ops Signals finding was investigated.

The first implementation collects durable evidence only. It does not automatically modify analyzer recommendation weights, YAML scoring rules, or runtime selection behavior.

## Why This Exists

Analyzer feedback should come from investigation outcomes, not from asking users whether an algorithm name was correct.

Instead of asking:

```text
Was Ruptures correct?
```

Ops Signals asks:

```text
Did the original finding help explain the issue?
```

The backend then derives which analyzers were confirmed or rejected from the finding's signal evidence.

## Flow

The learning flow extends the normal analysis path:

```text
Time series
  -> series profile
  -> analyzer router
  -> analyzer execution
  -> findings
  -> case
  -> investigation
  -> resolution
  -> analyzer learning outcome
```

## What Gets Stored

Learning outcomes are stored in PostgreSQL in:

```text
analyzer_learning_outcomes
```

Each record stores immutable snapshots of:

- the time-series profile
- router recommendation decisions and scores
- analyzers that executed
- generated findings
- case and finding IDs
- final investigation outcome
- confirmed analyzers derived from evidence
- rejected analyzers derived from evidence
- router, feature extractor, and registry versions

## Outcome Categories

The supported learning outcomes are:

- `confirmed`
- `partially_confirmed`
- `rejected`
- `inconclusive`

Meaning:

- `confirmed`: the finding accurately represented the investigated operational behavior
- `partially_confirmed`: the finding was useful but incomplete or overstated
- `rejected`: the finding was incorrect, irrelevant, or a false positive
- `inconclusive`: the case closed without enough evidence to validate or reject it

## When A Record Is Created

A learning record is created when a case resolution moves to a final state:

- `resolved`
- `mitigated`
- `won_t_fix`

The resolution request must include:

```json
{
  "learning_outcome_status": "confirmed"
}
```

If a final resolution is submitted without that field, the backend rejects the request.

## UI Feedback

In the Grafana plugin's case resolution step, users see:

```text
Did the original finding help explain the issue?
```

Options map internally to learning outcomes:

- `Yes, it was confirmed` -> `confirmed`
- `Partially` -> `partially_confirmed`
- `No, it was incorrect` -> `rejected`
- `Could not determine` -> `inconclusive`

Analyzer names are not shown to users in this question.

## Analyzer Confirmation Logic

The backend looks at the finding's linked signal IDs.

If the outcome is `confirmed` or `partially_confirmed`:

- analyzers that produced the supporting signals are stored in `confirmed_analyzers`

If the outcome is `rejected`:

- analyzers that produced the supporting signals are stored in `rejected_analyzers`

If the outcome is `inconclusive`:

- no analyzer confirmation or rejection is inferred

## API Endpoints

Read one learning outcome:

```text
GET /api/learning-outcomes/{id}
```

Read outcomes for a case:

```text
GET /api/cases/{case_id}/learning-outcomes
```

Query outcomes:

```text
GET /api/learning-outcomes
```

Supported filters:

- `organization_id`
- `service_id`
- `metric_name`
- `analyzer_id`
- `outcome_status`
- `created_from`
- `created_to`
- `limit`
- `offset`

Create explicitly from a resolved case:

```text
POST /api/cases/{case_id}/learning-outcomes
```

Normally, creation happens through the case resolution API.

## Case Resolution Example

```json
{
  "outcome_status": "resolved",
  "outcome_summary": "The detected baseline shift matched the deployment-related CPU reduction.",
  "corrective_action": "Documented the deployment change and updated expected CPU baseline.",
  "learning_outcome_status": "confirmed",
  "root_cause_category": "deployment_change",
  "resolution_summary": "A deployment changed resource allocation and reduced steady-state CPU usage.",
  "resolved_by": "local-user"
}
```

## Important Guarantees

- Historical router scores are stored as snapshots
- Historical profiles are not recalculated after router YAML changes
- Duplicate learning records for the same case and finding are blocked
- PostgreSQL is the system of record
- No analyzer weights are changed by this implementation

## Future Use

This data can later support:

- analyzer success-rate dashboards
- recommendation tuning
- organization-specific analyzer defaults
- scoring-rule suggestions
- false-positive analysis

Those behaviors are intentionally not implemented in the first version.
