# Pluggable Case Ticketing Architecture Plan (Jira Cloud Reference Implementation)

**Status:** Proposed (Technical Design Document)  
**Extends:** [`docs/07-operational-cases.md`](../../07-operational-cases.md) (operational case lifecycle),  
[`ADR-004`](../../adr/ADR-004-postgresql-system-of-record.md) (PostgreSQL as system of record),  
[`ADR-005`](../../adr/ADR-005-qdrant-retrieval-index.md) (Qdrant as derived retrieval index),  
[`backend/app/security.py`](../../../backend/app/security.py) (API token & public routes).  

---

## 1. Executive Summary & Vision

Ops Signals analyzes telemetry anomalies, generates findings, and drives operational cases to root-cause investigation and resolution. Today, cases live in PostgreSQL as the authoritative system of record and are indexed into Qdrant for semantic similarity retrieval. However, enterprise operations teams collaborate across external issue-tracking and ITSM platforms—predominantly **Jira Cloud**, **ServiceNow**, **GitHub Issues**, and **Linear**.

### The Vision: Plug-and-Play Ticketing Architecture
Instead of coupling Ops Signals to a bespoke, one-off Jira script that mixes delivery state into case models and breaks when another tool is introduced, Ops Signals establishes a **pluggable ticketing architecture**:
1. **Strict Single-Authority Model:** PostgreSQL remains the immutable system of record. Case lifecycle status is derived exclusively from internal case domain milestones (investigation, RCA verification, corrective action). External ticket updates are captured as non-destructive link metadata and external timeline events—never modifying internal case status or notes.
2. **Durable Transactional Outbox with Ambiguous-Outcome Circuit Breakers (`ticket_operations`):** Outbound operations return `202 Accepted` immediately and process reliably through a durable outbox table with idempotency keys, explicit retry backoff (`available_at`), and per-claim random lease tokens with active heartbeat renewal via independent database sessions. On any uncertain network outcome, operations transition to `ambiguous_outcome`; negative JQL lookups are never treated as proof of absence, completely preventing duplicate tickets.
3. **Atomic Completion & Link Persistence:** Conditional lease ownership verification and `case_ticket_links` upserts are committed in a single database transaction, ensuring no operation can complete without its link record.
4. **Normalized Link, Event & Delivery Entities (`case_ticket_links`, `case_ticket_events`, `ticket_webhook_deliveries`):** Webhook delivery IDs (`X-Atlassian-Webhook-Identifier`) are isolated to delivery receipts, while `case_ticket_events` uses canonical domain IDs (`jira_comment_{id}`) across both webhooks and periodic polling, eliminating duplicate timeline entries.
5. **Deep Module Façade (`CaseTicketing`) & Role Protocols:** Granular role protocols (`TicketCreator`, `TicketSynchronizer`, `WebhookVerifier`, `WebhookParser`) operate on pure value models (`TicketDraft`, `TicketView`, `TicketOperationView`, `TicketEventView`), hiding persistence and ORM entities from providers and callers.
6. **Jira Cloud v3 Reference Adapter:** Phase 1 delivers an end-to-end Jira Cloud adapter using Atlassian Document Format (ADF), REST API v3, and native label indexing for distributed idempotency, secured with authentic HMAC-SHA256 webhook signatures integrated via a provider-agnostic dynamic security exemption.

---

## 2. Core Architectural Principles & Authority Model (P0)

### A. Strict Lifecycle Integrity & Zero Mutation
In Ops Signals, `case_status` and `investigation_status` are computed dynamically via `_compute_case_status` in [`backend/app/api/cases.py`](../../../backend/app/api/cases.py):
- Any item in `case.investigation_notes` $\rightarrow$ `investigation_status = "in_progress"`
- `root_cause_summary` AND `corrective_action` present $\rightarrow$ `case_status = "in_progress"`
- `root_cause_verified` AND `corrective_action` AND `outcome_summary` present $\rightarrow$ `case_status = "resolved"`, `investigation_status = "completed"`

A design that appends remote Jira comments to `case.investigation_notes` or maps Jira status directly to `case.case_status` directly violates domain integrity:
- Inbound comments would prematurely flip a case's `investigation_status` from `"not_started"` to `"in_progress"`.
- Inbound statuses would dual-master conflict and be wiped out on subsequent case saves.

**Architectural Decision:**
- **Phase 1 (Outbound-Only):** External tickets are derived projections *from* the operational case.
- **Phases 2 & 3 (Inbound Sync & Webhooks):** External changes do **not** write to `ops_operational_cases`. Instead:
  1. Remote workflow status is stored in `case_ticket_links.observed_remote_status` (e.g., `"In Progress"`, `"Done"`).
  2. Remote comments and updates are stored in a dedicated, deduplicated `case_ticket_events` table keyed by `(provider, remote_event_id)`.
  3. Inbound events are presented in the UI as external activity. Promoting a remote resolution to an Ops Signals resolved case requires explicit operator action with required RCA verification fields.

### B. Isolated Qdrant Memory Pipeline
The semantic memory pipeline (`CaseMemoryIndexer` $\rightarrow$ Qdrant `operational_cases` collection) continues reading exclusively from PostgreSQL. Ticketing integration touches neither vector embeddings nor Qdrant storage.

---

## 3. High-Level System Architecture

```mermaid
flowchart TB
  subgraph ClientUI["Client Surfaces (Grafana Plugin / Web UI)"]
    CaseView["Case Details View\n- Ticket Pill (display_key, observed_status)\n- Action Button (Create / Sync / Retry)\n- Ambiguous Outcome Resolver\n- External Activity Feed"]
  end

  subgraph API["FastAPI Layer"]
    CaseEndpoints["POST /api/cases/{id}/ticket/create\nPOST /api/cases/{id}/ticket/sync\nPOST /api/cases/{id}/ticket/retry\nPOST /api/cases/{id}/ticket/link\nGET /api/cases/{id}/ticket"]
    WebhookEndpoint["POST /api/integrations/ticketing/{provider}/webhook\n(Dynamic security exemption, HMAC-SHA256 verified)"]
  end

  subgraph CoreModule["Deep Module Boundary: CaseTicketing"]
    Façade["CaseTicketing Façade\n- SessionFactory injection\n- Pure Value Models (TicketDraft, TicketView)\n- request_create(case_id)\n- request_sync(case_id)\n- retry_operation(operation_id)\n- link_existing_ticket(case_id, display_key)\n- process_pending_operations()\n- accept_webhook(provider, raw_body, headers)"]
    
    subgraph RoleProtocols["Role Protocols (Pure Data Contracts)"]
      Creator["TicketCreator (Protocol)"]
      Syncer["TicketSynchronizer (Protocol)"]
      Verifier["WebhookVerifier (Protocol)"]
      Parser["WebhookParser (Protocol)"]
    end
    
    Façade --> RoleProtocols
  end

  subgraph OutboxEngine["Durable Transactional Outbox"]
    OutboxTable[("ticket_operations\n(PostgreSQL)\nstatus, available_at, lease_token, lease_expires_at")]
    Worker["Outbox Worker\n(Short-lived DB session per step)"]
    Heartbeat["Heartbeat Task\n(Dedicated short-lived session per pulse)"]
    Worker -.->|"Claim leased operation"| OutboxTable
    Heartbeat -.->|"Renew lease_expires_at"| OutboxTable
  end

  subgraph DataLayer["Authoritative Storage (PostgreSQL)"]
    CasesTable[("ops_operational_cases\n(Domain system of record - UNCHANGED)")]
    LinksTable[("case_ticket_links\n(case_id, provider, remote_id, display_key,\nobserved_remote_status, sync_cursor)")]
    EventsTable[("case_ticket_events\n(case_id, provider, remote_event_id,\nevent_type, author, summary, occurred_at)")]
    DeliveriesTable[("ticket_webhook_deliveries\n(provider, delivery_id, processed_at)")]
  end

  subgraph Adapters["Provider Implementations"]
    JiraAdapter["JiraTicketProvider (Cloud v3)\n- Reconcile via native JQL labels\n- Ambiguous-outcome protection\n- Builds ADF JSON\n- Basic Auth (Email + Token)\n- X-Hub-Signature HMAC Verifier\n- Canonical event ID extraction"]
    ServiceNowAdapter["ServiceNowTicketProvider (Future)"]
    GitHubAdapter["GitHubIssuesTicketProvider (Future)"]
    
    RoleProtocols -.-> JiraAdapter
    RoleProtocols -.-> ServiceNowAdapter
    RoleProtocols -.-> GitHubAdapter
  end

  subgraph ExternalSaaS["External Platforms"]
    JiraAPI["Atlassian Jira Cloud REST API v3\n/rest/api/3/issue\n/rest/api/3/search\n/rest/api/3/issue/{key}/comment"]
    JiraWebhooks["Jira Webhook Sender"]
  end

  CaseView -->|"Triggers action"| CaseEndpoints
  CaseEndpoints --> Façade
  Façade -->|"Writes operation (atomic)"| OutboxTable
  Façade -->|"Returns 202 Accepted"| CaseEndpoints
  Worker --> JiraAdapter
  JiraAdapter -->|"1. Pre-retry check (if attempts > 1)"| JiraAPI
  JiraAdapter -->|"2. HTTPS POST (ADF + labels)"| JiraAPI
  Worker -->|"Atomic TX: mark completed + upsert link"| DataLayer
  
  JiraWebhooks -->|"POST X-Hub-Signature"| WebhookEndpoint
  WebhookEndpoint --> Façade
  Façade -->|"Deduplicate delivery_id"| DeliveriesTable
  Façade -->|"Updates observed_remote_status"| LinksTable
  Façade -->|"Appends canonical domain event"| EventsTable
```

---

## 4. Durable Transactional Outbox & Reliability Engine (P0 & P1)

### A. Schema: `ticket_operations`
```sql
CREATE TABLE ticket_operations (
    id VARCHAR(64) PRIMARY KEY,                  -- UUID
    case_id INTEGER NOT NULL REFERENCES ops_operational_cases(id) ON DELETE CASCADE,
    provider VARCHAR(32) NOT NULL,              -- 'jira', 'servicenow', etc.
    operation_type VARCHAR(32) NOT NULL,        -- 'create_ticket', 'sync_ticket'
    idempotency_key VARCHAR(128) NOT NULL,      -- Unique per logical operation
    status VARCHAR(32) NOT NULL DEFAULT 'pending', -- pending, processing, ambiguous_outcome, completed, failed, dead_letter
    attempts INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 5,
    available_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(), -- Retry timing backoff
    lease_token VARCHAR(64),                    -- Cryptographically random UUID per claim
    lease_expires_at TIMESTAMP WITH TIME ZONE,  -- Worker lease timeout
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    error_message TEXT,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX uq_ticket_ops_idempotency ON ticket_operations(idempotency_key);
CREATE INDEX idx_ticket_ops_claimable ON ticket_operations(status, available_at, lease_expires_at);
CREATE INDEX idx_ticket_ops_case_id ON ticket_operations(case_id);
```

### B. Correct Lease Claim & Recovery Predicate (P0)
To guarantee that crashed workers are safely reclaimed without leaving tasks stuck in `'processing'`, the claim query selects **both** pending/failed rows past their backoff **and** processing rows whose leases have expired:
```sql
UPDATE ticket_operations
SET status = 'processing',
    lease_token = :random_claim_uuid,           -- Fresh UUID per claim (uuid.uuid4())
    lease_expires_at = NOW() + INTERVAL '60 seconds',
    attempts = attempts + 1,
    updated_at = NOW()
WHERE id = (
    SELECT id FROM ticket_operations
    WHERE (
        (status IN ('pending', 'failed') AND available_at <= NOW())
        OR (status = 'processing' AND lease_expires_at < NOW())
    )
    AND attempts < max_attempts
    ORDER BY created_at ASC
    LIMIT 1
    FOR UPDATE SKIP LOCKED
)
RETURNING *;
```

### C. Session Ownership & Heartbeat Lease Renewal (P1)
In FastAPI / SQLAlchemy, a single request-scoped `Session` cannot be concurrently accessed by an async heartbeat task while the worker executes external HTTP calls.

**Architecture:**
- `CaseTicketing` is injected with a `session_factory: Callable[[], Session]`.
- The worker opens a short-lived session for claiming operations, and another short-lived session for final completion.
- The heartbeat runs as an independent coroutine using its own short-lived session per pulse:
  ```python
  async def _heartbeat_loop(session_factory, op_id: str, lease_token: str, stop_event: asyncio.Event):
      while not stop_event.is_set():
          try:
              await asyncio.wait_for(stop_event.wait(), timeout=20.0)
              break
          except asyncio.TimeoutError:
              with session_factory() as session:
                  session.execute(
                      text("""
                          UPDATE ticket_operations
                          SET lease_expires_at = NOW() + INTERVAL '60 seconds',
                              updated_at = NOW()
                          WHERE id = :op_id
                            AND lease_token = :token
                            AND status = 'processing'
                      """),
                      {"op_id": op_id, "token": lease_token}
                  )
                  session.commit()
  ```

### D. Single Atomic Transaction: Completion & Link Persistence (P0)
Marking an operation completed and inserting `case_ticket_links` must occur within a **single database transaction**. If completion is written first and the process crashes before writing the link, the system is left with a completed outbox row but no ticket link, permanently preventing reconciliation.

**Single Transaction Contract:**
```python
with session_factory() as session:
    with session.begin():
        # 1. Conditional lease ownership check and completion update
        result = session.execute(
            text("""
                UPDATE ticket_operations
                SET status = 'completed',
                    lease_token = NULL,
                    lease_expires_at = NULL,
                    updated_at = NOW()
                WHERE id = :op_id
                  AND lease_token = :lease_token
                  AND lease_expires_at > NOW()
                  AND status = 'processing'
            """),
            {"op_id": operation_id, "lease_token": claim_uuid}
        )
        if result.rowcount == 0:
            # Lease expired or claimed by another worker; roll back immediately
            raise LeaseLostError(f"Lease lost for operation {operation_id}; rolling back.")

        # 2. Upsert ticket link in the EXACT SAME database transaction
        session.execute(
            text("""
                INSERT INTO case_ticket_links (
                    case_id, provider, remote_id, display_key, ticket_url,
                    observed_remote_status, updated_at
                )
                VALUES (
                    :case_id, :provider, :remote_id, :display_key, :ticket_url,
                    :observed_status, NOW()
                )
                ON CONFLICT (case_id, provider) DO UPDATE SET
                    remote_id = EXCLUDED.remote_id,
                    display_key = EXCLUDED.display_key,
                    ticket_url = EXCLUDED.ticket_url,
                    observed_remote_status = EXCLUDED.observed_remote_status,
                    updated_at = NOW()
            """),
            {
                "case_id": draft.case_id,
                "provider": "jira",
                "remote_id": result_ticket.remote_id,
                "display_key": result_ticket.display_key,
                "ticket_url": result_ticket.ticket_url,
                "observed_status": result_ticket.observed_remote_status or "To Do",
            }
        )
        # Commit guarantees both succeed or both roll back together
```

### E. Distributed Idempotency & Ambiguous-Outcome Circuit Breakers (P0)

#### 1. Searchable Origin Labels
Jira Cloud natively indexes the `labels` field for instant JQL search out of the box with zero app installation. When creating an issue, `JiraTicketProvider` tags the issue with deterministic labels:
```json
{
  "fields": {
    "project": {"key": "OPS"},
    "summary": "[Ops Signals] Telemetry Anomaly in checkout-service",
    "issuetype": {"name": "Task"},
    "labels": [
      "ops-signals",
      "ops-signals-case-14",
      "ops-signals-op-op_9f8d1c7e2b"
    ],
    "description": { ... }
  }
}
```

#### 2. Negative JQL Lookup is NOT Proof of Absence (P0)
Jira search indexing operates asynchronously with variable latency (eventual consistency). During load spikes, an issue may take several seconds or minutes to be indexed and return in JQL search results.
- **Rule:** A negative search result (`issues == []`) **never** authorizes an automated worker to retry a `POST /rest/api/3/issue` call after an uncertain outcome.
- **Uncertain Outcomes:** Network timeout, connection drop/reset, HTTP 502/503/504 Bad Gateway, or worker crash during an in-flight POST.
- **Circuit Breaker:** Whenever an uncertain outcome occurs:
  1. The worker marks the operation as `status = 'ambiguous_outcome'`.
  2. The automated worker **immediately stops** retrying.
  3. The UI presents an operator resolution modal with explicit manual choices:
     - **Check Jira Again:** Queries JQL search again after indexing has had time to catch up.
     - **Link Manually:** Operator pastes the issue key (e.g. `OPS-143`) directly.
     - **Force Create:** Operator confirms that no issue exists in Jira and explicitly forces a fresh create call.

### F. Explicit Retry Timing & Key Lifecycle (P1)
- **Exponential Backoff:** On deterministic transient failure (e.g. HTTP 429 rate limit or HTTP 500 error before request transmission), `available_at` is scheduled with jittered exponential backoff:
  $$\text{available\_at} = \text{NOW}() + (2^{\text{attempts}} \times 2\text{ seconds}) \pm \text{jitter}$$
- **Terminal Failure:** If `attempts >= max_attempts`, `status` transitions to `'dead_letter'`.
- **Manual Retry Action:** The UI offers a **"Retry"** button when status is `failed` or `dead_letter`.
  Calling `retry_operation(operation_id)` explicitly **reopens** the existing record:
  ```sql
  UPDATE ticket_operations
  SET status = 'pending',
      attempts = 0,
      available_at = NOW(),
      lease_token = NULL,
      lease_expires_at = NULL,
      error_message = NULL,
      updated_at = NOW()
  WHERE id = :operation_id
    AND status IN ('failed', 'dead_letter');
  ```
  This preserves the single logical operation per case lifecycle and avoids unique index collisions on `uq_ticket_ops_idempotency`.

---

## 5. Normalized Link, Event and Delivery Data Models (P0 & P1)

### Table 1: `case_ticket_links` (Active Ticket Association)
```sql
CREATE TABLE case_ticket_links (
    id SERIAL PRIMARY KEY,
    case_id INTEGER NOT NULL REFERENCES ops_operational_cases(id) ON DELETE CASCADE,
    provider VARCHAR(32) NOT NULL,              -- 'jira', 'servicenow', 'github'
    remote_id VARCHAR(64) NOT NULL,             -- Jira numeric ID (e.g. "10042")
    display_key VARCHAR(64) NOT NULL,           -- Jira human key (e.g. "OPS-142")
    ticket_url TEXT NOT NULL,                   -- Clickable URL
    observed_remote_status VARCHAR(64),         -- e.g. "To Do", "In Progress", "Done"
    sync_cursor VARCHAR(255),                   -- Cursor/timestamp for incremental pull
    last_synced_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_case_provider UNIQUE (case_id, provider)
);

CREATE INDEX idx_case_ticket_links_remote ON case_ticket_links(provider, remote_id);
```

### Table 2: `case_ticket_events` (Immutable Canonical Timeline Events) (P0 & P1)
```sql
CREATE TABLE case_ticket_events (
    id SERIAL PRIMARY KEY,
    case_id INTEGER NOT NULL REFERENCES ops_operational_cases(id) ON DELETE CASCADE,
    provider VARCHAR(32) NOT NULL,
    remote_event_id VARCHAR(128) NOT NULL,      -- Canonical domain ID (e.g. 'jira_comment_10042')
    event_type VARCHAR(32) NOT NULL,            -- 'comment_created', 'status_changed', 'issue_updated'
    author VARCHAR(255),                        -- Remote author name / email
    summary TEXT NOT NULL,                      -- Comment text or change summary
    payload JSONB NOT NULL DEFAULT '{}'::jsonb, -- Raw provider payload
    occurred_at TIMESTAMP WITH TIME ZONE NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_ticket_event_provider_remote_id UNIQUE (provider, remote_event_id)
);

CREATE INDEX idx_ticket_events_case_timeline ON case_ticket_events(case_id, occurred_at DESC);
```

### Table 3: `ticket_webhook_deliveries` (Webhook Delivery Receipts) (P1)
```sql
CREATE TABLE ticket_webhook_deliveries (
    id SERIAL PRIMARY KEY,
    provider VARCHAR(32) NOT NULL,
    delivery_id VARCHAR(128) NOT NULL,          -- e.g. X-Atlassian-Webhook-Identifier header
    processed_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_webhook_delivery UNIQUE (provider, delivery_id)
);
```

### Canonical Event Identity vs. Delivery Receipts (P1)
Jira documentation specifies that `X-Atlassian-Webhook-Identifier` tracks the *HTTP delivery* across retry attempts, not the underlying domain entity. To prevent duplicate events between webhooks and polling:
1. **Delivery Deduplication:**
   When a webhook arrives, `accept_webhook` checks `ticket_webhook_deliveries(provider, delivery_id)`. If the receipt exists, it returns HTTP `200 OK` immediately (idempotent receipt acknowledgement) without re-processing.
2. **Canonical Domain Event Identity:**
   Both webhooks and polling (`pull_remote_ticket`) map domain events to identical canonical keys:
   - **Comments:** `remote_event_id = f"jira_comment_{comment_id}"` (from `body["comment"]["id"]` or polling REST API).
   - **Changelog / Transitions:** `remote_event_id = f"jira_changelog_{changelog_id}"` (from `body["changelog"]["id"]` or polling REST API).
   
Because `case_ticket_events` has a unique constraint on `(provider, remote_event_id)`, comments delivered via webhook and subsequently encountered during polling are deduplicated natively.

---

## 6. Deep Module Boundary: `CaseTicketing` Façade (P1)

All module boundaries use **pure value models** (Pydantic / dataclasses) to isolate external callers and adapters from database models and transaction sessions.

### Pure Value Models (`backend/app/integrations/ticketing/models.py`)
```python
from datetime import datetime
from pydantic import BaseModel, Field

class TicketDraft(BaseModel):
    case_id: int
    case_title: str
    analysis_run_id: str
    root_cause_summary: str | None = None
    finding_summary: str | None = None
    extra_context: dict[str, str] = Field(default_factory=dict)

class TicketCreationResult(BaseModel):
    remote_id: str
    display_key: str
    ticket_url: str
    observed_remote_status: str | None = None

class RemoteTicketSnapshot(BaseModel):
    remote_id: str
    display_key: str
    observed_remote_status: str
    remote_events: list["RemoteEventDraft"]
    sync_cursor: str | None = None

class RemoteEventDraft(BaseModel):
    remote_event_id: str                    # Canonical ID (e.g. 'jira_comment_10042')
    event_type: str                         # "comment_created", "status_changed"
    author: str | None = None
    summary: str
    occurred_at: datetime
    raw_payload: dict = Field(default_factory=dict)

class TicketView(BaseModel):
    case_id: int
    provider: str
    remote_id: str
    display_key: str
    ticket_url: str
    observed_remote_status: str | None = None
    last_synced_at: datetime | None = None

class TicketOperationView(BaseModel):
    operation_id: str
    case_id: int
    provider: str
    operation_type: str
    status: str                             # pending, processing, ambiguous_outcome, completed, failed, dead_letter
    attempts: int
    available_at: datetime
    error_message: str | None = None

class TicketEventView(BaseModel):
    id: int
    case_id: int
    provider: str
    remote_event_id: str
    event_type: str
    author: str | None
    summary: str
    occurred_at: datetime
```

### Granular Role Protocols (`backend/app/integrations/ticketing/protocols.py`)
```python
from typing import Mapping, Protocol, runtime_checkable

@runtime_checkable
class TicketCreator(Protocol):
    """Outbound ticket creation and pre-retry reconciliation."""
    def reconcile_or_create(self, draft: TicketDraft, operation_id: str) -> TicketCreationResult: ...

@runtime_checkable
class TicketSynchronizer(Protocol):
    """Inbound polling of remote ticket status and timeline activity."""
    def pull_remote_ticket(self, remote_id: str, display_key: str, cursor: str | None = None) -> RemoteTicketSnapshot: ...

@runtime_checkable
class WebhookVerifier(Protocol):
    """Cryptographic signature verification on raw request bodies."""
    def verify_signature(self, raw_body: bytes, headers: Mapping[str, str], secret: str) -> bool: ...

@runtime_checkable
class WebhookParser(Protocol):
    """Parsing inbound provider webhook payloads into canonical events and delivery receipt."""
    def extract_delivery_id(self, headers: Mapping[str, str]) -> str | None: ...
    def parse_webhook_event(self, raw_body: bytes, headers: Mapping[str, str]) -> RemoteEventDraft | None: ...
```

### Deep Façade: `CaseTicketing` (`backend/app/integrations/ticketing/service.py`)
```python
from typing import Callable
from sqlalchemy.orm import Session

class CaseTicketing:
    """Deep module façade orchestrating ticketing outbox, adapters, links, and events."""

    def __init__(self, session_factory: Callable[[], Session], config: TicketingConfig, providers: dict[str, Any]):
        self.session_factory = session_factory
        self.config = config
        self.providers = providers

    def request_create(self, case_id: int, idempotency_key: str | None = None) -> TicketOperationView:
        """Enqueues an idempotent ticket creation operation in the outbox."""

    def request_sync(self, case_id: int) -> TicketOperationView:
        """Enqueues an idempotent ticket sync operation in the outbox."""

    def retry_operation(self, operation_id: str) -> TicketOperationView:
        """Reopens a failed or dead-letter outbox operation for immediate retry."""

    def link_existing_ticket(self, case_id: int, provider: str, display_key: str) -> TicketView:
        """Operator resolution: manually links an existing remote ticket."""

    def force_create_ticket(self, case_id: int, operation_id: str) -> TicketOperationView:
        """Operator resolution: forces creation after an ambiguous outcome."""

    def get_ticket_view(self, case_id: int) -> TicketView | None:
        """Fetches active ticket link projection for a case."""

    def get_operation_view(self, operation_id: str) -> TicketOperationView | None:
        """Fetches outbox operation state."""

    def list_ticket_events(self, case_id: int, limit: int = 50) -> list[TicketEventView]:
        """Fetches immutable external timeline events for a case."""

    def process_pending_operations(self, limit: int = 10) -> int:
        """Outbox worker step: claims jobs with lease locking, heartbeats, and executes them."""

    def accept_webhook(self, provider_name: str, raw_body: bytes, headers: Mapping[str, str]) -> bool:
        """Verifies signature, records delivery receipt, updates status, and appends canonical event."""
```

---

## 7. Jira Cloud Reference Adapter Details (P0, P1 & P2)

### A. Jira Cloud REST API v3 Only (P2)
Ops Signals targets **Jira Cloud REST API v3** exclusively. All rich-text descriptions are generated in Atlassian Document Format (ADF) via `backend/app/integrations/ticketing/jira/adf.py`.

### B. Reconciliation & Ambiguous Error Handling
```python
class JiraTicketProvider:
    def reconcile_or_create(self, draft: TicketDraft, operation_id: str) -> TicketCreationResult:
        op_label = f"ops-signals-op-{operation_id}"
        
        # Step 1: Pre-reconciliation search via native label
        existing = self._find_issue_by_label(op_label)
        if existing:
            return existing

        # Step 2: Fresh issue creation with ADF description and labels
        payload = {
            "fields": {
                "project": {"key": self.config.project_key},
                "summary": f"[Ops Signals] {draft.case_title}",
                "issuetype": {"name": self.config.issue_type},
                "labels": [
                    "ops-signals",
                    f"ops-signals-case-{draft.case_id}",
                    op_label,
                ],
                "description": build_case_adf_description(draft),
            }
        }
        try:
            res = self._post("/rest/api/3/issue", payload)
            return TicketCreationResult(
                remote_id=res["id"],
                display_key=res["key"],
                ticket_url=f"{self.config.base_url.rstrip('/')}/browse/{res['key']}",
                observed_remote_status="To Do"
            )
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            # Uncertain outcome: do NOT retry automatically; trigger ambiguous outcome state
            raise AmbiguousOutcomeError(f"In-flight Jira create encountered {exc}; state unknown.") from exc

    def _find_issue_by_label(self, label: str) -> TicketCreationResult | None:
        jql = f'project = "{self.config.project_key}" AND labels = "{label}"'
        data = self._get("/rest/api/3/search", params={"jql": jql, "maxResults": 1})
        issues = data.get("issues", [])
        if not issues:
            return None
        issue = issues[0]
        return TicketCreationResult(
            remote_id=issue["id"],
            display_key=issue["key"],
            ticket_url=f"{self.config.base_url.rstrip('/')}/browse/{issue['key']}",
            observed_remote_status=issue.get("fields", {}).get("status", {}).get("name"),
        )
```

### C. Provider-Agnostic Dynamic Webhook Security Exemption (P1)
In Ops Signals, [`backend/app/security.py`](../../../backend/app/security.py) protects all API routes with a global bearer token check (`require_api_token`).

Instead of hardcoding Jira-specific URLs into static sets (which would force modifying core security files whenever ServiceNow or GitHub is added in Phase 4), `backend/app/security.py` defines a narrow **dynamic public route exemption**:
```python
def is_public_route(method: str, path: str) -> bool:
    if (method, path) in PUBLIC_ROUTES:
        return True
    # Dynamic exemption: Inbound ticketing webhooks are exempt from bearer auth;
    # authentication is delegated entirely to the provider's cryptographic verifier.
    if method == "POST" and path.startswith("/api/integrations/ticketing/") and path.endswith("/webhook"):
        return True
    return False

def require_api_token(
    request: Request,
    authorization: str | None = Header(default=None),
    config: SecurityConfig = Depends(get_security_config),
) -> None:
    if is_public_route(request.method, request.url.path.rstrip("/")):
        return
    check_bearer_token(authorization, config.api_token)
```

The webhook endpoint itself enforces authentication via `WebhookVerifier.verify_signature`:
```python
class JiraTicketProvider:
    def verify_signature(self, raw_body: bytes, headers: Mapping[str, str], secret: str) -> bool:
        sig = headers.get("X-Hub-Signature") or headers.get("x-hub-signature")
        if not sig or not secret:
            return False
        expected = "sha256=" + hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, sig)

    def extract_delivery_id(self, headers: Mapping[str, str]) -> str | None:
        return headers.get("X-Atlassian-Webhook-Identifier") or headers.get("x-atlassian-webhook-identifier")
```
If the provider is unconfigured, unknown, or the HMAC signature fails, the endpoint immediately returns `401 Unauthorized` (or `404 Not Found`).

---

## 8. Configuration Model & Dependency Injection

### Configuration Schema (`backend/app/config.py`)
```python
class JiraConfig(BaseModel):
    base_url: str | None = None               # e.g. "https://example.atlassian.net"
    email: str | None = None                  # service account email
    api_token: str | None = None              # Atlassian API token
    project_key: str | None = None            # e.g. "OPS"
    issue_type: str = "Task"                  # "Task", "Incident", "Bug"
    webhook_secret: str | None = None         # Shared HMAC secret for webhooks
    request_timeout_seconds: float = 10.0

class TicketingConfig(BaseModel):
    enabled: bool = False
    active_provider: str = "jira"             # "jira" | "servicenow" | "github"
    automatic_on_case_creation: bool = False  # opt-in auto-creation
    outbox_lease_seconds: int = 60
    outbox_max_attempts: int = 5
    jira: JiraConfig = Field(default_factory=JiraConfig)

def get_ticketing_config() -> TicketingConfig:
    return TicketingConfig(
        enabled=_parse_bool(_env("OPS_SIGNALS_TICKETING_ENABLED"), False),
        active_provider=_env("OPS_SIGNALS_TICKETING_PROVIDER") or "jira",
        automatic_on_case_creation=_parse_bool(_env("OPS_SIGNALS_TICKETING_AUTO_CREATE"), False),
        jira=JiraConfig(
            base_url=_env("OPS_SIGNALS_JIRA_URL"),
            email=_env("OPS_SIGNALS_JIRA_EMAIL"),
            api_token=_env("OPS_SIGNALS_JIRA_API_TOKEN"),
            project_key=_env("OPS_SIGNALS_JIRA_PROJECT_KEY"),
            issue_type=_env("OPS_SIGNALS_JIRA_ISSUE_TYPE") or "Task",
            webhook_secret=_env("OPS_SIGNALS_JIRA_WEBHOOK_SECRET"),
        )
    )
```

### FastAPI Dependency Injection (`backend/app/api/ticketing.py`)
```python
def get_case_ticketing(
    config: TicketingConfig = Depends(get_ticketing_config)
) -> CaseTicketing:
    providers = {}
    if config.jira.base_url and config.jira.api_token:
        providers["jira"] = JiraTicketProvider(config.jira)
    return CaseTicketing(session_factory=get_db_sessionmaker(), config=config, providers=providers)
```

---

## 9. REST API Endpoints Contract

| Method & Path | Auth / Status | Purpose | Details |
|---|---|---|---|
| `POST /api/cases/{case_id}/ticket/create` | Bearer / `202 Accepted` | Idempotent trigger for ticket creation | Returns `{"status": "accepted", "operation_id": "...", "poll_url": "..."}` |
| `POST /api/cases/{case_id}/ticket/sync` | Bearer / `202 Accepted` | Idempotent trigger for manual ticket sync | Enqueues sync outbox task. |
| `POST /api/cases/{case_id}/ticket/retry` | Bearer / `202 Accepted` | Reopens failed/dead-letter outbox operation | Resets attempts and triggers immediate retry. |
| `POST /api/cases/{case_id}/ticket/link` | Bearer / `200 OK` | Manually link existing external ticket | Body: `{"provider": "jira", "display_key": "OPS-143"}` |
| `POST /api/cases/{case_id}/ticket/force-create` | Bearer / `202 Accepted` | Operator forces fresh create after ambiguous outcome | Bypasses ambiguous circuit and queues create task. |
| `GET /api/cases/{case_id}/ticket` | Bearer / `200 OK` | Fetch ticket link, active operation & events | Returns `TicketView`, active `TicketOperationView`, and recent `TicketEventView` items. |
| `GET /api/cases/{case_id}/ticket/operations/{operation_id}` | Bearer / `200 OK` | Check operation execution status | Returns `TicketOperationView`. |
| `POST /api/integrations/ticketing/{provider}/webhook` | Public + `X-Hub-Signature` / `200 OK` | Inbound webhook receiver | Cryptographically verified on raw bytes; records delivery receipt and appends canonical event. |

---

## 10. Frontend User Experience (Grafana & Standalone UI)

The Case Details view features a dedicated **Ticketing Card**:
1. **Unlinked Case:**
   - Primary Action: `[Create Jira Ticket]` button.
   - When operation is `pending` or `processing`: Spinner with disabled button `[Creating Ticket... ⏳]`.
2. **Linked Case:**
   - Ticket Badge: `[JIRA: OPS-142 ↗]` opening the Jira ticket in a new browser tab.
   - Status Chip: Displays `observed_remote_status` (e.g., `In Progress`, `Done`).
   - Refresh Action: `[Sync Now 🔄]` button.
   - **External Activity Feed:** Displays recent comments from `case_ticket_events` with remote author and timestamp, completely separate from the internal RCA notes.
3. **Ambiguous Outcome State:**
   - Diagnostic banner: *"Ticket creation was interrupted by a network timeout. Ops Signals could not confirm whether Jira created the ticket."*
   - Actions: `[Check Jira Again]`, `[Link Existing Ticket]`, or `[Force Create New]`.
4. **Failed / Dead-Letter State:**
   - Error banner with failure explanation and `[Retry Ticket Action]` button calling `POST /api/cases/{id}/ticket/retry`.

---

## 11. Phased Rollout Plan

### Phase 1: Outbound Jira Cloud v3 with Durable Outbox & Reconciliation
- **Migration `004_add_ticketing_tables.sql`:**
  - Create `case_ticket_links`.
  - Create `case_ticket_events`.
  - Create `ticket_webhook_deliveries`.
  - Create `ticket_operations`.
- **Core Engine:**
  - Value models (`models.py`), role protocols (`protocols.py`), and `CaseTicketing` façade (`service.py`).
  - `JiraTicketProvider` with ADF generator and JQL label reconciliation.
  - Outbox worker loop with per-claim UUID leases, independent session heartbeat, and atomic completion transaction.
- **Security & Routes:**
  - Add dynamic webhook route exemption to `backend/app/security.py`.
  - Add `TicketingConfig` and `JiraConfig` to `config.py`.
  - Expose case ticket endpoints.
- **UI:** Integrate ticketing widget into Grafana plugin and web UI.

### Phase 2: Inbound Poll & External Activity Feed
- Implement `pull_remote_ticket` in `JiraTicketProvider` using `f"jira_comment_{id}"` / `f"jira_changelog_{id}"`.
- Expose `POST /api/cases/{id}/ticket/sync`.
- Ingest remote comments into `case_ticket_events` and update `observed_remote_status`.

### Phase 3: Real-Time Inbound Webhooks via HMAC-SHA256
- Implement `verify_signature` using `X-Hub-Signature` and constant-time `hmac.compare_digest`.
- Ingest delivery receipts into `ticket_webhook_deliveries` and canonical domain events into `case_ticket_events`.

### Phase 4: Additional Adapters (ServiceNow, GitHub, Linear)
- Add `ServiceNowTicketProvider` and `GitHubIssuesTicketProvider`.
- Zero schema migrations and zero core security edits; purely additive provider classes implementing role protocols.

---

## 12. Explicit Non-Goals

1. **No Dual-Master Status Overwriting:** Ops Signals' computed `case_status` is never replaced by Jira status.
2. **No Ingestion into `investigation_notes`:** Remote comments live in `case_ticket_events` to preserve case lifecycle rules.
3. **No Automated Creation After Uncertain Outcomes:** Negative JQL is never treated as proof of absence; uncertain outcomes require operator resolution.
4. **No Direct Qdrant Access:** External systems cannot query or index directly into Qdrant vector memory.
5. **No Legacy Jira v2 Wiki Markup:** We do not support Jira Server or Jira Cloud REST v2 fallback.
6. **No Insecure Query-String Webhook Secrets:** Webhooks require authentic HTTP header HMAC signatures.
