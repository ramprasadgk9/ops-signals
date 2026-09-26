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

## Backward Compatibility

Legacy flat configs still work.

If a config file already contains `analysis`, it is treated as a complete configuration and loaded directly.

## Guidance

- put common analyzer defaults in `config/analyzers.yaml`
- keep provider files focused on columns, mappings, and input details
- only add provider-specific analyzer overrides when a provider truly needs them
