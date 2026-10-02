-- Ask Ops Signals answer feedback (docs/ask-ops-signals-assistant.md). Created automatically at
-- backend startup via Base.metadata.create_all (backend/app/main.py) since it's a new table, not an
-- alter to an existing one - this file documents the same change for anyone reading migration
-- history by hand, same convention as 003-005.

CREATE TABLE IF NOT EXISTS ops_assistant_feedback (
    id SERIAL PRIMARY KEY,
    conversation_id VARCHAR(64) NULL,
    question TEXT NOT NULL,
    answer TEXT NULL,
    helpful BOOLEAN NOT NULL,
    reason VARCHAR(32) NULL,
    ai_synthesis_used BOOLEAN NOT NULL DEFAULT FALSE,
    cited_json JSON NULL,
    status VARCHAR(16) NOT NULL DEFAULT 'open',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_assistant_feedback_helpful_status
    ON ops_assistant_feedback(helpful, status);
