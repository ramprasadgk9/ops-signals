-- Imported incident history (docs/importing-incident-history.md). Applied automatically at backend
-- startup by ensure_case_import_schema (backend/app/models/schema_compat.py), since it alters an
-- existing table - this file documents the same change for anyone reading migration history by
-- hand, same convention as 003-006.

ALTER TABLE ops_operational_cases ADD COLUMN IF NOT EXISTS source VARCHAR(32) NOT NULL DEFAULT 'detected';
ALTER TABLE ops_operational_cases ADD COLUMN IF NOT EXISTS source_id TEXT NULL;
ALTER TABLE ops_operational_cases ADD COLUMN IF NOT EXISTS source_url TEXT NULL;
ALTER TABLE ops_operational_cases ADD COLUMN IF NOT EXISTS import_batch_id VARCHAR(32) NULL;
ALTER TABLE ops_operational_cases ADD COLUMN IF NOT EXISTS content_hash VARCHAR(64) NULL;

-- Re-importing the same record updates its case instead of creating a second one.
CREATE UNIQUE INDEX IF NOT EXISTS uq_case_source_record ON ops_operational_cases (source, source_id);

-- A detected case links to exactly one finding or behavior; an imported case links to neither and
-- carries its source's record ID. NOT VALID: checked for new and updated rows only.
ALTER TABLE ops_operational_cases DROP CONSTRAINT IF EXISTS ck_case_exactly_one_source;
ALTER TABLE ops_operational_cases ADD CONSTRAINT ck_case_source_link CHECK (
    (source = 'detected' AND ((finding_id IS NOT NULL) != (behavior_finding_id IS NOT NULL)))
    OR (source <> 'detected' AND finding_id IS NULL AND behavior_finding_id IS NULL AND source_id IS NOT NULL)
) NOT VALID;

CREATE TABLE IF NOT EXISTS ops_case_imports (
    id VARCHAR(32) PRIMARY KEY,
    sources JSON NOT NULL,
    file_profiles JSON NOT NULL,
    counts JSON NOT NULL,
    indexed INTEGER NOT NULL DEFAULT 0,
    status VARCHAR(16) NOT NULL DEFAULT 'running',
    created_at TIMESTAMPTZ NULL,
    undone_at TIMESTAMPTZ NULL
);
