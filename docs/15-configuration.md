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
- `config/providers/*.yaml`: provider-specific input configuration and any rare provider overrides

## Backward Compatibility

Legacy flat configs still work.

If a config file already contains `analysis`, it is treated as a complete configuration and loaded directly.

## Guidance

- put common analyzer defaults in `config/analyzers.yaml`
- keep provider files focused on columns, mappings, and input details
- only add provider-specific analyzer overrides when a provider truly needs them
