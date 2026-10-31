# AGENTS.md

Rules and facts for working in this repository. Detail lives in [`docs/`](docs/README.md) and
[`CONTRIBUTING.md`](CONTRIBUTING.md); this file only holds what's easy to get wrong.

## What this is

Ops Signals analyzes Prometheus and OTLP metrics, explains each change in plain language, links it
to the deploy behind it, and remembers how past incidents were fixed. Main parts:

- `backend/app/` - FastAPI backend: analyzers, pipeline, findings, cases, assistant, MCP server.
- `frontend/` - one React + MUI codebase built two ways: the standalone web UI and the Grafana app
  plugin (`vite.plugin.config.ts`).
- PostgreSQL is the system of record; Qdrant is only a retrieval index (ADR-004, ADR-005).

## Commands

| Task | Command |
| --- | --- |
| First-time setup | `./scripts/setup.sh` |
| Run locally | `./scripts/run_all.sh` - backend `8001`, web UI `5174`, Prometheus `9090` |
| Run with Grafana | `./scripts/run_grafana_stack.sh` - Grafana `3000`, plugin backend `8002` |
| Backend tests | `pytest -q` (Playwright specs live in `tests/scenarios/`; `--ignore=tests/scenarios` for unit tests only) |
| Frontend tests | `cd frontend && npm test` |
| Frontend type check | `cd frontend && npx tsc -b` - `tsc --noEmit -p .` checks nothing |
| Playwright | `./scripts/test_local_integration_scenarios.sh [web-ui\|plugin]` |
| Plugin build | `cd frontend && npm run build:grafana` |
| Assistant retrieval misses | `python -m benchmark.assistant_benchmark` |

## Traps

- **`frontend/dist` is the Grafana plugin.** It's mounted into the local Grafana container. A plain
  `npm run build` overwrites it with the web UI. To check the web UI builds, use
  `npx tsc -b && npx vite build --outDir <somewhere else>`.
- **Dev backends reload on every edit.** `run_all.sh` and `run_grafana_stack.sh` run
  `uvicorn --reload` on `backend/` and share Postgres and Qdrant (`:6333`) with the demo stack. A
  change to Qdrant schema or startup code migrates that shared data. Check UI changes against such
  code on an isolated stack (own Postgres with `sql/init.sql`, own Qdrant, other ports).
- **Tests must not touch dev data.** `tests/conftest.py` swaps Qdrant for an in-memory client, but:
  - a `scope="module"` or `"session"` fixture that builds the app runs before that guard; apply the
    same patch inside it;
  - `SignalPipeline(config)` with no store writes to the dev Postgres from `config.yaml`; pass
    `store=PreviewPipelineStore()` or mock it.
  Both pass locally and fail in CI. Check with `OPS_SIGNALS_QDRANT_URL=http://localhost:6399`.
- **Grafana caches the plugin bundle** (the version tag doesn't change between local builds).
  Reload with DevTools → Network → Disable cache.
- **Local-only docs change assistant results.** The assistant indexes every `docs/**/*.md`, so an
  untracked doc can make `tests/test_assistant_golden.py` fail locally.

## Git

- Work on a branch (`feat/…`, `fix/…`, `docs/…`), never directly on `main`.
- Merge with `git merge --no-ff <branch>` and the default message `Merge branch '<branch>' into main`.
- Never rewrite published history: no force-push, rebase or `filter-repo` on `main`.
- No AI co-author or "Generated with" lines in commits or PR descriptions.
- Never commit: `tmp/`, `video/`, benchmark results, local QA reports, `.env`, secrets.

## Product rules

- **Vendor-neutral.** Don't name or default to a commercial vendor or its prices in the UI, config
  defaults or feature docs. Costs use a rate the user sets; without one, show counts.
- **Plain wording.** Findings and UI copy say what happened in everyday words; statistics go in
  tooltips or details. See [`docs/finding-wording.md`](docs/finding-wording.md).
- **Help sits next to the action.** Walkthroughs and how-tos go in the UI where the user acts
  (button + dialog), not only in docs.
- **No unimplemented claims** in docs or UI copy.
- Deterministic by default: core features work with no LLM (ADR-007).

## How changes are made

- **UI changes start with a mockup**, kept in the gitignored `tmp/mockup/<name>/`, agreed before
  building.
- **Prove a feature with tests.** Add or update unit tests and, for UI flows, a Playwright spec.
- **Benchmarks only when asked**, and a small sample first; full suites take a long time.
- Update docs (`README.md`, `docs/ui-tour.md`, the feature's doc) when behaviour changes. The
  assistant answers from them: open each section with its answer in the words people would ask it
  ([guide](docs/ask-ops-signals-assistant.md#writing-docs-the-assistant-can-answer-from)).
- Raising the assistant golden floors is fine; lowering one needs a reason in the commit message.

## Code Review Rules

**Read-only.** A review changes nothing unless fixes are explicitly asked for: no code edits, no
destructive commands, no database resets, no writes to dev data (see Traps).

**What to look for**, in this order of priority: correctness bugs, security, data integrity and
reliability, then architecture, performance, concurrency, missing error handling and resource
leaks. Skip formatting and naming unless they materially hurt maintainability.

**How to review**

- Read the implementation and follow the execution path across components (API → service →
  pipeline → storage → UI), not just the changed file or its docs.
- Check the change against the architecture, the product rules and the Git rules above.
- Backend: FastAPI endpoints, analyzer selection and execution, the signal pipeline, findings, the
  case lifecycle, PostgreSQL persistence, Qdrant index consistency with Postgres, and external
  integrations (Prometheus, OTLP, Slack, Jira, Alertmanager).
- Frontend: React/MUI behaviour, API calls, loading and error states, accessibility where relevant,
  and that it works in both the standalone and Grafana plugin builds.
- Failure paths: database outages, partial writes, retries, timeouts, duplicate processing,
  concurrent requests and a pipeline that fails halfway. Check whether handling exists; don't
  assume it does.
- Security boundaries: authentication, authorization (roles), input validation, secret handling and
  leaking sensitive data into logs, responses, alerts or tickets.
- Tests: missing unit, integration, regression and negative-path tests.
- Large reviews: go component by component and say which parts were not examined. Never claim a
  complete review of code you didn't read.

**Evidence**

- Verify every finding in the code. Never invent defects or line numbers.
- Keep **confirmed defects** separate from **potential risks** that still need checking.
- Run only relevant, non-destructive checks from the Commands table. Report exactly which ran,
  which passed, which failed and which were not run. Never call an unrun test passing.

**Each finding states:** severity (Critical / High / Medium / Low), `file:line`, what's wrong,
impact or a reproduction scenario, and the recommended fix.

**End every review with:**

1. Confirmed defects, most severe first
2. Potential risks that need verification
3. Missing test coverage
4. Overall assessment and prioritized next steps
