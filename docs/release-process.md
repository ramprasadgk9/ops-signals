# Release Process

## Release Goals

- preserve reproducibility
- keep docs aligned with behavior
- avoid overstating capability

## Suggested Steps

1. Validate tests.
2. Review docs for accuracy.
3. Update changelog.
4. Tag the release when ready.

## Versioning

This repository currently follows an early-stage release process. Public version claims should match the actual project state.

There are two version numbers, and they are meant to differ:

- **The project version** (`pyproject.toml`, `frontend/package.json`, the `vX.Y.Z` git tag and the
  CHANGELOG heading) is the version of Ops Signals as a whole: backend, web UI, MCP server and
  container images. It is still `0.x`.
- **The Grafana plugin version** (`info.version` in `frontend/plugin.json`) belongs to the plugin
  alone. Grafana compares it to decide whether an installed plugin needs updating, so it only ever
  goes up, and it is bumped on every project release that changes the plugin. It is `1.0.x` because
  the plugin was versioned before the project was, and it is not reset to match.

The release notes for a project version name the plugin version it ships, for example
"v0.3.0 includes Grafana plugin 1.0.32".
