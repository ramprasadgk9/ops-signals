from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from intelligence.config import load_config
from intelligence.pipeline import SignalPipeline
from intelligence.signals.schema import OperationalSignal


class InMemoryStore:
    def __init__(self) -> None:
        self.normalized_points = None
        self.saved_signals = []
        self.saved_findings = []
        self.initialized = False
        self.learning_snapshot = None
        self.learning_snapshots = []
        self.analysis_run = None
        self.created_analysis_runs = []

    def init_db(self) -> None:
        self.initialized = True

    def init_db_from_sql(self, sql_path: Path) -> None:
        self.initialized = True

    def save_normalized_points(self, dataframe, analysis_run_id=None) -> None:
        self.normalized_points = dataframe.copy()

    def save_signals(self, signals, embeddings=None) -> None:
        self.saved_signals = [(signals, embeddings)]

    def save_findings(self, findings) -> None:
        self.saved_findings = list(findings)

    def fetch_findings(self):
        return None

    def create_analysis_run(self, payload) -> None:
        self.created_analysis_runs.append(dict(payload))
        self.analysis_run = dict(payload)

    def update_analysis_run_learning_snapshot(self, analysis_run_id, snapshot) -> None:
        self.learning_snapshots.append((analysis_run_id, dict(snapshot)))
        if self.analysis_run and self.analysis_run.get("id") == analysis_run_id:
            self.analysis_run.update(snapshot)
        self.learning_snapshot = (analysis_run_id, snapshot)

    def save_capabilities(self, capabilities) -> None:
        self.capabilities = capabilities

    def save_questions(self, questions) -> None:
        self.questions = questions

    def save_question_answers(self, answers) -> None:
        self.answers = answers


class StubEmbedder:
    def embed(self, text: str):
        return [0.1, 0.2, 0.3]


def test_csv_pipeline_generates_operational_signals() -> None:
    project_root = Path(__file__).resolve().parents[1]
    config = load_config(project_root / "config.yaml")
    store = InMemoryStore()
    pipeline = SignalPipeline(config=config, store=store, embedder=StubEmbedder())

    result = pipeline.run()

    assert store.normalized_points is not None
    assert len(result.normalized_points) == 24
    assert len(result.signals) >= 2
    signal_types = {signal.signal_type for signal in result.signals}
    assert "baseline_shift" in signal_types
    assert "trend" in signal_types
    baseline_signal = next(signal for signal in result.signals if signal.signal_type == "baseline_shift")
    assert baseline_signal.analyzer_id == "baseline_shift"
    assert baseline_signal.evidence["library"] == "ruptures"
    assert baseline_signal.evidence["algorithm"] == "binseg"
    assert baseline_signal.evidence["model"] == "l2"
    assert baseline_signal.evidence["jump"] == 5
    assert baseline_signal.evidence["n_bkps"] == 1
    assert baseline_signal.evidence["change_point_index"] > 0
    trend_signal = next(signal for signal in result.signals if signal.signal_type == "trend")
    assert trend_signal.evidence["library"] == "statsmodels"
    assert trend_signal.evidence["model"] == "OLS"
    assert "p_value" in trend_signal.evidence
    assert "r_squared" in trend_signal.evidence
    assert len(result.findings) == 1
    assert result.report.answers["what_changed_yesterday"]
    assert store.created_analysis_runs[0]["status"] == "running"
    assert any(snapshot == {"status": "completed"} for _, snapshot in store.learning_snapshots)
    assert store.analysis_run["created_at"]
    assert store.analysis_run["status"] == "completed"


def test_findings_do_not_claim_previous_day_without_comparison_data() -> None:
    project_root = Path(__file__).resolve().parents[1]
    config = load_config(project_root / "config.yaml")
    store = InMemoryStore()
    pipeline = SignalPipeline(config=config, store=store, embedder=StubEmbedder())

    result = pipeline.run()

    finding = result.findings[0]
    assert "yesterday" not in finding.title.lower()
    assert "previous day" not in finding.summary.lower()
    assert finding.comparison_json["comparison_type"] == "selected_window_split"


def test_pipeline_records_recommended_analyzers_that_are_skipped() -> None:
    project_root = Path(__file__).resolve().parents[1]
    config = load_config(project_root / "config.yaml")
    store = InMemoryStore()
    pipeline = SignalPipeline(config=config, store=store, embedder=StubEmbedder())

    snapshots = pipeline._executed_analyzer_snapshots(
        [
            {"analyzer_id": "trend_regression", "display_name": "Trend Regression", "recommendation": "RECOMMENDED"},
            {"analyzer_id": "kats", "display_name": "Kats", "recommendation": "RECOMMENDED"},
            {"analyzer_id": "pyod_outlier", "display_name": "PyOD Outlier Detection", "recommendation": "RECOMMENDED"},
            {"analyzer_id": "adtk", "display_name": "ADTK", "recommendation": "REJECTED"},
        ],
        ["trend", "baseline_shift", "pyod_outlier"],
    )

    by_id = {item["router_analyzer_id"]: item for item in snapshots}
    assert by_id["trend_regression"]["pipeline_analyzer_ids"] == ["trend"]
    assert by_id["trend_regression"]["execution_status"] == "completed"
    assert by_id["trend_regression"]["executed_pipeline_analyzer_ids"] == ["trend"]
    assert by_id["kats"]["selected"] is True
    assert by_id["kats"]["pipeline_analyzer_ids"] == ["kats"]
    assert by_id["kats"]["execution_status"] == "skipped"
    assert by_id["kats"]["executed_pipeline_analyzer_ids"] == []
    assert "No enabled pipeline analyzer" in by_id["kats"]["execution_reason"]
    assert by_id["pyod_outlier"]["execution_status"] == "completed"
    assert by_id["pyod_outlier"]["executed_pipeline_analyzer_ids"] == ["pyod_outlier"]
    assert by_id["adtk"]["selected"] is False


def test_recommended_threshold_selects_top_recommended_executable_analyzers() -> None:
    project_root = Path(__file__).resolve().parents[1]
    config = load_config(project_root / "config.yaml")
    config.analysis.selection_mode = "recommended_threshold"
    config.analysis.recommendation_execution.min_score = 0.8
    config.analysis.recommendation_execution.max_analyzers = 3
    config.analysis.recommendation_execution.include_optional = False
    pipeline = SignalPipeline(config=config, store=InMemoryStore(), embedder=StubEmbedder())

    allowed = pipeline._allowed_pipeline_analyzers(
        [
            {"analyzer_id": "ruptures", "display_name": "Ruptures", "recommendation": "RECOMMENDED", "final_score": 1.0},
            {"analyzer_id": "kats", "display_name": "Kats", "recommendation": "RECOMMENDED", "final_score": 0.88},
            {
                "analyzer_id": "trend_regression",
                "display_name": "Trend Regression",
                "recommendation": "RECOMMENDED",
                "final_score": 0.86,
            },
            {"analyzer_id": "stumpy", "display_name": "STUMPY", "recommendation": "RECOMMENDED", "final_score": 0.79},
            {"analyzer_id": "river", "display_name": "River", "recommendation": "OPTIONAL", "final_score": 0.95},
        ]
    )

    assert allowed == {"ruptures", "kats", "trend"}


def test_pipeline_continues_when_one_analyzer_fails(monkeypatch) -> None:
    project_root = Path(__file__).resolve().parents[1]
    config = load_config(project_root / "config.yaml")
    config.output.save_normalized_data = False
    config.output.save_signals = False
    config.output.save_question_answers = False
    config.output.save_embeddings = False
    config.capabilities.auto_register = False
    config.questions.auto_generate_from_capabilities = False
    store = InMemoryStore()
    pipeline = SignalPipeline(config=config, store=store, embedder=StubEmbedder())

    class FailingAnalyzer:
        analyzer_id = "broken_analyzer"

        def analyze(self, dataframe):
            raise RuntimeError("intentional failure")

    class HealthyAnalyzer:
        analyzer_id = "healthy_analyzer"

        def analyze(self, dataframe):
            return [
                OperationalSignal(
                    signal_type="trend",
                    analyzer_id=self.analyzer_id,
                    metric_name="cpu_usage",
                    service="checkout",
                    env="prod",
                    severity="medium",
                    confidence=0.8,
                    start_time=dataframe["timestamp"].min().to_pydatetime(),
                    end_time=dataframe["timestamp"].max().to_pydatetime(),
                    summary="cpu_usage has a healthy analyzer signal.",
                    evidence={"test": True},
                )
            ]

    monkeypatch.setattr(
        pipeline,
        "_route_analyzers",
        lambda normalized: (
            [
                {"analyzer_id": "broken_analyzer", "display_name": "Broken", "recommendation": "RECOMMENDED"},
                {"analyzer_id": "healthy_analyzer", "display_name": "Healthy", "recommendation": "RECOMMENDED"},
            ],
            {"detected_profiles": ["trend"]},
            "test",
        ),
    )
    monkeypatch.setattr(pipeline, "_build_analyzers", lambda routing: [FailingAnalyzer(), HealthyAnalyzer()])

    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    dataframe = pd.DataFrame(
        {
            "timestamp": [start + timedelta(minutes=index) for index in range(40)],
            "metric_name": ["cpu_usage"] * 40,
            "value": [50.0 + index for index in range(40)],
            "service": ["checkout"] * 40,
            "env": ["prod"] * 40,
        }
    )

    result = pipeline.run_normalized(dataframe)

    assert store.created_analysis_runs[0]["status"] == "running"
    assert store.learning_snapshots[-1][1] == {"status": "completed_with_errors"}
    assert [signal.analyzer_id for signal in result.signals] == ["healthy_analyzer"]
    assert result.executed_analyzers == ["healthy_analyzer"]
    assert store.analysis_run["status"] == "completed_with_errors"
    assert store.analysis_run["status"] != "completed"
    snapshots = {item["router_analyzer_id"]: item for item in result.analyzer_executions}
    assert snapshots["broken_analyzer"]["execution_status"] == "failed"
    assert snapshots["broken_analyzer"]["failed_pipeline_analyzer_ids"] == ["broken_analyzer"]
    assert "RuntimeError: intentional failure" in snapshots["broken_analyzer"]["execution_reason"]
    assert snapshots["healthy_analyzer"]["execution_status"] == "completed"
