-- New tables for alert enrichment (docs/design/alert-enrichment-plan.md). Created automatically at backend
-- startup via Base.metadata.create_all (backend/app/main.py) since they're new tables, not alters to
-- existing ones - this file documents the same change for anyone reading migration history by hand,
-- same convention as 003/004.

CREATE TABLE IF NOT EXISTS ops_change_events (
    id SERIAL PRIMARY KEY,
    service TEXT NOT NULL,
    event_type VARCHAR(32) NOT NULL,
    timestamp TIMESTAMPTZ NOT NULL,
    version TEXT NULL,
    env TEXT NULL,
    author TEXT NULL,
    source TEXT NULL,
    url TEXT NULL,
    description TEXT NULL,
    attributes_json JSON NULL,
    received_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_change_events_service_ts
    ON ops_change_events(service, timestamp);

CREATE TABLE IF NOT EXISTS ops_alert_enrichments (
    id SERIAL PRIMARY KEY,
    fingerprint TEXT NOT NULL,
    source VARCHAR(32) NOT NULL,
    alert_name TEXT NOT NULL,
    service TEXT NULL,
    metric_key TEXT NULL,
    severity TEXT NULL,
    status VARCHAR(16) NOT NULL,
    starts_at TIMESTAMPTZ NOT NULL,
    ends_at TIMESTAMPTZ NULL,
    labels_json JSON NULL,
    annotations_json JSON NULL,
    generator_url TEXT NULL,
    external_url TEXT NULL,
    promql TEXT NULL,
    analysis_status VARCHAR(64) NULL,
    analysis_run_id TEXT NULL,
    finding_id INTEGER NULL,
    change_event_ids JSON NULL,
    recommendation VARCHAR(32) NULL,
    enrichment_json JSON NULL,
    message_json JSON NULL,
    notify_status VARCHAR(64) NULL,
    slack_posted_at TIMESTAMPTZ NULL,
    resolved_posted_at TIMESTAMPTZ NULL,
    error TEXT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_alert_enrichments_fingerprint
    ON ops_alert_enrichments(fingerprint, created_at);
