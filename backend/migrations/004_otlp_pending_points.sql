-- New table for OTLP push ingestion (docs/otlp-metrics-ingestion-plan.md). Created automatically
-- at backend startup via Base.metadata.create_all (backend/app/main.py) since it's a new table,
-- not an alter to an existing one - this file documents the same change for anyone reading
-- migration history by hand, same convention as 003_autonomous_policy_scheduling.sql.

CREATE TABLE IF NOT EXISTS otlp_pending_points (
    id SERIAL PRIMARY KEY,
    metric_name TEXT NOT NULL,
    metric_type TEXT NOT NULL,
    timestamp TIMESTAMPTZ NOT NULL,
    value DOUBLE PRECISION NOT NULL,
    service TEXT NOT NULL,
    env TEXT NULL,
    host TEXT NULL,
    namespace TEXT NULL,
    pod TEXT NULL,
    attributes_json JSON NULL,
    received_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_otlp_pending_points_service_metric
    ON otlp_pending_points(service, metric_name);
CREATE INDEX IF NOT EXISTS idx_otlp_pending_points_received_at
    ON otlp_pending_points(received_at);
