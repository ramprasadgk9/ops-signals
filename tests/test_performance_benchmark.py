from __future__ import annotations

from pathlib import Path

from benchmark.performance_benchmark import DATASETS, MAX_SECONDS_PER_ANALYZER, run_all, run_dataset, write_report


def test_run_dataset_completes_without_error_on_the_smallest_dataset() -> None:
    result = run_dataset("24h", DATASETS["24h"])

    assert result.sample_count > 0
    assert result.analyzers
    assert all(timing.error is None for timing in result.analyzers)
    # Deliberately generous - a tripwire for a catastrophic regression, not an SLA. See the
    # module docstring for why per-analyzer timing (not a tight total) is what's checked.
    assert all(timing.elapsed_seconds < MAX_SECONDS_PER_ANALYZER for timing in result.analyzers)


def test_write_report_produces_json_and_markdown(tmp_path: Path) -> None:
    results = [run_dataset("24h", DATASETS["24h"])]

    write_report(results, reports_dir=tmp_path)

    assert (tmp_path / "performance_report.json").exists()
    assert (tmp_path / "performance_report.md").exists()


def test_run_all_warms_up_before_the_first_recorded_dataset() -> None:
    """Regression test for a real, empirically-confirmed issue: stumpy pays a one-time ~6s Numba
    JIT-compile cost on its first call in a process. Without a warm-up pass, that cost lands
    entirely on whichever dataset runs first, making the smallest dataset look far slower than
    the largest one - the opposite of the real scaling behavior this benchmark exists to measure.
    """
    results = run_all({"24h": DATASETS["24h"]})

    stumpy_timing = next(timing for timing in results[0].analyzers if timing.analyzer_id == "stumpy")
    # A warmed-up call on 288 samples is a few milliseconds - nowhere near the ~6s cold-JIT cost.
    assert stumpy_timing.elapsed_seconds < 1.0
