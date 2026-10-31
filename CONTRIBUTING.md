# Contributing

Thanks for helping improve Ops Signals.

## Before You Start

- Read the README and the architecture docs
- Check whether your change affects PostgreSQL, Qdrant, or the React UI
- Prefer small, focused pull requests
- Skim [`AGENTS.md`](AGENTS.md): the project's conventions, commands and known traps (it's also what
  AI coding assistants read; `CLAUDE.md` just imports it)

## Development Workflow

1. Create a branch for your work.
2. Make the change with minimal scope.
3. Run the relevant tests.
4. Update documentation when behavior changes. Ask Ops Signals answers from every doc, so open each
   section with its answer in the words people would ask it
   ([Writing docs the assistant can answer from](docs/ask-ops-signals-assistant.md#writing-docs-the-assistant-can-answer-from)).
5. Open a pull request with a clear summary.

## Code Quality

- Keep behavior deterministic where possible
- Do not add unimplemented claims to docs or UI copy
- Preserve PostgreSQL as the system of record
- Treat Qdrant as a retrieval index, not authoritative storage

## Suggested Checks

- `pytest -q`
- `cd frontend && npm test`
- `./scripts/backend_test_report.py` - runs the backend tests and writes an HTML list of every test,
  what it checks and its result to `tmp/reports/backend-tests-<date>.html`

## Adding a Benchmark Scenario

If your change affects analyzer routing, detection accuracy, or Behavior Intelligence, consider
adding a benchmark scenario alongside it - see
[`benchmark/CONTRIBUTING.md`](benchmark/CONTRIBUTING.md) for a walkthrough.

## Reporting Issues

If you find a bug, include:

- what you expected
- what happened instead
- sample input when possible
- any relevant logs or screenshots
