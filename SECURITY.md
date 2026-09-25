# Security Policy

## Supported Versions

This repository is under active development. Security fixes should be applied to the current main branch.

## Reporting a Vulnerability

If you discover a security issue, do not open a public issue.
Instead, report it privately through the project maintainer or the repository's preferred private contact channel.

Please include:

- a description of the issue
- impact and affected component
- reproduction steps if safe to share
- suggested mitigation if available

## Deployment Security

Ops Signals is designed to run inside a trusted network. The API has no authentication unless
`OPS_SIGNALS_API_TOKEN` is set, and the endpoints that delete data or write files are disabled
unless you turn them on. See [docs/security-model.md](docs/security-model.md) before exposing it
beyond your own machine.
