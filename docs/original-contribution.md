# Original Technical Contribution

This document is a factual, engineering-level description of what is original about Ops Signals' design and implementation. It is written as source material for anyone evaluating the project's technical contribution (e.g. for a technical review, an academic/professional reference, or an immigration petition exhibit) - it makes no legal claims and takes no position on "significance" in any legal sense. That determination is for qualified counsel and the relevant adjudicating body.

**Author.** Ops Signals was designed and implemented by Ramprasad Goturkarnam ([@ramprasadgk9](https://github.com/ramprasadgk9)), who is the project's sole architect, primary contributor, and maintainer. This is independently verifiable from the repository's commit history, [LICENSE](../LICENSE) copyright notice, and [README.md](../README.md).

## The problem being addressed

Standard observability and monitoring tooling (metrics dashboards, APM, alerting) answers "what is happening right now" and "where." Per the project's own framing in [`docs/01-vision.md`](01-vision.md), it stops short of answering "what changed," "what does this mean operationally," "have we seen this pattern before," and "how was it resolved last time" - questions that today are typically answered by an engineer's institutional memory rather than by the tooling itself. Ops Signals is built around closing that specific gap: turning raw time-series data into explainable findings, and turning resolved incidents into structured, retrievable operational knowledge, without attempting to replace existing observability platforms or automate remediation (explicit non-goals, `docs/01-vision.md`).

## What is original in the design

### 1. A dual-registry, config-driven analyzer framework

Rather than hardcoding which detection algorithm (PyOD, Prophet, STUMPY, ruptures, z-score, trend regression, etc.) runs against a given metric, the system separates two concerns into independent registries ([`docs/04-analyzer-plugin-framework.md`](04-analyzer-plugin-framework.md)):

- A **pipeline registry** (`config/analyzer_registry.d/*.yml`, `intelligence/analyzer_registry.py`) declaring which analyzer implementations exist and how to construct them.
- A **router registry** (`experiments/analyzer_router/analyzer_registry.yaml`) declaring, per analyzer, which time-series profiles it's eligible for and how it should be scored for a given series.

Adding a new analyzer requires implementing a single `Analyzer.analyze()` method plus a YAML registration entry - no change to a central dispatcher. Registrations merge additively, so a custom analyzer cannot silently override a built-in one. A web UI wizard (Save & Validate → Test → Promote) generates both files for a user adding an analyzer without touching Python code.

### 2. Deterministic, explainable analyzer routing with an explicitly bounded role for AI

A "Universal Router" scores each candidate analyzer's suitability for a given series from extracted features (seasonality, trend strength, variance, a "shift index," etc.) and selects analyzers deterministically against a fixed threshold (`config/analyzers.yaml`, `min_score`). An optional AI advisor (`gemma_advisor.py`) can independently score the same candidates, but by explicit design it never overrides the deterministic router's decision - a disagreement is only surfaced as a flagged divergence for a human to review (`docs/02-architecture.md`). This is a deliberate constraint choice: it keeps every routing decision auditable and reproducible even when an LLM-based component is present, at the cost of not letting the AI act autonomously.

### 3. A declarative, non-LLM rule engine for multi-signal correlation ("Behavior Intelligence")

Beyond single-metric findings, a separate layer evaluates YAML-defined rules that combine facts extracted from multiple analyzer outputs across different metrics - e.g. correlating a memory anomaly with a simultaneous error-rate anomaly into one higher-level "behavior" - using explicit temporal-correlation constraints (`same_analysis_context`, `max_time_gap`, `minimum_overlap`) and a documented confidence calculation (`docs/14-behavior-intelligence.md`). The engine explicitly does not use `eval`, `exec`, LLM-generated rules, or embedded scripts - correlation logic is fully declarative and inspectable, and the UI surfaces the exact facts, conditions, and correlation values that produced each match.

### 4. Separation of system-of-record from retrieval index for operational memory

Resolved cases are persisted in full in Postgres (system of record) and separately embedded into Qdrant as a retrieval index for similarity search over past incidents (`docs/08-operational-memory.md`, `docs/09-design-decisions.md`). The retrieval layer is explicitly documented as advisory only - "it does not determine final root cause" - keeping the transactional record and the similarity-search convenience layer from being conflated into a single, harder-to-reason-about store.

### 5. Analyzer methodology documented and self-audited against its own published foundations

Each built-in analyzer implements a published statistical or ML method (`docs/26-analyzer-methodology.md` cites, e.g., Truong et al. 2020 for change-point detection, Yeh et al. 2016 for Matrix Profile, Taylor & Letham 2018 for Prophet, Zhao et al. 2019 for PyOD's KNN outlier method, Shewhart 1931 for z-score/SPC). Ops Signals does not claim to have invented these detection algorithms. What is original is the layer built on top of them: the routing/suitability-scoring formulas, which the same document explicitly and candidly labels as heuristic and not yet benchmarked against outcome data - and two concrete bugs the author found and documented through self-audit, one of which (a hardcoded feature value in a secondary code path) was fixed in the same pass. Infrastructure to eventually recalibrate the heuristic weights against confirmed/rejected real-world outcomes (`AnalyzerLearningOutcomeEntity`, `AnalyzerDivergenceEntity` in `backend/app/models/entities.py`) exists but is explicitly documented as not yet in use for that purpose.

## Verifiable evidence

- **Commit history and authorship**: the git history of [this repository](https://github.com/ramprasadgk9/operational-intelligence) attributes the design and implementation to the author.
- **License**: [LICENSE](../LICENSE) names the author as copyright holder.
- **Independent adoption**: self-reported by users in [ADOPTERS.md](../ADOPTERS.md) as it accumulates over time.
- **Test and CI evidence** that the described mechanisms are implemented and exercised, not just documented: `.github/workflows/ci.yml`, `.github/workflows/integration.yml`, and the test suites under `tests/`.

## Scope and limitations of this document

This document describes architecture and design rationale as of the date it was written, based on the project's own documentation and source code. It does not claim novelty relative to the entire body of prior art in observability or anomaly-detection tooling beyond what is stated above, and it is not a substitute for independent expert review, citation analysis, or adoption evidence, all of which carry more evidentiary weight than a self-authored technical description.
