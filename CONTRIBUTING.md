# Contributing

Thanks for helping improve Ops Signals. This page covers how to find something to work on, set up
your machine, and get a pull request merged.

## Find Something to Work On

- **First contribution?** Pick an issue labelled
  [`good first issue`](https://github.com/ramprasadgk9/ops-signals/labels/good%20first%20issue).
  Each one has a "Where to start" comment naming the files involved.
- **Want something bigger?** Look at
  [`help wanted`](https://github.com/ramprasadgk9/ops-signals/labels/help%20wanted).
- **Claim it** by commenting on the issue ("I'd like to take this"), so two people don't do the same
  work. If you stop, say so in a comment and the issue goes back to the pool.
- **Have an idea that isn't an issue yet?** Start a thread in
  [Discussions → Ideas](https://github.com/ramprasadgk9/ops-signals/discussions/categories/ideas).
  For questions about setup or usage, use
  [Discussions → Q&A](https://github.com/ramprasadgk9/ops-signals/discussions/categories/q-a).

## Set Up Your Machine

You need Docker, Python 3.11 or newer, and Node.js.

```bash
./scripts/setup.sh
./scripts/run_all.sh
```

`setup.sh` installs dependencies and starts PostgreSQL and Qdrant in Docker. `run_all.sh` starts
the backend (`:8001`), the web UI (`:5174`) and Prometheus (`:9090`). If something fails, see
[Troubleshooting](docs/getting-started.md#troubleshooting). For backend and frontend layout, see
the [Development Guide](docs/development-guide.md).

**Rather not install anything?** Open the repository in GitHub Codespaces (**Code → Codespaces →
Create codespace**) or in VS Code with **Dev Containers: Reopen in Container**. The container comes
with Python, Node and Docker and runs `setup.sh` for you; when it's done, run
`./scripts/run_all.sh` in its terminal. The first build takes a while (it installs PyTorch) and
needs a machine with at least 4 cores and 8 GB of memory.

Three things that catch newcomers (the full list is in [`AGENTS.md`](AGENTS.md#traps)):

- **Don't run a plain `npm run build` in `frontend/`.** `frontend/dist` is the Grafana plugin
  bundle, and a plain build overwrites it with the web UI. To check the web UI builds, use
  `npx tsc -b && npx vite build --outDir /tmp/web-ui-check`.
- **The dev backend reloads on every edit** and shares PostgreSQL and Qdrant with the local demo,
  so a change to startup or schema code changes that data.
- **Tests must not touch your dev data.** `tests/conftest.py` swaps Qdrant for an in-memory client,
  but a module- or session-scoped fixture that builds the app runs before that guard, and
  `SignalPipeline(config)` with no store writes to the dev PostgreSQL. Pass
  `store=PreviewPipelineStore()` or mock it. Check with
  `OPS_SIGNALS_QDRANT_URL=http://localhost:6399 pytest -q`.

## Common Kinds of Contribution

- **Fix a bug.** Add a test that fails before your fix and passes after.
- **Add an analyzer.** Follow [Analyzer Plugin Framework → Extensibility
  Model](docs/analyzer-plugin-framework.md#extensibility-model). For an analyzer that runs as your
  own HTTP service, see [`docs/http-analyzer-contract.md`](docs/http-analyzer-contract.md).
- **Add a benchmark scenario** when your change affects analyzer routing, detection accuracy or
  Behavior Intelligence. See [`benchmark/CONTRIBUTING.md`](benchmark/CONTRIBUTING.md).
- **Improve the docs.** Ask Ops Signals answers from every doc, so open each section with its
  answer in the words people would ask it
  ([Writing docs the assistant can answer from](docs/ask-ops-signals-assistant.md#writing-docs-the-assistant-can-answer-from)).

## Bigger Changes

Open a thread in Discussions → Ideas, or an issue, before writing a lot of code. Agreeing on the
approach first saves you rework. Changes to the architecture (storage, the signal → finding → case
model, how analyzers plug in) are recorded as an ADR in [`docs/adr/`](docs/adr/). UI changes start
with a mockup or screenshot in the issue.

## Make the Change

1. Fork the repository and create a branch: `fix/…`, `feat/…` or `docs/…`.
2. Keep the change small and focused. One pull request per problem.
3. Add or update tests. UI flows get a Playwright spec in `tests/scenarios/`.
4. Update the docs when behavior changes (`README.md`, `docs/ui-tour.md`, the feature's doc), and
   `CHANGELOG.md` under "Unreleased" if users will notice.
5. Run the checks below.
6. Commit with `git commit -s` (see [Sign Off Your Commits](#sign-off-your-commits)).
7. Open a pull request and fill in the template. Link the issue with "Fixes #123".

## Sign Off Your Commits

Every commit in a pull request needs a `Signed-off-by:` line with your name and email. It says you
wrote the change, or otherwise have the right to submit it, under the project's MIT license. This is
the [Developer Certificate of Origin](https://developercertificate.org/) (DCO), the same rule many
open-source projects use. It isn't a contract and you don't sign anything else.

Add the line by committing with `-s`:

```bash
git commit -s -m "fix(ingestion): warn about duplicate CSV timestamps"
```

This appends `Signed-off-by: Your Name <you@example.com>`, using your `user.name` and `user.email`
from git config. A **DCO** check on the pull request shows which commits are missing it.

**Forgot to sign off?** On your own branch, either:

- add the missing line to past commits and update the pull request:
  `git rebase --signoff main && git push --force-with-lease`, or
- add one extra commit whose message has the text the DCO check's details page gives you, if you'd
  rather not rewrite your branch.

## Checks to Run

| What | Command |
| --- | --- |
| Backend unit tests | `pytest -q --ignore=tests/scenarios` |
| Frontend tests | `cd frontend && npm test` |
| Frontend type check | `cd frontend && npx tsc -b` (`tsc --noEmit -p .` checks nothing) |
| Browser scenarios | `./scripts/test_local_integration_scenarios.sh web-ui` |
| Backend test report | `./scripts/backend_test_report.py` writes an HTML list of every test and its result to `tmp/reports/` |

## Project Rules

These apply to every change. The reasons are in [`AGENTS.md`](AGENTS.md).

- **Deterministic by default.** Core features work without an LLM.
- **PostgreSQL is the system of record.** Qdrant is only a retrieval index.
- **Plain wording.** Findings and UI text say what happened in everyday words; statistics go in
  tooltips. See [`docs/finding-wording.md`](docs/finding-wording.md).
- **Vendor-neutral.** Don't name or default to a commercial vendor or its prices.
- **No unimplemented claims** in docs or UI text.

## Using AI Coding Assistants

You're welcome to use them. `AGENTS.md` is written so they follow the project's conventions
(`CLAUDE.md` just imports it). You're responsible for what you submit: read it, understand it, and
test it as if you wrote it by hand. Don't add AI co-author or "Generated with" lines to commits or
pull requests.

## What Happens After You Open a Pull Request

- The maintainer reviews it, usually within a week. Small pull requests get reviewed faster.
- CI runs on demand: the maintainer starts it before merging, so don't worry if checks don't appear
  right away.
- You may be asked for changes. Push them to the same branch.
- Once approved, the maintainer merges it. You're added to the Contributors list in the README and
  thanked in the next release's notes.

## Reporting Issues

Use the bug report or feature request form when you open an issue. For a bug, include:

- what you expected
- what happened instead
- sample input when possible
- any relevant logs or screenshots

For security problems, don't open a public issue. See [`SECURITY.md`](SECURITY.md).
