-- New tables for Pluggable Case Ticketing Architecture (docs/design/proposals/jira-integration-plan.md).
-- Created automatically at backend startup via Base.metadata.create_all and ensure_ticketing_schema (backend/app/main.py).

CREATE TABLE IF NOT EXISTS ticket_operations (
    id VARCHAR(64) PRIMARY KEY,
    case_id INTEGER NOT NULL REFERENCES ops_operational_cases(id) ON DELETE CASCADE,
    provider VARCHAR(32) NOT NULL,
    operation_type VARCHAR(32) NOT NULL,
    idempotency_key VARCHAR(128) NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'pending',
    attempts INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 5,
    available_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    lease_token VARCHAR(64) NULL,
    lease_expires_at TIMESTAMPTZ NULL,
    supersedes_operation_id VARCHAR(64) NULL REFERENCES ticket_operations(id),
    payload JSON NULL,
    error_message TEXT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_ticket_ops_provider_key UNIQUE (provider, idempotency_key)
);

CREATE INDEX IF NOT EXISTS idx_ticket_ops_claim
    ON ticket_operations(status, available_at);

CREATE INDEX IF NOT EXISTS idx_ticket_ops_case_type
    ON ticket_operations(case_id, operation_type);

CREATE TABLE IF NOT EXISTS case_ticket_links (
    id SERIAL PRIMARY KEY,
    case_id INTEGER NOT NULL REFERENCES ops_operational_cases(id) ON DELETE CASCADE,
    provider VARCHAR(32) NOT NULL,
    remote_id VARCHAR(128) NOT NULL,
    display_key VARCHAR(128) NOT NULL,
    ticket_url TEXT NOT NULL,
    observed_remote_status VARCHAR(64) NULL,
    sync_cursor TEXT NULL,
    last_synced_at TIMESTAMPTZ NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_case_ticket_links_case_provider UNIQUE (case_id, provider)
);

CREATE INDEX IF NOT EXISTS idx_ticket_links_provider_remote
    ON case_ticket_links(provider, remote_id);

CREATE TABLE IF NOT EXISTS case_ticket_events (
    id SERIAL PRIMARY KEY,
    case_id INTEGER NOT NULL REFERENCES ops_operational_cases(id) ON DELETE CASCADE,
    provider VARCHAR(32) NOT NULL,
    remote_event_id VARCHAR(128) NOT NULL,
    event_type VARCHAR(64) NOT NULL,
    author VARCHAR(128) NULL,
    summary TEXT NOT NULL,
    payload JSON NULL,
    occurred_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_ticket_events_prov_remote_id UNIQUE (provider, remote_event_id)
);

CREATE INDEX IF NOT EXISTS idx_ticket_events_case_occ
    ON case_ticket_events(case_id, occurred_at);

CREATE TABLE IF NOT EXISTS ticket_webhook_deliveries (
    id SERIAL PRIMARY KEY,
    provider VARCHAR(32) NOT NULL,
    delivery_id VARCHAR(128) NOT NULL,
    processed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_webhook_deliv_prov_delivery UNIQUE (provider, delivery_id)
);
