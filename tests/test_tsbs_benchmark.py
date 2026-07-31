from __future__ import annotations

from pathlib import Path

import pandas as pd

from benchmark.scripts.tsbs_benchmark import (
    BENCHMARK_ROOT,
    SOURCE_FILES,
    BenchmarkError,
    evaluate_against_ground_truth,
    generate_cpu_baseline_shift_scenario,
    parse_tsbs_source,
    validate_normalized_dataframe,
    write_normalized_csv,
)
from intelligence.config import load_config
from intelligence.pipeline import SignalPipeline


class InMemoryStore:
    def __init__(self) -> None:
        self.normalized_points = None
        self.saved_findings = []

    def create_analysis_run(self, payload) -> None:
        self.analysis_run = payload

    def save_normalized_points(self, dataframe, analysis_run_id=None) -> None:
        self.normalized_points = dataframe.copy()

    def update_analysis_run_learning_snapshot(self, analysis_run_id, snapshot) -> None:
        self.learning_snapshot = snapshot

    def save_capabilities(self, capabilities) -> None:
        return None

    def save_questions(self, questions) -> None:
        return None

    def save_signals(self, signals, embeddings=None) -> None:
        self.saved_signals = list(signals)

    def save_findings(self, findings) -> None:
        self.saved_findings = list(findings)

    def save_question_answers(self, answers) -> None:
        self.answers = list(answers)


class StubEmbedder:
    def embed(self, text: str):
        return [0.0, 0.0, 0.0]


def test_parse_tsbs_source_returns_expected_shape() -> None:
    dataframe = parse_tsbs_source(SOURCE_FILES["24h"])

    assert not dataframe.empty
    assert list(dataframe.columns) == [
        "timestamp",
        "value",
        "metric_name",
        "hostname",
        "host",
        "service",
        "env",
        "source",
        "unit",
        "metric_type",
        "tags_json",
    ]
    assert dataframe["hostname"].nunique() == 1
    assert set(dataframe["metric_name"].unique()) == {"cpu.usage_user"}


def test_validate_normalized_dataframe_rejects_duplicate_timestamps() -> None:
    dataframe = parse_tsbs_source(SOURCE_FILES["24h"]).head(3).copy()
    dataframe.loc[1, "timestamp"] = dataframe.loc[0, "timestamp"]

    try:
        validate_normalized_dataframe(dataframe)
    except BenchmarkError as exc:
        assert "Duplicate timestamps" in str(exc)
    else:
        raise AssertionError("Expected duplicate timestamp validation to fail")


def test_write_normalized_csv_and_summary(tmp_path: Path) -> None:
    output_path = tmp_path / "healthy_cpu_24h.csv"
    summary = write_normalized_csv("24h", str(output_path))
    normalized = pd.read_csv(output_path)

    assert summary.interval == "5m"
    assert summary.hostname_count == 1
    assert summary.metric_count == 1
    assert list(normalized.columns[:4]) == ["timestamp", "value", "metric", "hostname"]


def test_generated_scenario_runs_through_pipeline() -> None:
    generate_cpu_baseline_shift_scenario()
    dataset_path = BENCHMARK_ROOT / "scenarios" / "cpu_baseline_shift_v1" / "dataset.csv"
    dataframe = pd.read_csv(dataset_path).rename(columns={"metric": "metric_name"})
    dataframe["timestamp"] = pd.to_datetime(dataframe["timestamp"], utc=True)

    config = load_config(Path(__file__).resolve().parents[1] / "config.yaml")
    store = InMemoryStore()
    pipeline = SignalPipeline(config=config, store=store, embedder=StubEmbedder())

    result = pipeline.run_normalized(dataframe, run_metadata={"file_name": str(dataset_path)})
    evaluation = evaluate_against_ground_truth(
        benchmark_id="ops-signals-tsbs-v1",
        scenario_id="cpu_baseline_shift_v1",
        scenario_dir=dataset_path.parent,
        pipeline_result=result,
    )

    assert any(signal.signal_type == "baseline_shift" for signal in result.signals)
    assert evaluation.passed is True
