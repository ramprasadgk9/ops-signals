# Standalone Overview API

This page documents the read-only endpoints used by the standalone Overview workspace.
They are additive backend APIs and are not required by the Grafana plugin, Grafana panel,
MCP tools, analyzer execution, or database migrations.

## Historical Overview Summary

`GET /api/overview/summary`

Purpose: provide bounded historical aggregates for the standalone Overview page.

Query parameters:

| Parameter | Values | Default | Meaning |
| --- | --- | --- | --- |
| `window` | `24h`, `7d` | `24h` | Include findings and behavior findings created on or after the UTC window start. |

Response fields:

| Field | Definition |
| --- | --- |
| `generated_at` | UTC time when the response was generated. |
| `window` | Selected window. |
| `active_findings` | Findings in the selected window that do not have a terminal case or outcome status. Findings with no case are active. |
| `open_cases` | Cases whose `case_status` is not terminal. This is not window bounded. |
| `behavior_changes` | Behavior findings created within the selected window. |
| `impacted_services` | Distinct non-empty services across active findings in the selected window. |
| `memory_items` | Cases whose `memory_status` is `indexed`. This is not a Qdrant collection count. |
| `severity_trend` | Active findings grouped by hour for `24h` or by UTC day for `7d`. Empty buckets are omitted. |
| `category_breakdown` | Active findings grouped by `FindingEntity.category`; missing categories are returned as `unknown`. |

Terminal statuses for `active_findings` and `open_cases` are:

```text
resolved, verified, closed, completed
```

Multiple case records for one finding are not expected by the current case creation flow.
If they exist, the current frontend summary implementation keeps the last case loaded for
that `finding_id` when deciding whether the finding is active.

Example:

```json
{
  "generated_at": "2026-07-26T17:00:00Z",
  "window": "24h",
  "active_findings": 3,
  "open_cases": 1,
  "behavior_changes": 2,
  "impacted_services": 2,
  "memory_items": 1,
  "severity_trend": [
    {
      "timestamp": "2026-07-26T16:00:00Z",
      "critical": 1,
      "high": 2,
      "medium": 0,
      "low": 0
    }
  ],
  "category_breakdown": [
    {
      "category": "behavior_change",
      "count": 3
    }
  ]
}
```

Empty response:

```json
{
  "generated_at": "2026-07-26T17:00:00Z",
  "window": "24h",
  "active_findings": 0,
  "open_cases": 0,
  "behavior_changes": 0,
  "impacted_services": 0,
  "memory_items": 0,
  "severity_trend": [],
  "category_breakdown": []
}
```

Failure semantics:

| Condition | Response |
| --- | --- |
| Invalid `window` | FastAPI validation error, currently HTTP `422`. |
| Database unavailable | HTTP `500`; the standalone UI marks overview aggregates unavailable and keeps independently loaded sections usable. |
| One aggregation fails | Whole endpoint fails. No partial payload is returned. |

## Memory Statistics

`GET /api/memory/stats`

Purpose: provide authoritative case-memory status counts from PostgreSQL case metadata.

The endpoint does not enumerate Qdrant points. It counts operational case records by
`OperationalCaseEntity.memory_status`, so the total is authoritative for stored case
metadata and is not affected by pagination.

Response fields:

| Field | Definition |
| --- | --- |
| `generated_at` | UTC time when the response was generated. |
| `enabled` | Whether operational memory is enabled in backend configuration. |
| `status` | `disabled`, `initializing`, or the vector store health status such as `healthy`, `unhealthy`, or `unknown`. |
| `indexed_cases` | Cases whose `memory_status` is `indexed`. |
| `not_indexed_cases` | Cases whose `memory_status` is `not_indexed`. |
| `stale_cases` | Cases whose `memory_status` is `stale`. |
| `error_cases` | Cases whose `memory_status` is `error`. |
| `total_cases` | Total case records counted by `memory_status`. |
| `source` | Always `ops_operational_cases.memory_status`. |

Example:

```json
{
  "generated_at": "2026-07-26T17:00:00Z",
  "enabled": true,
  "status": "healthy",
  "indexed_cases": 12,
  "not_indexed_cases": 4,
  "stale_cases": 1,
  "error_cases": 0,
  "total_cases": 17,
  "source": "ops_operational_cases.memory_status"
}
```

Empty or zero-indexed response:

```json
{
  "generated_at": "2026-07-26T17:00:00Z",
  "enabled": true,
  "status": "healthy",
  "indexed_cases": 0,
  "not_indexed_cases": 1,
  "stale_cases": 0,
  "error_cases": 0,
  "total_cases": 1,
  "source": "ops_operational_cases.memory_status"
}
```

Optional dependency behavior:

| Condition | Response |
| --- | --- |
| Memory disabled | HTTP `200`, `enabled=false`, `status=disabled`, counts still come from case metadata. |
| Vector store initializing | HTTP `200`, `status=initializing`, counts still come from case metadata. |
| Qdrant unhealthy as reported by health check | HTTP `200`, health-derived `status`, counts still come from case metadata; UI shows memory unavailable for non-healthy enabled memory. |
| Qdrant collection missing | Current vector-store health does not distinguish this from an empty collection; `GET /api/memory/stats` still returns PostgreSQL case metadata counts. |
| Vector store health check raises | HTTP `500`; UI shows memory unavailable instead of zero. |

## UI Semantics

The standalone Overview page does not synthesize chart points or fake counts.
Empty arrays render empty states. Failed overview aggregates render unavailable
states. Failed or degraded memory statistics render `Memory unavailable` rather
than zero. Recent findings, cases, and behavior lists are loaded independently,
so those sections can remain usable when the overview summary endpoint fails.
