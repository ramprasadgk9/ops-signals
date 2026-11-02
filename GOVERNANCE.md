# Governance

Ops Signals is run by its maintainers, listed in [MAINTAINERS.md](MAINTAINERS.md), with a lead
maintainer who has the final say when maintainers can't agree. This page says how decisions are
made and how contributors become maintainers.

## Roles

- **Contributors** are everyone who opens an issue, answers in Discussions, reviews or sends a pull
  request. Everyone whose pull request is merged is listed in the README and thanked in the release
  notes.
- **Maintainers** review and merge pull requests, triage issues, run CI before merging, cut
  releases, and enforce the [Code of Conduct](CODE_OF_CONDUCT.md).
- **The lead maintainer** (Ramprasad Goturkarnam, the project's creator) sets the roadmap and
  breaks ties between maintainers.

## How Decisions Are Made

- **Everyday changes** (bug fixes, docs, small features): one maintainer's approval is enough to
  merge.
- **Bigger changes** (new features, changes to the architecture or the
  [project rules](CONTRIBUTING.md#project-rules), new dependencies, breaking changes to the API or config): discuss
  them first in an issue or [Discussions → Ideas](https://github.com/ramprasadgk9/ops-signals/discussions/categories/ideas).
  Maintainers aim for agreement; when they can't agree, the lead maintainer decides and writes down
  why in the thread.
- **Architecture decisions** that change how the system works are recorded as ADRs in
  [`docs/adr/`](docs/adr/).
- **Releases** are cut by a maintainer following [`docs/release-process.md`](docs/release-process.md).

## Becoming a Maintainer

There's no fixed number of pull requests. A contributor is usually invited after they have:

- had several substantial pull requests merged,
- reviewed or helped others in issues, pull requests or Discussions, and
- shown they follow the product rules and the Code of Conduct.

Any maintainer can propose a contributor. The maintainers agree, the lead maintainer confirms, and
the new maintainer is added to [MAINTAINERS.md](MAINTAINERS.md) in a pull request.

## Stepping Down

A maintainer can step down at any time by opening a pull request that removes them from
MAINTAINERS.md. A maintainer who has been inactive for six months may be asked whether
they want to stay on. If the lead maintainer steps down, the remaining maintainers choose a new
lead.

## Changing This Document

Changes to this page go through a pull request that every active maintainer approves.
