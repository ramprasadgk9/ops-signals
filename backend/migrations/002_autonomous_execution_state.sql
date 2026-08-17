CREATE TABLE IF NOT EXISTS autonomous_policies (
    id VARCHAR(64) PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    datasource VARCHAR(64) NOT NULL,
    backend VARCHAR(128) NOT NULL,
    scope_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    monitoring_categories_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    execution_policy_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    enabled BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS autonomous_policy_runs (
    id VARCHAR(64) PRIMARY KEY,
    policy_id VARCHAR(64) NULL REFERENCES autonomous_policies(id) ON DELETE SET NULL,
    trigger VARCHAR(32) NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'planned',
    started_at TIMESTAMPTZ NULL,
    completed_at TIMESTAMPTZ NULL,
    policy_snapshot_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    metrics_discovered INTEGER NOT NULL DEFAULT 0,
    metrics_selected INTEGER NOT NULL DEFAULT 0,
    jobs_planned INTEGER NOT NULL DEFAULT 0,
    jobs_completed INTEGER NOT NULL DEFAULT 0,
    jobs_skipped INTEGER NOT NULL DEFAULT 0,
    jobs_failed INTEGER NOT NULL DEFAULT 0,
    findings_created INTEGER NOT NULL DEFAULT 0,
    error_summary TEXT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_autonomous_policy_runs_policy_id
    ON autonomous_policy_runs(policy_id);

CREATE INDEX IF NOT EXISTS idx_autonomous_policy_runs_status
    ON autonomous_policy_runs(status);

CREATE INDEX IF NOT EXISTS idx_autonomous_policy_runs_created_at
    ON autonomous_policy_runs(created_at);

CREATE TABLE IF NOT EXISTS autonomous_analysis_jobs (
    id VARCHAR(64) PRIMARY KEY,
    policy_run_id VARCHAR(64) NOT NULL REFERENCES autonomous_policy_runs(id) ON DELETE CASCADE,
    status VARCHAR(32) NOT NULL DEFAULT 'planned',
    datasource VARCHAR(64) NOT NULL,
    environment VARCHAR(255) NULL,
    namespace VARCHAR(255) NULL,
    service VARCHAR(255) NULL,
    metric_name VARCHAR(255) NOT NULL,
    logical_metric_name VARCHAR(255) NULL,
    category VARCHAR(64) NULL,
    concept VARCHAR(64) NULL,
    promql TEXT NULL,
    analysis_window VARCHAR(32) NOT NULL,
    aggregation_strategy VARCHAR(128) NULL,
    transformation VARCHAR(128) NULL,
    classification_confidence DOUBLE PRECISION NULL,
    selection_reason VARCHAR(255) NULL,
    skip_reason_code VARCHAR(64) NULL,
    skip_reason_detail TEXT NULL,
    retry_count INTEGER NOT NULL DEFAULT 0,
    analysis_run_id VARCHAR(64) NULL REFERENCES analysis_runs(id) ON DELETE SET NULL,
    started_at TIMESTAMPTZ NULL,
    completed_at TIMESTAMPTZ NULL,
    duration_ms INTEGER NULL,
    error_type VARCHAR(128) NULL,
    error_code VARCHAR(128) NULL,
    error_message TEXT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_autonomous_jobs_policy_run_id
    ON autonomous_analysis_jobs(policy_run_id);

CREATE INDEX IF NOT EXISTS idx_autonomous_jobs_status
    ON autonomous_analysis_jobs(status);

CREATE INDEX IF NOT EXISTS idx_autonomous_jobs_analysis_run_id
    ON autonomous_analysis_jobs(analysis_run_id);

CREATE INDEX IF NOT EXISTS idx_autonomous_jobs_service
    ON autonomous_analysis_jobs(service);

CREATE INDEX IF NOT EXISTS idx_autonomous_jobs_metric_name
    ON autonomous_analysis_jobs(metric_name);

CREATE INDEX IF NOT EXISTS idx_autonomous_jobs_created_at
    ON autonomous_analysis_jobs(created_at);

