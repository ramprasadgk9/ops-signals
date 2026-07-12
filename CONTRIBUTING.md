# Contributing

Thanks for helping improve Ops Signals.

## Before You Start

- Read the README and the architecture docs
- Check whether your change affects PostgreSQL, Qdrant, or the React UI
- Prefer small, focused pull requests

## Development Workflow

1. Create a branch for your work.
2. Make the change with minimal scope.
3. Run the relevant tests.
4. Update documentation when behavior changes.
5. Open a pull request with a clear summary.

## Code Quality

- Keep behavior deterministic where possible
- Do not add unimplemented claims to docs or UI copy
- Preserve PostgreSQL as the system of record
- Treat Qdrant as a retrieval index, not authoritative storage

## Suggested Checks

- `pytest -q`
- `cd frontend && npm test`

## Reporting Issues

If you find a bug, include:

- what you expected
- what happened instead
- sample input when possible
- any relevant logs or screenshots
