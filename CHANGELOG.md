# Changelog

## Unreleased

- **Behavior change:** `POST /api/testing/reset-operational-data` is gone unless
  `OPS_SIGNALS_ENABLE_TESTING_API=true`, and the endpoints that write files on the server (saving,
  promoting and deleting analyzers, generating adapter code, saving behavior definitions to a pack)
  return 403 unless `OPS_SIGNALS_ALLOW_FILE_WRITES=true`. The dev scripts turn both on, and the
  demo turns on file writes.
- Added an optional API token (`OPS_SIGNALS_API_TOKEN`) that protects every endpoint except
  `/api/health`. The alert and event receivers use it when they have no token of their own. The web
  UI's nginx adds it on the server side, the Grafana plugin has a field for it, and Helm reads it
  from a Secret.
- CORS origins are now configurable with `OPS_SIGNALS_CORS_ORIGINS`.
- Fixed: the behavior-definition `pack_file` accepted paths, so a request could write YAML outside
  `config/behavior_definitions.d/`. It must now be a bare `.yml`/`.yaml` file name.
- Fixed: an analyzer's display name and library went into the generated adapter code unescaped,
  so a crafted name could inject code that ran when the adapter was imported.
- Added [`docs/security-model.md`](docs/security-model.md).
- Renamed `OPS_INTEL_DATABASE_URL` to `OPS_SIGNALS_DATABASE_URL`, so every setting uses the same
  `OPS_SIGNALS_` prefix. The old name still works, and the new one wins when both are set.
- The API now calls itself "Ops Signals API" (it was "Ops Intelligence API").
- Analyzers added through the Add Analyzer wizard now run on scheduled (autonomous) runs too.
  Those runs used to build only the 7 built-ins from a hardcoded list; they now read
  `config/analyzer_registry.d/` like CSV runs do.
- Analyzers added through the wizard now appear in the Recommendations view, MCP and the AI
  second opinion. The recommendation service used to skip `config/analyzer_registry.d/`.
- Added two registry options for guard-style analyzers, also available as wizard switches:
  `accepts_flat_or_gappy_series` (don't reject flat, gappy or zero-variance series) and
  `always_run` (run outside the `max_analyzers` limit). Scoring rules can now use
  `constant_value_percentage`.
- Fixed: on a scheduled run, an analyzer that raised an error crashed the run with a `NameError`
  instead of being recorded as failed.

## 0.2.0 - 2026-09-14

- Let a Behavior Finding (a correlated, cross-metric pattern) be promoted to a Case, not just a
  single-metric Finding - behaviors previously had no path to an RCA, resolution, or recorded
  outcome at all.
- Added `GET /api/alert-context`: a single lookup an external alert manager can call before firing
  an alert, combining exact-match learning-outcome history, semantically similar resolved cases,
  and raw finding/behavior recurrence (patterns that occurred but were never cased) into one
  recommendation - with an optional AI-polished summary that falls back to a deterministic
  sentence whenever AI is off or fails.
- Fixed: resolving a case as "Resolved" failed silently - the Resolution tab had no field for the
  required `learning_outcome_status`, so the save request was rejected with no visible error and
  the case's outcome was never actually recorded.
- Fixed: repeated analysis runs on the same data produce findings/behaviors with byte-identical
  auto-generated titles - the alert-context "raw activity" list now shows distinct titles instead
  of the same sentence repeated.
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
