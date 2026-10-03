# Roadmap

## Near-Term

- broaden analyzer coverage
- refine case lifecycle UX
- improve retrieval filtering
- expand documentation around evaluation and releases

## Mid-Term

- more reusable operational memory patterns
- richer case comparison
- better review flows for investigation and RCA
- multi-source Prometheus backends (Mimir, Thanos):
  - scope analysis by cluster, and tell apart series that differ only by `cluster` or other external labels
  - ignore HA replica labels (`__replica__`, `prometheus_replica`) so duplicated series aren't counted twice
  - several connections, one per Mimir tenant, with a connection picker in the Configure panel
- more AI provider choices (only Ollama today):
  - an OpenAI-compatible endpoint setting, covering vLLM, Azure OpenAI and Bedrock gateways
  - Anthropic
  - keep "no LLM required" as the default

## Long-Term

- deeper evaluation tooling
- richer extensibility for analyzers and capabilities
- better support for iterative operational learning
