# Changelog

## Unreleased

- Replaced the hardcoded analyzer if/elif chain with a config-driven registry
  (`config/analyzer_registry.d/`) that merges custom registrations additively, never overriding a
  built-in analyzer. Reworked the Add Analyzer wizard to write to this backend, collapsed its
  workflow from 5 steps to 3, and added a two-track Python/API entry choice for new contributors.
- Wired the autonomous monitoring results dashboard onto the configure page - "Run Once" now shows
  what the run actually found instead of a one-line status banner.
- Gave the "Ask Ops Signals" assistant real retrieval and optional local LLM synthesis: automatic
  case indexing, semantic search over findings/behaviors, LLM-assisted routing that only adds
  coverage on top of deterministic keyword routing (never replaces it), and an opt-in local Ollama
  service (`docker compose --profile ai up`, no API key, no cloud calls). Every answer now labels
  whether it came from a model or a template.
- Added a benchmark suite covering detection accuracy (not just router recommendation), a
  false-positive negative control, opt-in router precision checks, and the first multi-metric
  Behavior Intelligence scenarios. See `benchmark/README.md` and `benchmark/CONTRIBUTING.md`.
- Fixed the assistant's document retrieval: ADR files were silently invisible to search (a
  non-recursive glob skipped `docs/adr/`), and documents over 8,000 characters - including
  README.md itself - were truncated rather than fully searchable. Long documents are now chunked
  instead.
- Documentation and governance structure added; operational intelligence architecture clarified;
  PostgreSQL and Qdrant responsibilities documented.

## 0.1.0

- Initial project scaffold
