-- Wires up the previously-unused autonomous_policies.enabled flag with the columns a recurring
-- schedule actually needs. Applied automatically at backend startup via
-- backend/app/models/schema_compat.py::ensure_autonomous_policy_scheduling_schema - this file
-- documents the same additive change for anyone reading migration history by hand.

ALTER TABLE autonomous_policies ADD COLUMN IF NOT EXISTS schedule_minutes INTEGER NULL;
ALTER TABLE autonomous_policies ADD COLUMN IF NOT EXISTS next_run_at TIMESTAMPTZ NULL;
ALTER TABLE autonomous_policies ADD COLUMN IF NOT EXISTS last_run_status VARCHAR(32) NULL;
ALTER TABLE autonomous_policies ADD COLUMN IF NOT EXISTS consecutive_failures INTEGER NOT NULL DEFAULT 0;

CREATE INDEX IF NOT EXISTS idx_autonomous_policies_enabled_next_run
    ON autonomous_policies(enabled, next_run_at);
