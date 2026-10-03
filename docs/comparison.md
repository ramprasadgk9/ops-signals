# How Ops Signals Compares

People evaluating Ops Signals usually ask how it relates to tools they already know. This page
answers that for the ones that come up most: Robusta and HolmesGPT, Keep, and Grafana Sift with
Grafana Assistant.

Ops Signals works alongside these tools, not instead of them. Each one solves a different part of
the "an alert fired, now what?" problem, and some of them can run next to Ops Signals.

> **Last checked: October 2026** (Robusta 0.50.0, HolmesGPT 0.42.0, Keep 0.54.3). These projects
> ship often. Every statement about another tool below links to that tool's own docs. If something
> here is out of date, please open an issue or a PR.

## At a glance

| | Robusta + HolmesGPT | Keep | Grafana Sift / Assistant | Ops Signals |
|---|---|---|---|---|
| **Main job** | Better Prometheus alerts on Kubernetes (Robusta); an AI agent that investigates incidents (HolmesGPT) | Alert hub: dedup, correlation and workflows across many monitoring tools | ML checks (Sift) and AI investigations (Assistant) over Grafana telemetry | Explain what the alerting metric did, what changed, and whether it has been seen before |
| **License / hosting** | Robusta MIT, HolmesGPT Apache-2.0; self-hosted, optional SaaS UI | MIT core plus a separately licensed `ee/` folder; self-hosted or cloud | Grafana Cloud; self-hosted Grafana can connect to Assistant through a Grafana Cloud account | MIT; self-hosted |
| **Needs Kubernetes** | Robusta yes; HolmesGPT no | No | Most Sift checks use Kubernetes data | No |
| **How it reaches a conclusion** | An LLM agent queries your tools (HolmesGPT) | Rules and workflows, plus LLM correlation and summaries | Fixed ML checks (Sift); LLM agent (Assistant) | Statistical detectors on the metric itself; no LLM by default |
| **LLM providers** | OpenAI, Anthropic, Azure, Bedrock, Gemini, and local models through an OpenAI-compatible endpoint (HolmesGPT) | OpenAI, Anthropic, Gemini, Grok, DeepSeek, Ollama, LlamaCPP | Run by Grafana Cloud (Assistant) | Optional: Ollama, any OpenAI-compatible endpoint (vLLM, Azure OpenAI, Bedrock gateways), Anthropic. Never overrides the statistical result |
| **Past incidents** | Not described in their docs | Not described in their docs | Not described in their docs | Resolved cases are recalled as "seen before"; past incidents can be imported from Jira, PagerDuty, CSV or Markdown |
| **Finds deploys automatically** | Yes, from Kubernetes changes | Through integrations | Yes, from Kubernetes changes | No; your CI sends deploy events to `POST /api/events` |
| **Logs and traces** | Yes (pod logs; Loki, Elasticsearch, Tempo and more in HolmesGPT) | Through integrations | Yes (Loki, Tempo) | No; metrics only |

## Robusta and HolmesGPT

[Robusta](https://github.com/robusta-dev/robusta) enriches Prometheus alerts on Kubernetes before
they reach Slack: pod logs, Grafana links, grouping into threads, tracking of Kubernetes resource
changes, and auto-remediation rules. [HolmesGPT](https://github.com/HolmesGPT/holmesgpt), created
by Robusta and now a CNCF project, is an AI agent that investigates incidents and suggests a root
cause. It no longer needs Kubernetes: it runs as a CLI against VMs, bare metal or cloud services,
connects to 50+ data sources, and works with hosted or local models
([HolmesGPT docs](https://holmesgpt.dev/latest/)).

**Choose Robusta if** you run on Kubernetes and want automatic change tracking, pod-level context,
or remediation. **Choose HolmesGPT if** you want an LLM agent that explores logs, traces and
metrics across many tools to propose a root cause.

**How Ops Signals differs:**

- It analyzes the alerting series itself with published detection methods (see
  [`analyzer-methodology.md`](analyzer-methodology.md)) and states what happened, for example
  "sustained baseline shift ~621 → ~425 ms". The same input gives the same answer, and no LLM is
  involved by default. An LLM can be added to write the explanation, but it never changes the
  finding.
- It links the alert to past resolved cases, including their root cause and fix, and returns them
  as "seen before" (see [`operational-memory.md`](operational-memory.md)). Past incidents can be
  imported, so this works from day one (see
  [`importing-incident-history.md`](importing-incident-history.md)).
- Robusta needs Kubernetes; Ops Signals works against plain Prometheus or Prometheus-compatible
  backends (Thanos, Mimir, VictoriaMetrics).

**Where they are ahead:** Robusta discovers deploys and configuration changes on its own, attaches
pod logs, and can remediate. HolmesGPT reads logs and traces and covers far more data sources. Ops
Signals needs your CI to send deploy events, reads metrics only, and doesn't remediate. It can show
which pods a change came from and which new pods a deploy started, but only from metrics and only
when the per-pod drill-down is turned on (see [`finding-drilldown.md`](finding-drilldown.md)).

## Keep

[Keep](https://github.com/keephq/keep) is an alert-management platform. It collects alerts from
many monitoring tools, deduplicates and correlates them, enriches them, and runs YAML workflows
(for example, open a Jira ticket or run a query). Its AI correlation and summaries can use hosted
or local models. See the [Keep docs](https://docs.keephq.dev/overview/introduction).

**Choose Keep if** your main problem is too many alerts from too many tools.

**How Ops Signals differs:** Ops Signals doesn't route or deduplicate alerts. It takes one alert
and explains the metric behind it. The two can run together: Keep decides which alerts matter, and
Ops Signals explains them.

## Grafana Sift and Grafana Assistant

[Sift](https://grafana.com/docs/grafana-cloud/machine-learning/sift/) is a diagnostic assistant in
Grafana Cloud. It runs a set of
[checks](https://grafana.com/docs/grafana-cloud/machine-learning/sift/analyses/) during an
incident: error log patterns (Loki), elevated HTTP errors, Kubernetes crashes, noisy neighbors,
resource contention, recent deployments, and custom PromQL or LogQL queries.

[Grafana Assistant](https://grafana.com/products/cloud/ai-assistant/) adds LLM-driven
investigations that correlate signals across Grafana data. Self-hosted Grafana (OSS or Enterprise)
can use it by connecting to a Grafana Cloud account. A free tier covers 3 active users.

**Choose Sift or Assistant if** you already use Grafana Cloud, or are happy to connect your Grafana
to it, especially with Kubernetes and Loki.

**How Ops Signals differs:** it is open source and runs entirely on your network, with no Grafana
Cloud account. It doesn't need Kubernetes or Loki, and it keeps resolved cases as memory for future
alerts. Ops Signals also has a [Grafana plugin](grafana-plugin-architecture.md) for self-hosted
Grafana.

## Summary

Ops Signals fits teams that run Prometheus or a Prometheus-compatible backend, with or without
Kubernetes, and want each alert to say what the metric did, what changed and whether it has
happened before. Its results are explainable, repeatable and don't depend on an LLM. When you do
want AI-written explanations, you can use your own model, local or hosted.

Its gaps compared with the tools above: no automatic deploy discovery, no logs or traces, no
remediation, and no alert routing. Its current limitations are listed in
[Current Limitations](../README.md#current-limitations).
