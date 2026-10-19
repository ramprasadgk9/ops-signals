-- Who did what, when a request came through the Grafana plugin's proxy (backend/app/identity.py).
-- Applied automatically at backend startup via
-- backend/app/models/schema_compat.py::ensure_actor_schema - this file documents the same additive
-- change for anyone reading migration history by hand, same convention as 003-009.

ALTER TABLE ops_finding_feedback ADD COLUMN IF NOT EXISTS answered_by TEXT NULL;
ALTER TABLE ops_operational_cases ADD COLUMN IF NOT EXISTS created_by TEXT NULL;
ALTER TABLE autonomous_policies ADD COLUMN IF NOT EXISTS created_by TEXT NULL;
ALTER TABLE autonomous_policies ADD COLUMN IF NOT EXISTS edited_by TEXT NULL;
ALTER TABLE autonomous_policies ADD COLUMN IF NOT EXISTS edited_at TIMESTAMPTZ NULL;
