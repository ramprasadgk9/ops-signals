ALTER TABLE IF EXISTS ops_normalized_timeseries_points
    ADD COLUMN IF NOT EXISTS analysis_run_id TEXT;

ALTER TABLE IF EXISTS ops_operational_signals
    ADD COLUMN IF NOT EXISTS analyzer_id TEXT;

ALTER TABLE IF EXISTS ops_operational_signals
    ADD COLUMN IF NOT EXISTS analysis_run_id TEXT;

CREATE TABLE IF NOT EXISTS capabilities (
    id VARCHAR(64) PRIMARY KEY,
    analyzer_id VARCHAR(64) NOT NULL,
    title VARCHAR(128) NOT NULL,
    description TEXT NOT NULL,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS question_catalog (
    id VARCHAR(64) PRIMARY KEY,
    label VARCHAR(256) NOT NULL,
    description TEXT NOT NULL,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    display_order INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS capability_questions (
    capability_id VARCHAR(64) NOT NULL REFERENCES capabilities(id) ON DELETE CASCADE,
    question_id VARCHAR(64) NOT NULL REFERENCES question_catalog(id) ON DELETE CASCADE,
    PRIMARY KEY (capability_id, question_id)
);

CREATE TABLE IF NOT EXISTS analysis_runs (
    id VARCHAR(64) PRIMARY KEY,
    source_type VARCHAR(32) NOT NULL,
    provider VARCHAR(32) NOT NULL DEFAULT 'generic',
    service VARCHAR(128) NOT NULL,
    metric_name VARCHAR(128) NOT NULL,
    start_time TIMESTAMPTZ NOT NULL,
    end_time TIMESTAMPTZ NOT NULL,
    sample_count INTEGER NOT NULL,
    status VARCHAR(32) NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

ALTER TABLE IF EXISTS analysis_runs
    ADD COLUMN IF NOT EXISTS provider VARCHAR(32) NOT NULL DEFAULT 'generic';

CREATE TABLE IF NOT EXISTS question_answers (
    id BIGSERIAL PRIMARY KEY,
    analysis_run_id VARCHAR(64) NOT NULL REFERENCES analysis_runs(id) ON DELETE CASCADE,
    question_id VARCHAR(64) NOT NULL REFERENCES question_catalog(id) ON DELETE CASCADE,
    headline TEXT NOT NULL,
    answer TEXT NOT NULL,
    status VARCHAR(32) NOT NULL,
    priority VARCHAR(32) NOT NULL,
    confidence DOUBLE PRECISION NOT NULL,
    key_points_json JSONB NOT NULL,
    evidence_signal_ids JSONB NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
