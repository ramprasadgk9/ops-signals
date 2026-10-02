# How Ops Signals Compares

People evaluating Ops Signals usually ask how it relates to tools they already know. This page
answers that for the three that come up most: Robusta (with HolmesGPT), Keep, and Grafana Sift.

Ops Signals works alongside these tools, not instead of them. Each one solves a different part of
the "an alert fired, now what?" problem, and some of them can run next to Ops Signals.

> **Last checked: September 2026.** These projects ship often. Every statement about another tool
> below links to that tool's own docs. If something here is out of date, please open an issue or a
> PR.

## At a glance

| | Robusta + HolmesGPT | Keep | Grafana Sift | Ops Signals |
|---|---|---|---|---|
| **Main job** | Better Prometheus alerts on Kubernetes, with context, grouping, AI investigation and remediation | Alert hub: dedup, correlation and workflows across many monitoring tools | ML checks over Kubernetes telemetry during an incident | Explain what the alerting metric did, what changed, and whether it has been seen before |
| **License / hosting** | Robusta MIT, HolmesGPT Apache-2.0; self-hosted, optional SaaS UI | MIT core plus a separately licensed `ee/` folder; self-hosted or cloud | Grafana Cloud only | MIT; self-hosted |
| **Needs Kubernetes** | Yes | No | Most checks use Kubernetes data | No |
| **Use of AI** | LLM-driven investigation (HolmesGPT) | LLM correlation and summaries | ML detectors | Deterministic by default; optional local LLM via Ollama that never overrides the deterministic result |
| **Finds deploys automatically** | Yes, from Kubernetes changes | Through integrations | Yes, from Kubernetes changes | No; your CI sends deploy events to `POST /api/events` |

## Robusta and HolmesGPT

[Robusta](https://github.com/robusta-dev/robusta) enriches Prometheus alerts on Kubernetes before
they reach Slack: pod logs, Grafana links, grouping into threads, tracking of Kubernetes resource
changes, and auto-remediation rules. [HolmesGPT](https://github.com/HolmesGPT/holmesgpt), created
by Robusta and now a CNCF project, is an AI agent that investigates alerts and suggests a root
cause.

**Choose Robusta if** you run on Kubernetes and want automatic change tracking, pod-level context,
remediation, or LLM-driven investigation.

**How Ops Signals differs:**

- It doesn't need Kubernetes. It works against plain Prometheus.
- It analyzes the alerting series itself with published detection methods (see
  [`26-analyzer-methodology.md`](26-analyzer-methodology.md)) and states what happened, for example
  "sustained baseline shift ~621 → ~425 ms". No LLM is involved by default.
- It links the alert to past resolved cases, including their root cause and fix, and returns them
  as "seen before" in the alert (see [`08-operational-memory.md`](08-operational-memory.md)).

**Where Robusta is ahead:** it discovers deploys and configuration changes on its own, attaches pod
logs, and can remediate. Ops Signals needs your CI to send deploy events and doesn't remediate.

## Keep

[Keep](https://github.com/keephq/keep) is an alert-management platform. It collects alerts from
many monitoring tools, deduplicates and correlates them, enriches them, and runs YAML workflows
(for example, open a Jira ticket or run a query). See the
[Keep docs](https://docs.keephq.dev/overview/introduction).

**Choose Keep if** your main problem is too many alerts from too many tools.

**How Ops Signals differs:** Ops Signals doesn't route or deduplicate alerts. It takes one alert
and explains the metric behind it. The two can run together: Keep decides which alerts matter, and
Ops Signals explains them.

## Grafana Sift

[Sift](https://grafana.com/docs/grafana-cloud/machine-learning/sift/) is a diagnostic assistant in
Grafana Cloud. It runs a set of
[checks](https://grafana.com/docs/grafana-cloud/machine-learning/sift/analyses/) during an
incident, such as error log patterns (Loki), elevated HTTP errors, Kubernetes crashes, noisy
neighbors, resource contention and recent deployments.

**Choose Sift if** you already use Grafana Cloud with Kubernetes and Loki.

**How Ops Signals differs:** it is open source and self-hosted, doesn't need Grafana Cloud,
Kubernetes or Loki, and keeps resolved cases as memory for future alerts. Ops Signals also has a
[Grafana plugin](grafana-plugin-architecture.md) for self-hosted Grafana.

## Summary

Ops Signals fits teams that run Prometheus, with or without Kubernetes, and want each alert to say
what the metric did, what changed and whether it has happened before, with results that are
explainable and don't depend on an LLM. Its current gaps compared with the tools above are listed
in [Current Limitations](../README.md#11-current-limitations).
