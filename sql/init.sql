CREATE TABLE IF NOT EXISTS ops_normalized_timeseries_points (
    id BIGSERIAL PRIMARY KEY,
    source TEXT,
    metric_name TEXT NOT NULL,
    timestamp TIMESTAMPTZ NOT NULL,
    value DOUBLE PRECISION NOT NULL,
    service TEXT,
    env TEXT,
    host TEXT,
    namespace TEXT,
    pod TEXT,
    unit TEXT,
    metric_type TEXT,
    tags_json JSONB,
    analysis_run_id TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_ops_norm_metric_ts
    ON ops_normalized_timeseries_points (metric_name, timestamp);

CREATE INDEX IF NOT EXISTS idx_ops_norm_service_ts
    ON ops_normalized_timeseries_points (service, timestamp);

CREATE INDEX IF NOT EXISTS idx_ops_norm_env_ts
    ON ops_normalized_timeseries_points (env, timestamp);

CREATE TABLE IF NOT EXISTS ops_operational_signals (
    id BIGSERIAL PRIMARY KEY,
    signal_id TEXT,
    signal_type TEXT NOT NULL,
    analyzer_id TEXT,
    metric_name TEXT NOT NULL,
    service TEXT,
    env TEXT,
    severity TEXT,
    confidence DOUBLE PRECISION,
    start_time TIMESTAMPTZ,
    end_time TIMESTAMPTZ,
    summary TEXT,
    evidence_json JSONB,
    importance_score DOUBLE PRECISION DEFAULT 0,
    status TEXT DEFAULT 'new',
    embedding_json JSONB,
    analysis_run_id TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

ALTER TABLE IF EXISTS ops_operational_signals
    ADD COLUMN IF NOT EXISTS signal_id TEXT;

ALTER TABLE IF EXISTS ops_operational_signals
    ADD COLUMN IF NOT EXISTS importance_score DOUBLE PRECISION DEFAULT 0;

ALTER TABLE IF EXISTS ops_operational_signals
    ADD COLUMN IF NOT EXISTS analyzer_id TEXT;

ALTER TABLE IF EXISTS ops_operational_signals
    ADD COLUMN IF NOT EXISTS analysis_run_id TEXT;

ALTER TABLE IF EXISTS ops_normalized_timeseries_points
    ADD COLUMN IF NOT EXISTS analysis_run_id TEXT;

CREATE UNIQUE INDEX IF NOT EXISTS idx_ops_signal_uid
    ON ops_operational_signals (signal_id);

CREATE INDEX IF NOT EXISTS idx_ops_signal_metric_start
    ON ops_operational_signals (metric_name, start_time);

CREATE INDEX IF NOT EXISTS idx_ops_signal_service_start
    ON ops_operational_signals (service, start_time);

CREATE INDEX IF NOT EXISTS idx_ops_signal_env_start
    ON ops_operational_signals (env, start_time);

CREATE INDEX IF NOT EXISTS idx_ops_signal_status
    ON ops_operational_signals (status);

CREATE TABLE IF NOT EXISTS ops_operational_findings (
    id BIGSERIAL PRIMARY KEY,
    analysis_run_id TEXT,
    service TEXT,
    metric_name TEXT NOT NULL,
    title TEXT NOT NULL,
    summary TEXT NOT NULL,
    category TEXT NOT NULL,
    health_status TEXT NOT NULL,
    importance_score DOUBLE PRECISION NOT NULL,
    investigation_priority INTEGER NOT NULL,
    signal_ids JSONB NOT NULL,
    comparison_json JSONB NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

ALTER TABLE IF EXISTS ops_operational_findings
    ADD COLUMN IF NOT EXISTS analysis_run_id TEXT;

-- External cluster label (Mimir/Thanos multi-cluster); NULL for single-cluster data.
ALTER TABLE IF EXISTS ops_normalized_timeseries_points
    ADD COLUMN IF NOT EXISTS cluster TEXT;

ALTER TABLE IF EXISTS ops_operational_signals
    ADD COLUMN IF NOT EXISTS cluster TEXT;

ALTER TABLE IF EXISTS ops_operational_findings
    ADD COLUMN IF NOT EXISTS cluster TEXT;

CREATE INDEX IF NOT EXISTS idx_ops_finding_metric
    ON ops_operational_findings (metric_name, created_at);

CREATE INDEX IF NOT EXISTS idx_ops_finding_service
    ON ops_operational_findings (service, created_at);

CREATE INDEX IF NOT EXISTS idx_ops_finding_importance
    ON ops_operational_findings (importance_score DESC);

CREATE TABLE IF NOT EXISTS ops_operational_cases (
    id BIGSERIAL PRIMARY KEY,
    finding_id BIGINT NOT NULL REFERENCES ops_operational_findings(id) ON DELETE CASCADE,
    analysis_run_id TEXT NOT NULL,
    case_title TEXT NOT NULL,
    case_status VARCHAR(32) NOT NULL DEFAULT 'open',
    finding_snapshot JSONB NOT NULL,
    investigation_status VARCHAR(32) NOT NULL DEFAULT 'not_started',
    investigation_notes JSONB NOT NULL DEFAULT '[]'::jsonb,
    root_cause_status VARCHAR(32) NOT NULL DEFAULT 'unknown',
    root_cause_summary TEXT,
    root_cause_confidence DOUBLE PRECISION,
    root_cause_verified BOOLEAN NOT NULL DEFAULT FALSE,
    corrective_action TEXT,
    outcome_status VARCHAR(32) NOT NULL DEFAULT 'pending',
    outcome_summary TEXT,
    memory_status VARCHAR(32) NOT NULL DEFAULT 'not_indexed',
    memory_indexed_at TIMESTAMPTZ,
    memory_error TEXT,
    memory_content_version INTEGER,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    resolved_at TIMESTAMPTZ
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_ops_case_finding
    ON ops_operational_cases (finding_id);

CREATE INDEX IF NOT EXISTS idx_ops_case_status
    ON ops_operational_cases (case_status);

CREATE INDEX IF NOT EXISTS idx_ops_case_created
    ON ops_operational_cases (created_at DESC);

CREATE INDEX IF NOT EXISTS idx_ops_case_memory_status
    ON ops_operational_cases (memory_status);

CREATE INDEX IF NOT EXISTS idx_ops_case_memory_indexed_at
    ON ops_operational_cases (memory_indexed_at DESC);

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
    file_name VARCHAR(255),
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

ALTER TABLE IF EXISTS analysis_runs
    ADD COLUMN IF NOT EXISTS file_name VARCHAR(255);

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
