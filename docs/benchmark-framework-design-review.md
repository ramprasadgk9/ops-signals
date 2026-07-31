# Ops Signals Benchmark Framework Design Review

## 1. Executive Summary

Ops Signals has enough implementation maturity to support a credible benchmark framework, but the benchmark framework itself should be treated as a first-class product surface rather than another experiment folder.

The current repository already has useful benchmark inputs and outputs: normalized time-series data, analyzer routing snapshots, operational signals, findings, cases, behavior findings, memory indexing status, assistant evidence groups, Grafana plugin surfaces, MCP tools, and a small experiment framework. Those pieces are valuable, but they are not yet a benchmark architecture because they do not define immutable datasets, ground truth, expected outcomes, scoring contracts, run metadata, historical comparisons, or regression gates.

Recommended benchmark readiness: **4/10**.

That score means the core product has benchmarkable behavior, but the repo should not publish benchmark claims yet. The next step should be design-first benchmark scaffolding: manifests, dataset catalog, expected outcome schema, evaluator contracts, report format, reproducibility rules, and CI tiers. Production benchmark implementation should follow only after those contracts are reviewed.

## 2. Current Strengths

| Area | Current strength | Benchmark relevance |
| --- | --- | --- |
| Analyzer pipeline | `intelligence/pipeline.py` runs normalization, routing, analyzers, signal scoring, finding aggregation, behavior evaluation, and question answers. | Provides a single end-to-end execution path to evaluate. |
| Analyzer routing | `experiments/analyzer_router/` calculates deterministic profile features, eligibility, suitability scores, and analyzer recommendations. | Suitable for top-k recommendation benchmarks and regression testing. |
| Analyzer configuration | `config/analyzers.yaml` centralizes enabled analyzers and key parameters. | Benchmark runs can capture analyzer configuration hashes and compare behavior across versions. |
| Analysis run storage | `AnalysisRunEntity` stores source metadata, sample count, router version, feature extractor version, analyzer registry version, profile JSON, routing decisions, executed analyzers, and generated findings. | Strong foundation for reproducible run metadata. |
| Signals and findings | `SignalEntity` and `FindingEntity` persist analyzer outputs and aggregated operational findings. | Allows signal-level and finding-level scoring. |
| Cases and outcomes | `OperationalCaseEntity` and `AnalyzerLearningOutcomeEntity` capture investigation status, RCA, resolution, and learning outcomes. | Useful for workflow regression and later outcome-backed evaluation. |
| Behavior intelligence | Behavior definitions, condition evaluation, fact extraction, and behavior finding persistence exist. | Can be benchmarked against multi-signal scenario expectations. |
| Operational memory | Case indexing, deterministic point IDs, memory status fields, Qdrant vector store, and similarity service exist. | Can support retrieval benchmarks such as recall@k and MRR. |
| Assistant | Assistant routes questions across cases, findings, behaviors, memory, docs, and analyzer knowledge, and returns evidence groups. | Can be evaluated on grounding, retrieval quality, and route selection. |
| Direct Prometheus analysis | Standalone UI and backend can query Prometheus, preview data, and run analysis. | Useful for live smoke tests, but not a replacement for versioned benchmark datasets. |
| Grafana plugin | Plugin has standalone packaging and local Prometheus setup docs. | Should be regression tested separately from benchmark scoring. |
| MCP | Read/write tool schemas and tool execution exist. | Can be contract-tested without becoming part of analyzer accuracy benchmarks. |
| Existing docs | `docs/11-datasets-and-evaluation.md` already says the repo has samples and tests but no public benchmark claims. | Good public framing to extend. |

## 3. Architectural Risks

1. **Experiments are not benchmarks.** The existing `experiments/` folder contains useful explorations and result files, but experiments can be mutable, ad hoc, and local. Benchmarks need stable manifests, stable datasets, stable ground truth, and repeatable scoring.

2. **No first-class ground truth model exists.** The repo can generate signals, findings, behavior findings, and cases, but it does not yet define expected outcomes that are independent from the code under test.

3. **Analyzer outputs are partly semantic, not exact.** Signals and findings include summaries, evidence, confidence, severity, categories, and windows. Exact text or exact generated IDs should not become benchmark targets.

4. **Router labels are not benchmark labels.** The analyzer router calculates suitability scores from rules. That is useful, but a benchmark still needs expected analyzer rankings or expected analyzer families for each scenario.

5. **Memory retrieval can be nondeterministic across embedding providers.** Qdrant state, embedding model version, payload filters, and score thresholds can change results. Benchmarks must capture model, collection, content version, and vector-store state.

6. **Assistant evaluation can become misleading if it relies on prose matching.** The assistant composes grounded answers from retrieved evidence. The benchmark should score route selection, evidence inclusion, citation/source quality, and refusal/limitation behavior instead of exact natural-language text.

7. **Behavior intelligence needs scenario-level labels.** Behavior rules often depend on multiple signals and matched facts. A single CSV label is not enough if the scenario expects a composite behavior.

8. **Live Prometheus is not reproducible.** Direct Prometheus analysis is important operationally, but benchmark datasets should be versioned and immutable. Live Prometheus should be limited to smoke tests unless responses are captured and versioned.

9. **Benchmark history should not require database schema changes at first.** The repo already has production schema complexity. Benchmark history can start as JSON and Markdown artifacts before a persistent benchmark database is justified.

10. **CI can become too slow or flaky.** Full analyzer, memory, assistant, Grafana, and MCP evaluation should not all run on every pull request.

## 4. Missing Components

The benchmark framework should introduce these first-class concepts.

| Concept | Needed? | Purpose |
| --- | --- | --- |
| Benchmark Dataset | Yes | Immutable input data unit with metadata, hashes, ownership, scenario type, and allowed execution modes. |
| Dataset Catalog | Yes | Repository-wide index of all benchmark datasets and their tags. |
| Golden Dataset | Yes | Curated subset with stable expected outcomes used for regression gates. |
| Ground Truth | Yes | Human-reviewed labels independent from generated analyzer output. |
| Expected Outcome | Yes | Machine-readable expected signals, findings, behavior findings, routing decisions, memory results, or assistant evidence. |
| Scenario | Yes | Human-readable benchmark story, such as baseline shift, noisy normal, CPU throttling, recovery, or recurring pattern. |
| Evaluation Metrics | Yes | Formal metric definitions for precision, recall, F1, top-k ranking, temporal overlap, severity accuracy, retrieval quality, and assistant grounding. |
| Benchmark Manifest | Yes | Defines which datasets, components, config, and metrics are included in a run. |
| Benchmark Run Metadata | Yes | Captures git SHA, config hash, dependency versions, dataset hashes, runtime flags, random seeds, and environment. |
| Benchmark Report | Yes | Summarizes pass/fail, scores, regressions, warnings, and links to artifacts. |
| Score Aggregation | Yes | Combines scenario scores into component-level and suite-level summaries. |
| Historical Comparison | Yes | Compares a run with a baseline report. |
| Regression Detection | Yes | Applies explicit thresholds for score drops, new false positives, runtime regressions, and output contract changes. |
| Versioned Benchmarks | Yes | Allows benchmark datasets and expectations to evolve through reviewed versions. |

## 5. Recommended Benchmark Architecture

### Core Model

The benchmark framework should have three layers:

1. **Input layer**
   - Dataset catalog
   - Dataset manifests
   - Raw time-series files
   - Optional captured Prometheus responses
   - Scenario metadata
   - Ground truth files

2. **Execution layer**
   - Pipeline runner
   - Analyzer router runner
   - Behavior intelligence runner
   - Memory indexing and retrieval runner
   - Assistant route/evidence runner
   - API and UI smoke runners

3. **Evaluation layer**
   - Component-specific evaluators
   - Score aggregation
   - Regression comparison
   - JSON and Markdown reports
   - CI exit policy

### Benchmark Dataset

Each benchmark dataset should include:

- stable `dataset_id`
- semantic version
- scenario tags
- source type
- license and provenance
- input files
- expected schema version
- hash for every input file
- owner or reviewer
- allowed suites, such as `smoke`, `nightly`, or `release`
- runtime requirements, such as optional Prophet dependency or Qdrant availability

### Ground Truth and Expected Outcomes

Ground truth should be independent from the implementation being evaluated. It should be reviewed by a human and stored separately from generated reports.

Expected outcomes should support:

- expected analyzer families
- expected route rankings
- expected signal types
- expected time windows with tolerance
- expected finding category and severity
- expected behavior definition IDs
- expected case workflow state when applicable
- expected memory retrieval case IDs
- expected assistant routes and required evidence sources

Expected outcomes should not require exact generated IDs, exact timestamps without tolerance, exact free-form summaries, or exact LLM wording.

### Scoring

Use component-specific scoring instead of a single universal score.

| Component | Recommended metrics |
| --- | --- |
| Normalization | row count accuracy, timestamp parse correctness, duplicate handling, missingness handling, provider label preservation |
| Analyzer routing | top-1 accuracy, top-k recall, MRR, NDCG, expected rejection accuracy, suitability score tolerance |
| Analyzer signals | precision, recall, F1, false positive rate, false negative rate, temporal intersection-over-union, severity accuracy |
| Findings | finding match precision/recall, category accuracy, health status accuracy, evidence coverage, priority bucket accuracy |
| Behavior intelligence | behavior ID precision/recall, matched-condition accuracy, contributing-signal coverage, severity/category accuracy |
| Cases | create/update contract correctness, lifecycle transition correctness, memory status transition correctness |
| Operational memory | indexing status accuracy, recall@k, MRR, same-service filter correctness, stale/error status behavior |
| Assistant | route accuracy, evidence-source recall, citation/reference validity, grounded answer checks, limitation disclosure |
| Grafana plugin | build success, data-source contract smoke, visual smoke snapshots, no plugin JSON regression |
| MCP | schema contract validation, read/write mode behavior, tool response shape, no unintended write in read mode |
| Performance | runtime per dataset, memory usage budget, timeout behavior |

## 6. Recommended Repository Structure

Recommended future structure:

```text
benchmarks/
  README.md
  catalog.yaml
  manifests/
    smoke.yaml
    analyzer-regression.yaml
    behavior-regression.yaml
    memory-retrieval.yaml
    assistant-grounding.yaml
    release.yaml
  datasets/
    synthetic/
      cpu_baseline_shift_v1/
        dataset.yaml
        timeseries.csv
        ground_truth.yaml
      cpu_no_issue_v1/
        dataset.yaml
        timeseries.csv
        ground_truth.yaml
    prometheus_captures/
      checkout_cpu_throttling_v1/
        dataset.yaml
        prometheus_response.json
        ground_truth.yaml
  schemas/
    benchmark_manifest.schema.json
    dataset.schema.json
    ground_truth.schema.json
    benchmark_report.schema.json
  reports/
    .gitignore
  baselines/
    release-main.json
```

Recommended future code placement, once implementation is approved:

```text
backend/app/benchmarks/
  __init__.py
  schemas.py
  catalog.py
  runner.py
  evaluators/
    normalization.py
    routing.py
    signals.py
    findings.py
    behavior.py
    memory.py
    assistant.py
  reporting.py
  regression.py
```

The first implementation should prefer file-based manifests and reports. Avoid database schema changes until benchmark history, filtering, and UI reporting clearly justify persistent storage.

## 7. Validation Strategy

### Unit-Level Validation

- Validate benchmark manifests against JSON Schema or Pydantic models.
- Validate dataset file hashes.
- Validate ground truth files separately from benchmark execution.
- Validate score aggregation with small hand-authored examples.
- Validate temporal matching behavior with edge cases.

### Component-Level Validation

- Normalization should be tested against malformed timestamps, missing values, duplicate timestamps, irregular sampling, provider tags, and empty files.
- Analyzer router should be tested against known profiles: normal, baseline shift, trend, spike, seasonal, sparse, constant, and mixed behavior.
- Signal evaluators should test window tolerance and type matching.
- Finding evaluators should test severity/category mapping and evidence coverage.
- Behavior evaluators should test single-behavior, multi-behavior, no-match, and partial-input scenarios.
- Memory evaluators should test indexed, stale, missing collection, no-match, and same-service filters.
- Assistant evaluators should test intent routes, required evidence sources, no-evidence answers, and hallucination-safe limitations.

### End-to-End Validation

End-to-end benchmark runs should produce:

- normalized data summary
- router decisions
- executed analyzer list
- signals
- findings
- behavior findings
- optional case outputs
- optional memory retrieval outputs
- optional assistant evidence outputs
- score report
- run metadata

The benchmark report should fail if any required artifact is missing.

## 8. Reproducibility Strategy

Every benchmark run should capture:

- git commit SHA
- branch name
- dirty worktree flag
- Python version
- Node version when frontend or Grafana checks are included
- package lock hash
- analyzer config hash
- analyzer registry version
- feature extractor version
- router version
- behavior definitions hash
- benchmark manifest hash
- dataset file hashes
- ground truth file hashes
- runtime mode
- selected analyzers
- random seed
- timezone
- dependency flags such as Prophet/STUMPY/Ruptures availability
- embedding provider and model version
- Qdrant collection name and content version when memory is included

Use deterministic matching wherever possible:

- fixed random seeds
- frozen input timestamps
- fixed analyzer config
- explicit floating-point tolerances
- semantic output matching instead of generated ID matching
- time-window overlap instead of exact timestamp equality
- retrieval rank metrics instead of exact similarity scores

## 9. CI/CD Integration

### Pull Request Tier

Run a small deterministic smoke suite:

- manifest validation
- dataset hash validation
- one no-issue dataset
- one baseline-shift dataset
- one routing-only dataset
- one behavior no-match/match pair
- no Qdrant requirement
- no live Prometheus requirement
- no LLM requirement

Target runtime: under 3 minutes.

### Nightly Tier

Run broader suites:

- analyzer regression
- behavior regression
- memory retrieval with Qdrant
- assistant grounding with deterministic/noop AI mode
- API smoke checks
- performance trend report

Target runtime: under 20 minutes.

### Release Tier

Run full validation before tagging:

- all benchmark suites
- frontend production build
- Grafana plugin build
- MCP read/write tests
- direct Prometheus smoke when local stack is available
- report generation
- historical comparison against release baseline

The release tier should publish JSON and Markdown benchmark reports as artifacts.

### Regression Policy

Suggested initial gates:

- no new crashes
- no schema validation failures
- no benchmark dataset hash drift
- no new false positives on golden no-issue datasets
- no more than 5 percent drop in component F1 without approved baseline update
- no required assistant evidence source missing
- no memory retrieval recall@5 regression on golden retrieval cases
- no MCP read-mode write behavior
- no Grafana build regression

## 10. Documentation Recommendations

Add these docs after design approval:

1. `benchmarks/README.md`
   - benchmark purpose
   - how to run smoke/nightly/release suites
   - how to read reports
   - how to update baselines

2. `docs/benchmark-methodology.md`
   - dataset categories
   - ground truth policy
   - scoring definitions
   - limitations
   - what is and is not claimed publicly

3. `docs/benchmark-dataset-authoring.md`
   - dataset manifest fields
   - ground truth examples
   - review checklist
   - license/provenance guidance

4. `docs/benchmark-ci.md`
   - CI tiers
   - failure interpretation
   - regression threshold policy

5. Update `docs/11-datasets-and-evaluation.md`
   - link to benchmark methodology
   - keep the current conservative stance until real results exist

6. Update `docs/release-review.md`
   - add benchmark status only after the framework exists and produces reports

Public docs should avoid claims such as "best analyzer accuracy" or "production-grade benchmark score" until the benchmark datasets, ground truth, and reports are reviewed and reproducible.

## 11. Phased Implementation Roadmap

### Phase 0: Design Freeze

- Review this design with the intended public release goals.
- Decide benchmark scope for first release.
- Decide which datasets are allowed to be public.
- Decide scoring metrics per component.
- Decide baseline update policy.

### Phase 1: Benchmark Contracts

- Add schemas for catalog, dataset, ground truth, manifest, and report.
- Add one smoke manifest.
- Add two to four tiny synthetic datasets.
- Add validation-only tests for schema and hash checks.
- Do not run the full Ops Signals pipeline yet.

### Phase 2: Analyzer and Finding Benchmarks

- Add runner for normalization, routing, analyzers, signals, and findings.
- Add temporal matching and signal/finding scoring.
- Add Markdown and JSON report output.
- Add PR smoke CI.

### Phase 3: Behavior Intelligence Benchmarks

- Add multi-signal behavior scenarios.
- Score behavior definitions, matched conditions, confidence ranges, and evidence coverage.
- Add false-positive scenarios for normal behavior.

### Phase 4: Memory and Assistant Benchmarks

- Add memory retrieval fixtures with expected case IDs.
- Score recall@k and MRR.
- Add assistant route/evidence benchmarks.
- Keep LLM text generation out of hard pass/fail unless a deterministic provider is used.

### Phase 5: Release Benchmarking

- Add historical comparison.
- Add regression thresholds.
- Add release artifacts.
- Add public methodology docs.

### Phase 6: UI and Plugin Regression Coverage

- Add standalone UI route smoke tests for benchmark-relevant pages.
- Add Grafana plugin build and visual smoke checks.
- Keep visual tests separate from analyzer accuracy scores.

## 12. Priority Matrix

### P0

| Item | Reason |
| --- | --- |
| Benchmark manifest schema | Prevents ad hoc execution from becoming the benchmark contract. |
| Dataset catalog schema | Makes datasets discoverable, versioned, and reviewable. |
| Ground truth schema | Separates expected outcomes from generated outputs. |
| Report schema | Makes CI and release artifacts stable. |
| Reproducibility metadata | Required before comparing runs. |
| Synthetic smoke datasets | Enables deterministic PR checks. |
| Temporal matching rules | Required for time-series scoring. |
| No-issue golden dataset | Prevents false-positive regressions. |

### P1

| Item | Reason |
| --- | --- |
| Analyzer routing evaluator | Validates analyzer selection and recommendation quality. |
| Signal and finding evaluator | Validates the main operational intelligence output. |
| Behavior intelligence evaluator | Validates composite behavior rules. |
| Markdown and JSON reporting | Makes results understandable and machine-readable. |
| CI smoke suite | Gives fast regression protection. |
| Baseline comparison | Enables controlled score changes. |
| Dataset authoring docs | Helps external contributors add scenarios safely. |

### P2

| Item | Reason |
| --- | --- |
| Memory retrieval benchmark | Requires controlled vector-store setup and expected case IDs. |
| Assistant grounding benchmark | Requires careful non-prose scoring. |
| Grafana visual smoke benchmark | Useful, but not core analyzer correctness. |
| Direct Prometheus captured-response benchmark | Useful after response fixtures are versioned. |
| Full performance benchmark | Needs stable hardware or normalized CI environment. |
| Benchmark dashboard | Nice after reports are stable. |
| Persistent benchmark history in DB | Should wait until file artifacts are not enough. |

## 13. Things That Should NOT Be Implemented

1. Do not implement benchmark code before schemas, dataset conventions, and scoring contracts are agreed.

2. Do not generate ground truth from the same analyzers being benchmarked.

3. Do not use live Prometheus data as a release benchmark without captured, versioned fixtures.

4. Do not score assistant quality by exact prose matching.

5. Do not let an LLM judge be the only source of benchmark truth.

6. Do not require Qdrant or an embedding model for the PR smoke suite.

7. Do not mix Grafana plugin visual regression scores with analyzer accuracy scores.

8. Do not introduce database schema changes for benchmark history in the first implementation.

9. Do not publish public benchmark claims until reports are reproducible from a clean checkout.

10. Do not compare optional dependency behavior unless the dependency set is captured in run metadata.

11. Do not hardcode local workstation paths in benchmark configs or reports.

12. Do not require exact generated run IDs, case IDs, or UUIDs in expected outcomes.

13. Do not silently update golden baselines during CI.

14. Do not treat operational learning outcomes as benchmark ground truth without explicit review, because they are production evidence records, not curated labels.

15. Do not make benchmark datasets mutable after release. Create a new dataset version instead.

## Final Recommendation

Create the benchmark framework as a file-first, schema-driven layer under `benchmarks/`, backed by small deterministic golden datasets and explicit ground truth. Keep analyzer, behavior, memory, assistant, Grafana, and MCP evaluations separate at first. This keeps the benchmark credible for open-source users while protecting the product from accidental benchmark-shaped technical debt.
