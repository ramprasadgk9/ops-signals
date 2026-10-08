-- "Was this real?" answers on findings (docs/finding-trust.md). Created automatically at backend
-- startup via Base.metadata.create_all (backend/app/main.py) since it's a new table, not an alter
-- to an existing one - this file documents the same change for anyone reading migration history
-- by hand, same convention as 003-008.

CREATE TABLE IF NOT EXISTS ops_finding_feedback (
    id SERIAL PRIMARY KEY,
    finding_id INTEGER NOT NULL UNIQUE,
    service TEXT NULL,
    metric_name TEXT NOT NULL,
    trust_group VARCHAR(32) NOT NULL,
    verdict VARCHAR(24) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_finding_feedback_service_group
    ON ops_finding_feedback(service, trust_group);
