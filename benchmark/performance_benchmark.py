"""Performance/scale benchmark: measures how long normalization and each real analyzer take as
data volume grows (24h -> 7d -> 30d) - the same production code path the other benchmarks
exercise, just timed instead of graded for correctness.

Report-only by default: wall-clock time varies too much across machines/CI runners for a fixed
threshold to be a meaningful pass/fail gate. The one exception is a deliberately generous ceiling
(MAX_SECONDS_PER_ANALYZER) meant only to catch a catastrophic algorithmic regression - e.g.
someone accidentally introducing O(n^2) behavior - not to enforce an SLA.
"""

from __future__ import annotations

import argparse
import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

import pandas as pd

from backend.app.services.timeseries_routing_service import build_csv_routing_config
from benchmark.router_benchmark import DEFAULT_ANALYZER_REGISTRY_DIR, PROJECT_ROOT
from intelligence.analyzer_registry import AnalyzerRegistrationError, instantiate, load_registrations
from intelligence.normalize.normalizer import normalize_timeseries

DATASETS = {
    "24h": PROJECT_ROOT / "benchmark" / "normalized" / "healthy_cpu_24h.csv",
    "7d": PROJECT_ROOT / "benchmark" / "normalized" / "healthy_cpu_7d.csv",
    "30d": PROJECT_ROOT / "benchmark" / "normalized" / "healthy_cpu_30d.csv",
}

MAX_SECONDS_PER_ANALYZER = 30.0


@dataclass(slots=True)
class AnalyzerTiming:
    analyzer_id: str
    elapsed_seconds: float
    signal_count: int
    error: str | None = None


@dataclass(slots=True)
class DatasetPerformance:
    dataset_label: str
    sample_count: int
    normalization_seconds: float
    total_seconds: float
    analyzers: list[AnalyzerTiming] = field(default_factory=list)


def run_dataset(dataset_label: str, csv_path: Path) -> DatasetPerformance:
    dataframe = pd.read_csv(csv_path)
    config = build_csv_routing_config(
        provider="prometheus",
        service="benchmark-performance",
        metric_name="cpu.usage_user",
        interval="5m",
        analyzer_id="all",
        preview=True,
    )

    normalize_start = time.perf_counter()
    normalized = normalize_timeseries(dataframe, config.input)
    normalization_seconds = time.perf_counter() - normalize_start

    timings: list[AnalyzerTiming] = []
    analyzers_start = time.perf_counter()
    for registration in load_registrations(DEFAULT_ANALYZER_REGISTRY_DIR):
        try:
            analyzer = instantiate(registration)
        except AnalyzerRegistrationError as exc:
            timings.append(AnalyzerTiming(analyzer_id=registration.analyzer_id, elapsed_seconds=0.0, signal_count=0, error=str(exc)))
            continue
        start = time.perf_counter()
        try:
            signals = analyzer.analyze(normalized)
            timings.append(AnalyzerTiming(analyzer_id=registration.analyzer_id, elapsed_seconds=time.perf_counter() - start, signal_count=len(signals)))
        except Exception as exc:
            timings.append(AnalyzerTiming(analyzer_id=registration.analyzer_id, elapsed_seconds=time.perf_counter() - start, signal_count=0, error=str(exc)))
    total_seconds = normalization_seconds + (time.perf_counter() - analyzers_start)

    return DatasetPerformance(
        dataset_label=dataset_label,
        sample_count=len(normalized),
        normalization_seconds=normalization_seconds,
        total_seconds=total_seconds,
        analyzers=timings,
    )


def run_all(datasets: dict[str, Path] | None = None) -> list[DatasetPerformance]:
    """Some analyzers pay a one-time process-wide cost on their first call - stumpy in particular
    JIT-compiles its core algorithm via Numba on first use (~6s), regardless of dataset size. Left
    unwarmed, that cost lands entirely on whichever dataset happens to run first and makes the
    smallest dataset look slower than the largest - confirmed empirically, not hypothetical. A
    throwaway warm-up pass on the smallest available dataset absorbs that cost up front, so the
    recorded numbers reflect actual data-scaling behavior instead of cold-start noise."""
    resolved = {label: path for label, path in (datasets or DATASETS).items() if path.exists()}
    if resolved:
        warmup_label = min(resolved, key=lambda label: resolved[label].stat().st_size)
        run_dataset(warmup_label, resolved[warmup_label])
    return [run_dataset(label, path) for label, path in resolved.items()]


def write_report(results: list[DatasetPerformance], *, reports_dir: Path | None = None) -> None:
    reports_dir = reports_dir or (PROJECT_ROOT / "benchmark" / "reports")
    reports_dir.mkdir(parents=True, exist_ok=True)
    json_path = reports_dir / "performance_report.json"
    markdown_path = reports_dir / "performance_report.md"

    json_path.write_text(json.dumps([asdict(result) for result in results], indent=2, sort_keys=True) + "\n", encoding="utf-8")

    lines = [
        "# Performance Benchmark Report",
        "",
        "Timings are only comparable across runs on the same machine - not a cross-machine SLA.",
        "",
    ]
    for result in results:
        lines.append(f"## {result.dataset_label} ({result.sample_count} samples)")
        lines.append("")
        lines.append(f"- Normalization: {result.normalization_seconds:.4f}s")
        lines.append(f"- Total (normalize + all analyzers): {result.total_seconds:.4f}s")
        lines.append("")
        lines.append("| Analyzer | Seconds | Signals | Error |")
        lines.append("| --- | --- | --- | --- |")
        for timing in result.analyzers:
            lines.append(f"| {timing.analyzer_id} | {timing.elapsed_seconds:.4f} | {timing.signal_count} | {timing.error or ''} |")
        lines.append("")
    markdown_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def print_summary(results: list[DatasetPerformance]) -> None:
    print("Dataset | Samples | Normalization (s) | Total (s)")
    print("--- | --- | --- | ---")
    for result in results:
        print(f"{result.dataset_label} | {result.sample_count} | {result.normalization_seconds:.4f} | {result.total_seconds:.4f}")
        for timing in result.analyzers:
            flag = f" ERROR: {timing.error}" if timing.error else ""
            print(f"  - {timing.analyzer_id}: {timing.elapsed_seconds:.4f}s, {timing.signal_count} signal(s){flag}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Measure Ops Signals analyzer performance across dataset sizes")
    parser.add_argument("--dataset", choices=sorted(DATASETS), help="Run only this dataset size (default: all)")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    datasets = {args.dataset: DATASETS[args.dataset]} if args.dataset else None
    results = run_all(datasets)
    print_summary(results)
    write_report(results)


if __name__ == "__main__":
    main()
