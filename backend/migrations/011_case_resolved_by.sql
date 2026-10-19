-- Who closed a case, when it was resolved through the Grafana plugin's proxy
-- (backend/app/identity.py). Applied automatically at backend startup via
-- backend/app/models/schema_compat.py::ensure_actor_schema - this file documents the same additive
-- change for anyone reading migration history by hand, same convention as 003-010.

ALTER TABLE ops_operational_cases ADD COLUMN IF NOT EXISTS resolved_by TEXT NULL;
