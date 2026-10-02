# OTLP Metrics Ingestion Plan (Implemented)

**Status:** Implemented. Verified with unit tests
(`tests/test_otlp_adapter.py`), integration tests (`tests/api_backend/test_otlp_ingestion.py`),
and a manual end-to-end run against a live Postgres instance (real OTLP protobuf payload → stored
→ scheduler cycle → completed `analysis_run`). Two implementation-time refinements to what's
written below, both discovered while wiring the scheduler step against the actual codebase — see
"Implementation notes" immediately below §5.

**Extends:** [`docs/02-architecture.md`](../02-architecture.md) (roadmap item: "OpenTelemetry
Collector ingestion", currently listed under Not Yet Implemented), [`README.md`](../../README.md)
§12 (Current Limitations).

---

## 1. Why

Ops Signals currently ingests two ways: CSV upload and pull-based Prometheus queries. Industry
data (Grafana Labs' 2026 Observability Survey) shows OpenTelemetry has become the de facto
ingestion format most new tooling is expected to speak — 57% of respondents use it for metrics,
and 89% of production users call OTel compliance "very important" when evaluating a new tool. Not
speaking OTLP is an adoption blocker, not a missing nice-to-have. This plan covers **metrics
only** — logs and traces are separate, larger efforts, deliberately out of scope here.

---

## 2. Scope (phase 1)

- OTLP/**HTTP** only (protobuf and JSON bodies, both required by spec). No OTLP/gRPC — would
  require a second server process (`grpc.aio`) alongside FastAPI/uvicorn for comparatively little
  gain, since any sender can be pointed at the HTTP exporter instead.
- Metric types: **Gauge and Sum (counter)** only. Histogram / ExponentialHistogram / Summary are
  received, counted, and rejected via `partial_success` — not silently dropped, not crashed on.
- **Store immediately, analyze on a timer** — not per-request analysis. OTLP is a continuous push;
  running the full analyzer pipeline on every incoming batch (potentially every 10–60s per sender)
  would be wasteful and give each run too little history to reason about.

---

## 3. Endpoint

`POST /api/otlp/v1/metrics`

Not the OTLP-spec-default root path `/v1/metrics`, because `docker/nginx.web.conf` only proxies
`/api/` to the backend, and every other route in this app already lives under `/api/*`. This stays
reachable through the same proxy path as everything else with zero infra changes. Still
spec-compliant: an OTel Collector's `otlphttp` exporter accepts an explicit
`endpoint: http://<host>:<port>/api/otlp` and auto-appends `/v1/metrics` itself. This deviation
from the naive "point it at root" assumption must be called out clearly in user-facing docs.

Separately, note the backend container already exposes its own port directly in
`docker-compose.packaged.yml` (`8000:8000`, distinct from `web`'s `8080:8080`) — so a sender can
also hit the backend directly, bypassing nginx entirely, if preferred.

---

## 4. Data flow

```
OTel SDK / Collector
  -> POST /api/otlp/v1/metrics (protobuf or JSON)
  -> size check, rate check (§6)
  -> parse resourceMetrics -> scopeMetrics -> metrics -> dataPoints
  -> reject unsupported metric types (Histogram/ExponentialHistogram/Summary)
  -> cardinality check per metric (§6)
  -> flatten into raw DataFrame (source-native columns, same shape CSVAdapter produces)
  -> normalize_timeseries() with new "otel" provider branch
  -> PostgresStore.save_normalized_points() (analysis_run_id = NULL = "pending")
  -> respond: empty success, or partial_success naming what was dropped and why
  ...independently, on a timer...
  -> scheduler poll loop finds analysis_run_id IS NULL rows (bounded per cycle, §6)
  -> groups by (service, metric_name) -> TimeSeriesRoutingService -> analyzers -> findings
  -> stamps rows with the new analysis_run_id
```

---

## 5. File-by-file changes

**`requirements.txt`** — add `opentelemetry-proto` (generated protobuf message classes for
`ExportMetricsServiceRequest`/`Response`; pure-Python, no gRPC runtime needed for HTTP-only
support).

**`backend/app/api/otlp.py`** (new) — FastAPI router, prefix `/api/otlp`.
- `Content-Type: application/x-protobuf` → `ExportMetricsServiceRequest.FromString(body)`
- `Content-Type: application/json` → `google.protobuf.json_format.Parse` (OTLP JSON follows
  canonical protobuf JSON encoding, not an ad-hoc shape)
- Optional bearer-token auth header, same pattern as `PrometheusConnectionConfig.bearer_token`,
  off by default to match the project's local-first, no-auth-required-out-of-the-box posture.

**`intelligence/normalize/normalizer.py`** — add an `otel` branch to `_apply_provider_mappings()`
(same shape as the existing `datadog` branch, [normalizer.py:124](../../intelligence/normalize/normalizer.py#L124)):
- `service.name` resource attribute → `service`
- `deployment.environment` / `deployment.environment.name` → `env`
- `host.name` → `host`
- `k8s.namespace.name` → `namespace`, `k8s.pod.name` → `pod`
- OTLP `metric_type` (`gauge`/`sum`) passed straight through — `_is_running_total()` already keys
  off exactly this column for counters, no changes needed there.

**`intelligence/adapters/csv_adapter.py`** / normalizer — add `"otel"` to the allowed-provider set
(currently `{"generic", "prometheus", "datadog", "custom"}`).

**`config/providers/otel.yaml`** (new) — same shape as `datadog.yaml` / `prometheus.yaml`:
`provider: otel`, `required_columns`. No `provider_mappings` dict needed — the normalizer branch
above renames directly, same as the `prometheus` branch does today.

**Storage** — no new table. Reuses `PostgresStore.save_normalized_points()`
([postgres_store.py:177](../../intelligence/storage/postgres_store.py#L177)) and the existing
`analysis_run_id IS NULL` convention as the "pending analysis" marker.

**`backend/app/autonomous/scheduler.py`** — add a second poll function alongside
`_run_one_policy`. Every `POLL_INTERVAL_SECONDS`, query pending `source = 'otel'` rows (bounded,
§6), group by `(service, metric_name)`, run each group through `TimeSeriesRoutingService`, write an
`AnalysisRunEntity`, stamp processed rows. Reuses the existing, explicitly-documented
single-instance/no-distributed-queue design rather than introducing new infrastructure.

**`backend/app/main.py`** — `app.include_router(otlp_router)`.

---

## Implementation notes (deviations from the design above)

**1. A new staging table, not the `analysis_run_id IS NULL` marker on `normalized_timeseries_points`.**
Reading `backend/app/autonomous/execution.py` while implementing the scheduler step surfaced the
actual reusable primitive: `MetricAnalysisExecutor.execute_dataframe()` already does
normalize → route → analyze → save (including writing `normalized_timeseries_points` itself) for
one `(service, metric_name)` group in a single call — it's exactly what the Prometheus autonomous
path already uses per planned metric. That means the OTLP receiver never needs to call
`normalize_timeseries()` or `PostgresStore.save_normalized_points()` directly; it only needs a
transient inbox to buffer raw points between receipt and the next batch. New table:
`otlp_pending_points` (`backend/app/models/entities.py::OtlpPendingPointEntity`) — rows are
deleted once a cycle folds them into a `MetricAnalysisExecutor` call, so its size *is* the
backlog metric, not a filtered view of history the way `analysis_run_id IS NULL` would have been.

**2. No normalizer `otel` provider branch was needed.** The original plan assumed OTLP's raw,
source-native attribute keys (`service.name`, etc.) would need a rename step in
`_apply_provider_mappings()`, mirroring the `datadog` branch. But the OTLP receiver controls the
DataFrame shape it hands to `normalize_timeseries()` directly (unlike CSV, where the file's raw
columns come from whatever an arbitrary uploaded file happens to call them) — so
`backend/app/otlp/converter.py` emits canonical column names (`service`, `env`, `host`,
`namespace`, `pod`) itself, and no mapping step is needed. `config/providers/otel.yaml` and
`provider="otel"` are kept anyway, purely for `source` tagging on stored points and for the
`load_routing_app_config("otel")` lookup `build_csv_routing_config()` needs — not for renaming.

**3. `_analyze_otlp_group` infers the resample interval from the actual data, not a hardcoded "1m".**
Found while building `scripts/send_test_otlp_metrics.py` for manual UI verification: a synthetic
5-minute-spaced series analyzed cleanly by sample count (`analysis_runs.sample_count`) but 1,148
of 1,436 normalized rows came back `NaN` — the hardcoded `interval="1m"` passed to
`build_csv_routing_config()` made `normalize_timeseries()`'s resample step
(`intelligence/normalize/normalizer.py`) bucket into 1-minute windows against data arriving every
5 minutes, leaving most buckets empty. Real OTel senders commonly export at 10s/15s/30s/60s, so a
fixed interval would have silently diluted the signal analyzers see for any sender whose cadence
didn't happen to match. Fixed by deriving the interval from the median gap between a group's
actual timestamps (`_infer_interval()`) — the same principle
`backend/app/autonomous/execution.py` already applies to Prometheus (deriving interval from the
query's real `step_seconds` rather than assuming one). Regression-tested in
`tests/api_backend/test_otlp_ingestion.py::test_infer_interval_matches_the_actual_gap_between_points`.

---

## 6. Volume and cardinality protection

OTLP is the first **always-on, sender-controlled-volume** ingestion path in this codebase —
everything else today is either a one-time upload or an on-demand pull the app itself paces. That
means it's also the first path that needs its own guardrails; nothing upstream naturally throttles
it the way a "click upload" action does. Three independent caps, each guarding a different failure
mode, each an env var with a conservative single-instance default — tune up for bigger Postgres,
tune down for constrained hardware:

| Env var | Default | Acts at | Protects against |
|---|---|---|---|
| `OPS_SIGNALS_MAX_OTLP_BYTES` | `10485760` (10MB) | Request entry, before parsing | An oversized single request wasting CPU before it's even rejected |
| `OPS_SIGNALS_OTLP_MAX_POINTS_PER_MIN` | `60000` (1000 pts/sec) | Per sender, before DB write | The write path / DB connection pool being overwhelmed by raw volume |
| `OPS_SIGNALS_OTLP_MAX_SERIES_PER_METRIC` | `2000` | Per metric, before storing a *new* distinct label combination | Cardinality explosion — the costlier, sneakier failure mode (more distinct series, not more points) |
| `OPS_SIGNALS_OTLP_MAX_BACKLOG_PER_CYCLE` | `5000` rows | Scheduler poll cycle, not request-time | One large backlog making a poll cycle run indefinitely and starve the next cycle |

Note `OPS_SIGNALS_OTLP_MAX_SERIES_PER_METRIC`'s default (2000) is deliberately not copied from the
existing `OPS_SIGNALS_PROMETHEUS_MAX_SERIES` default (20, in `backend/app/config.py`) — that
existing cap bounds a small, interactive, human-facing query preview; this one bounds sustained
background ingestion capacity, a different context entirely.

Rate-limit and cardinality rejections use OTLP's built-in backpressure contract: a retryable error
(HTTP 429/503, or `partial_success` in the response) that every compliant OTel sender already
knows how to back off and retry against — this is spec-intended behavior, not a workaround.

---

## 7. Self-observability: `/api/metrics`

A tool whose pitch is "explain what's happening, don't just show a number" should apply that
standard to its own ingestion pipeline. New endpoint, Prometheus exposition format (via the
`prometheus_client` library), on the same backend process:

- `otlp_points_received_total`
- `otlp_points_rejected_total{reason="rate_limit"|"cardinality_limit"|"unsupported_type"}`
- `otlp_backlog_size` (gauge, computed live: `count(*) where analysis_run_id IS NULL`)
- `otlp_analysis_cycle_duration_seconds`

Chosen over a bespoke JSON status endpoint because this project's actual audience already runs
Prometheus (it's one of the two existing data sources) — a standard `/metrics` target means
zero new tooling for them: one scrape-config line, and it's graphable/alertable in the Grafana
they already have. A custom JSON shape would need its own glue on their end for no real benefit.

---

## 8. Docs updates (done)

- `docs/02-architecture.md` — moved OpenTelemetry out of the Roadmap (Not Yet Implemented) list;
  noted logs/traces remain future work.
- `README.md` "OTLP Metrics Ingestion" (new) — endpoint URL, the `/api/otlp` path caveat, a copy-pasteable Collector
  config snippet, the four env vars, and a pointer to this document for the full design and the
  `/api/metrics` self-observability endpoint. "Current Limitations" — added the
  single-instance/HTTP-only/metrics-only line, pointing at §10 below.
- A dedicated `docs/28-otlp-ingestion.md` was **not** created separately — this document already
  serves as the single source of truth (design + "why" + scaling notes) and README's "OTLP Metrics Ingestion" section is the
  short, task-oriented pointer into it. Splitting them would just create two documents to keep in
  sync for no reader benefit.

---

## 9. Testing (done)

- Unit (`tests/test_otlp_adapter.py`, 7 tests): gauge/counter flattening with resource-attribute
  mapping, data-point attributes overriding resource attributes, Histogram/Summary rejection
  count, missing-value rejection, JSON/protobuf conversion parity, `RateLimiter` window behavior,
  `CardinalityTracker` per-metric cap behavior.
- Integration (`tests/api_backend/test_otlp_ingestion.py`, 7 tests): protobuf export accepted and
  stored, JSON export accepted and stored, malformed body → 400, oversized body → 413, rate-limited
  batch → 429 + `Retry-After` + nothing stored, cardinality cap → `partial_success` +
  only-allowed-series stored, and a full scheduler-cycle test (push → buffered →
  `_run_pending_otlp_analysis_once()` → backlog cleared).
- Manual, against live Postgres (not sqlite), two passes:
  - A synthetic `ExportMetricsServiceRequest` posted via `curl` to a locally-running backend —
    confirmed rows landed in `otlp_pending_points` with correct `service`/`env`/`host` mapping,
    `/api/metrics` counters moved, and running `_run_pending_otlp_analysis_once()` produced a
    `completed` `analysis_runs` row and cleared the backlog to zero.
  - `scripts/send_test_otlp_metrics.py` (a 288-point series shaped like
    `scripts/generate_learning_data.py`'s known-good baseline/step/trend pattern) — this run is
    what surfaced and confirmed the fix for the interval bug in Implementation note 3 above:
    before the fix, `sample_count=1436` with 1,148 `NaN` rows and no finding; after,
    `sample_count=288`, zero `NaN` rows, and a real finding (`"cpu_usage is trending in one
    direction"`, category `behavior_change`, importance `0.78`) visible through `GET
    /api/findings`, the same endpoint the Findings UI page reads. `otel-collector-contrib` against
    a live Collector was not exercised — the protobuf/JSON wire format was validated directly
    instead, which exercises the same code path an actual Collector export would hit.
- All pre-existing tests in the touched-adjacent files (`test_csv_pipeline.py`,
  `test_csv_adapter_row_limit.py`, `test_autonomous_policies.py`, `test_api.py`) still pass, and a
  full `tests/` run (411 tests) passes clean.

---

## 10. Explicit non-goals (phase 1)

- No OTLP/gRPC.
- No logs, no traces.
- No Histogram/ExponentialHistogram/Summary metric types.
- No multi-instance safety for the new scheduler poll loop — same limitation the existing
  scheduler already has and documents.
- No dynamic/adaptive throttling — caps are static env vars, not auto-tuned.
- No live `otel-collector-contrib` end-to-end run — validated at the wire-format level instead
  (see §9); worth doing before a first real-world deployment.

---

## 11. Implementation order (as built)

1. `config/providers/otel.yaml` + `intelligence/adapters/csv_adapter.py` provider allowlist.
2. `backend/app/models/entities.py::OtlpPendingPointEntity` (+ documentation-only
   `backend/migrations/004_otlp_pending_points.sql`, auto-created via `Base.metadata.create_all`).
3. `backend/app/otlp/converter.py`, `limits.py`, `metrics.py`.
4. `backend/app/api/otlp.py` (receiver) + `backend/app/api/metrics.py` (self-observability) +
   registration in `backend/app/main.py`.
5. `backend/app/autonomous/scheduler.py` extension (`_analyze_otlp_group`,
   `_run_pending_otlp_analysis_once`, hooked into `run_scheduler_loop`).
6. Tests (§9), manual verification against live Postgres, docs updates (§8).
7. `scripts/send_test_otlp_metrics.py` - a demo/smoke-test script, added after manual UI
   verification surfaced the interval bug in Implementation note 3.
8. `GET /api/otlp/status` (`backend/app/otlp/metrics.py::snapshot()`) + an ingestion card
   (`frontend/src/components/OtlpIngestionCard.tsx`, first on the Settings page, since moved to the
   Integrations page next to `GET /api/ingestion/status`, which adds a restart-proof "last point
   received" time) - Prometheus's connection flow has a URL field and a
   "Test Connection" button because Ops Signals *pulls* from it; OTLP is the reverse (Ops Signals
   never connects out, so there's nothing to "test"), which left the endpoint address and whether
   data is actually arriving completely invisible in the app itself - discoverable only by reading
   README. The card shows the endpoint URL (copy button) and live counts from a JSON summary of
   the same registry `/api/metrics` exposes, auto-refreshed every 10s - the closest honest
   equivalent of a passive "yes, it's working" signal for a push-based integration. Verified with
   a headless-browser screenshot in both empty and receiving states (see PR/commit for images) and
   3 unit tests (`frontend/src/pages/SettingsPage.test.tsx`).

Matches the originally suggested order exactly through step 6, aside from the two refinements
noted above §6; steps 7-8 were follow-on work added later in the same session.
