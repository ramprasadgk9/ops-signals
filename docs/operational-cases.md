# Operational Cases

Operational cases turn a finding into a trackable investigation object.

## Lifecycle

```mermaid
stateDiagram-v2
  [*] --> open
  open --> investigating
  investigating --> rca_in_progress
  rca_in_progress --> resolved
  resolved --> closed
```

## Example Lifecycle

1. A finding (or a behavior finding) is promoted into a case.
2. Investigation notes are added during review.
3. RCA fields are filled in when a cause is known.
4. Corrective action and outcome are recorded.
5. The case is indexed into Qdrant for future retrieval.

## Case Fields

- investigation status
- investigation notes
- RCA status
- RCA summary
- RCA confidence
- verification flag
- corrective action
- outcome status
- outcome summary
- memory status

## Purpose

Cases help teams preserve context across investigation, RCA, and post-resolution review.

## Ticketing Integration & Comment Promotion

When an operational case is linked to an external ticketing provider (e.g., Jira Cloud):
1. **Activity Feed Synchronization**: Remote ticket status changes and comments are synced into the case's external activity feed.
2. **1-Click Note Promotion**: Operators can elevate relevant external comments into official `investigation_notes` via `POST /api/cases/{case_id}/ticket/events/{event_id}/promote-to-note`.
   - Attaches provenance: `[{PROVIDER} note from {Author}]: {summary}`.
   - Automatically advances `investigation_status` from `not_started` to `in_progress`.
   - If the case was previously indexed in operational memory, flags `memory_status = "stale"` to ensure vector embeddings stay synchronized with PostgreSQL.
   - Enforces idempotency to prevent duplicate notes.
3. **AI Root Cause & Resolution Enrichment**: AI suggestion endpoints (`/api/cases/{case_id}/rca/suggest` and `/api/cases/{case_id}/resolution/suggest`) dynamically ingest external team observations from ticketing, filtering out already-promoted comments to eliminate duplicate tokens while capturing active incident context.
4. **Zero-Click AI Comment Relevance Triage**:
   - Automated evaluation: When new comments arrive via periodic synchronization or inbound webhooks, `CommentTriageService` evaluates unpromoted comments against case telemetry using structured AI output (`CommentTriageEvaluation`).
   - High-confidence operational clues (`is_relevant_clue=True`, `confidence >= 0.75`) detailing diagnostic discoveries, root cause hypotheses, or remediation actions are automatically promoted into case notes with provenance `[{PROVIDER} clue from {Author} (AI auto-promoted)]: {summary}`.
   - Administrative noise and project management chatter (e.g., sprint assignments, meeting schedules, general acknowledgments) remain in the activity feed without cluttering official case notes.
   - On-demand triage: Operators can trigger immediate AI triage at any time via `POST /api/cases/{case_id}/ticket/triage-comments` or the `[⚡ AI Triage]` button in the UI.
   - Graceful degradation: If AI services are unavailable or fail, comment triage fails closed, leaving comments unpromoted for manual operator review without breaking ticket synchronization.

5. **Outbound Resolution Synchronization**:
   - When an operator approves and verifies an RCA and resolves/mitigates an operational case, Ops Signals atomically enqueues a transactional outbox operation (`resolve_ticket`).
   - The Jira adapter formats an Atlassian Document Format (ADF) closing resolution comment containing the verified root cause, corrective action, outcome summary, and deep link back to Ops Signals.
   - Fail-safely transitions the linked Jira ticket to "Done" / "Resolved" if an eligible transition exists in the Jira project workflow.
   - Operators can also manually trigger outbound resolution sync at any time via `POST /api/cases/{case_id}/ticket/resolve`.
6. **Instant Webhook Ingestion & Configuration**:
   - Operators can retrieve setup details and delivery health via `GET /api/integrations/ticketing/{provider}/webhook-info`.
   - Incoming Jira webhooks (`POST /api/integrations/ticketing/{provider}/webhook`) process comments and status changes instantaneously with zero polling latency, verified via HMAC-SHA256 signatures and deduped against `ticket_webhook_deliveries`.

## Filtering by Service

The **Cases** page has a **Service** dropdown next to the search box when the cases cover two or more
services. Each case keeps the service of the finding it was opened from; the tab counts follow the
filter, and the URL keeps it (`/cases?service=payments-api`). `GET /api/cases?service=` filters in the
database before applying `limit`, so a service's older cases aren't dropped when other services have
newer ones.

## Current State

Case tracking exists in the backend models, standalone web frontend, and operational memory pipeline.
