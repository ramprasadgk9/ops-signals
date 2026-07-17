from __future__ import annotations

from pathlib import Path

from intelligence.config import load_config
from intelligence.pipeline import SignalPipeline


class InMemoryStore:
    def __init__(self) -> None:
        self.normalized_points = None
        self.saved_signals = []
        self.saved_findings = []
        self.initialized = False

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
        self.analysis_run = payload

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
    assert len(result.findings) == 1
    assert result.report.answers["what_changed_yesterday"]
