# Configuration

The configuration system now supports a shared analyzer layer plus provider-specific input files.

## Merge Order

```text
Base config
-> Shared analyzer config
-> Provider config
-> Provider overrides
```

## Files

- `config/config.yaml`: shared output, storage, embeddings, UI, capabilities, and question defaults
- `config/analyzers.yaml`: shared analysis mode, window, and analyzer defaults
- `config/providers/*.yaml`: provider-specific input configuration and any rare provider overrides.
  Editing an existing provider's `provider_mappings`/`required_columns` here takes effect on both
  the CLI run path and the CSV upload API. Adding a brand-new provider file alone is not yet
  enough to make it selectable through the upload API - `backend/app/api/ingestion.py` currently
  only accepts `generic`, `prometheus`, or `datadog` as the `provider` form field.
  `config/providers/otel.yaml` is a deliberate exception: it exists for the OTLP receiver
  (`backend/app/api/otlp.py`) to look up via `provider="otel"`, not for CSV upload - OTLP data
  never goes through `CSVAdapter`, so it isn't (and shouldn't be) selectable in the upload form.
  See [`docs/design/otlp-metrics-ingestion-plan.md`](design/otlp-metrics-ingestion-plan.md).

## Analyzer Settings

Each analyzer's defaults live in `config/analyzer_registry.d/builtin.yml` (`runtime_params`). A
block for it under `analysis.analyzers` in `config/analyzers.yaml` (or a provider file) changes
only the keys it sets: nested blocks such as `implementation` and `finding_rules` merge key by key,
so this changes the trend threshold and keeps the rest of the trend settings:

```yaml
analysis:
  analyzers:
    trend:
      finding_rules:
        min_slope_percent: 5
```

Analyzer Labs' "run with custom params" merges the same way. `enabled` turns an analyzer on or off.
The trend analyzer always fits a straight line by least squares (`model: OLS`); another `model`
value is ignored with a warning in the log.

## Operational Memory and Output

Operational memory (the Qdrant index and the embedding model) and what each run saves are set in the
root `config.yaml`:

```yaml
output:
  save_normalized_data: true
  save_signals: true
  save_question_answers: true
  save_embeddings: true

memory:
  enabled: true
  vector_store:
    provider: qdrant
    url: http://localhost:6333
    collection_name: operational_cases
  embedding:
    provider: sentence_transformers
    model: sentence-transformers/all-MiniLM-L6-v2
    dimension: 384
    normalize_embeddings: true
  indexing:
    automatic_on_case_creation: true
```

`OPS_SIGNALS_QDRANT_URL` and `OPS_SIGNALS_QDRANT_API_KEY` override the vector store's `url` and
`api_key`.

## Pluggable Ticketing Integration (Jira Cloud)

Ops Signals provides a pluggable architecture for bidirectional ticketing integration. The reference implementation integrates with Jira Cloud REST API v3 using a transactional outbox, distributed leases, and Atlassian Document Format (ADF) translation.

Ticketing can be enabled in `config.yaml` or overridden via environment variables.

### YAML Configuration

```yaml
ticketing:
  enabled: true
  active_provider: jira
  worker_poll_interval_seconds: 5.0
  outbox_lease_seconds: 60.0
  outbox_max_attempts: 5
  automatic_on_case_creation: false
  jira:
    base_url: https://your-domain.atlassian.net
    email: your-service-account@example.com
    api_token: your-jira-api-token
    project_key: OPS
    issue_type: Task
    webhook_secret: your-webhook-secret
    request_timeout_seconds: 10.0
```

### Environment Variables

| Variable | Description | Default |
| :--- | :--- | :--- |
| `OPS_SIGNALS_TICKETING_ENABLED` | Enables the ticketing subsystem and API routes. While it is off, the web UI and Grafana plugin hide ticket actions on cases that have no linked ticket (`GET /api/integrations/ticketing/status`) | `false` |
| `OPS_SIGNALS_TICKETING_ACTIVE_PROVIDER` | Active issue-tracking provider (`jira`) | `jira` |
| `OPS_SIGNALS_TICKETING_WORKER_ENABLED` | Runs the background outbox worker loop in the API process, only while ticketing is enabled; `false` stops it even then | `true` |
| `OPS_SIGNALS_TICKETING_WORKER_POLL_INTERVAL_SECONDS` | Outbox polling frequency in seconds | `5` |
| `OPS_SIGNALS_TICKETING_AUTOMATIC_ON_CASE_CREATION` | Automatically creates tickets when new cases are opened | `false` |
| `OPS_SIGNALS_JIRA_BASE_URL` | Jira Cloud instance base URL | `None` |
| `OPS_SIGNALS_JIRA_EMAIL` | Service account email associated with the Atlassian API token | `None` |
| `OPS_SIGNALS_JIRA_API_TOKEN` | Jira Cloud API token (generated from Atlassian Account Settings) | `None` |
| `OPS_SIGNALS_JIRA_PROJECT_KEY` | Target Jira Project Key (e.g. `OPS`, `INCIDENT`) | `None` |
| `OPS_SIGNALS_JIRA_ISSUE_TYPE` | Jira issue type name | `Task` |
| `OPS_SIGNALS_JIRA_WEBHOOK_SECRET` | Secret key for verifying inbound Jira HMAC-SHA256 signatures. Required for the webhook: without it every webhook is refused (401), and status only syncs via Sync now | `None` |
| `OPS_SIGNALS_JIRA_TIMEOUT_SECONDS` | HTTP request timeout for Jira Cloud API calls | `10.0` |

### Jira Webhook Setup

To receive real-time updates when comments or issue statuses change without waiting for polling sync:
1. In Jira Settings, navigate to **System > Webhooks**.
2. Create a webhook pointing to: `https://<your-ops-signals-host>/api/integrations/ticketing/jira/webhook`.
3. Select events: **Issue: updated** and **Comment: created**.
4. Set a secret in Jira and configure `OPS_SIGNALS_JIRA_WEBHOOK_SECRET` in Ops Signals. Inbound payloads will be validated using HMAC-SHA256 signatures.

## Backward Compatibility

Legacy flat configs still work.

If a config file already contains `analysis`, it is treated as a complete configuration and loaded directly.
The root `config.yaml` is one: `intelligence.cli run --config config.yaml` uses its own `analysis`
block, not `config/analyzers.yaml`.

## Guidance

- put common analyzer defaults in `config/analyzers.yaml`
- keep provider files focused on columns, mappings, and input details
- only add provider-specific analyzer overrides when a provider truly needs them
