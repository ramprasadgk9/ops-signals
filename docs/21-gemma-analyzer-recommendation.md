# Gemma Analyzer Recommendation Exploration

This path keeps the deterministic analyzer router as the source of technical eligibility and uses Gemma as an optional second-pass judge.

## Flow

1. Profile the time series with the existing router feature extraction.
2. Build deterministic analyzer decisions from `experiments/analyzer_router/analyzer_registry.yaml`.
3. Send Gemma a compact JSON prompt containing:
   - metric context
   - profile features
   - downsampled timestamp/value points
   - available analyzers, supported patterns, matched patterns, router score, and warnings
4. Require Gemma to return validated JSON with one `best_analyzer_id`, recommended analyzers, rejected analyzers, rationale, and caveats.
5. Treat Gemma output as advisory unless you explicitly promote it into routing policy.

## Local Model

The existing Ollama provider can run Gemma without a new backend provider. Example:

```yaml
ai:
  enabled: true
  provider: ollama
  temperature: 0.0
  max_tokens: 900
  timeout_seconds: 60
  ollama:
    base_url: http://localhost:11434
    model: gemma3:4b
```

Use a larger Gemma variant if the analyzer catalog grows or if you include longer raw samples in the prompt.

## Implementation

The prompt and response contract live in:

`backend/app/metric_analyzer_recommendations/gemma_advisor.py`

The advisor accepts a `StructuredLLMService`, so it works with Ollama-backed Gemma today and any future structured LLM provider later.
