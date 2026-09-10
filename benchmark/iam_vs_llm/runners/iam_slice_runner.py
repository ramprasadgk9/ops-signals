from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import pandas as pd
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from backend.app.models.entities import Base
from benchmark.iam_vs_llm.evaluators.normalization import normalize_iam_findings
from benchmark.iam_vs_llm.runners.base_runner import BaseBenchmarkRunner, BenchmarkRunResult, state_isolation
from intelligence.config import AppConfig, load_config
from intelligence.pipeline import SignalPipeline


class IsolatedInMemoryStore:
    """Ephemeral, in-memory store for isolated benchmark runs with zero external persistence."""

    def __init__(self) -> None:
        self.engine = create_engine(
            "sqlite+pysqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.normalized_points: pd.DataFrame | None = None
        self.saved_signals: list[Any] = []
        self.saved_findings: list[Any] = []
        self.learning_snapshots: list[tuple[str, dict[str, Any]]] = []
        self.created_analysis_runs: list[dict[str, Any]] = []
        self.capabilities: list[Any] = []
        self.questions: list[Any] = []
        self.answers: list[Any] = []
        self.analysis_run: dict[str, Any] | None = None

    def init_db(self) -> None:
        pass

    def init_db_from_sql(self, sql_path: Path) -> None:
        pass

    def save_normalized_points(self, dataframe: pd.DataFrame, analysis_run_id: str | None = None) -> None:
        self.normalized_points = dataframe.copy()

    def save_signals(self, signals: list[Any], embeddings: Any = None) -> None:
        self.saved_signals.extend(signals)

    def save_findings(self, findings: list[Any]) -> None:
        self.saved_findings.extend(findings)

    def fetch_findings(self) -> None:
        return None

    def create_analysis_run(self, payload: dict[str, Any]) -> None:
        self.created_analysis_runs.append(dict(payload))
        self.analysis_run = dict(payload)

    def update_analysis_run_learning_snapshot(self, analysis_run_id: str, snapshot: dict[str, Any]) -> None:
        self.learning_snapshots.append((analysis_run_id, dict(snapshot)))
        if self.analysis_run and self.analysis_run.get("id") == analysis_run_id:
            self.analysis_run.update(snapshot)

    def save_capabilities(self, capabilities: list[Any]) -> None:
        self.capabilities = capabilities

    def save_questions(self, questions: list[Any]) -> None:
        self.questions = questions

    def save_question_answers(self, answers: list[Any]) -> None:
        self.answers = answers


class StubEmbedder:
    """Zero-overhead deterministic embedder avoiding multi-gigabyte PyTorch/HuggingFace model loads."""
    def embed(self, text: str) -> list[float]:
        return [0.0] * 384


class IAMSliceRunner(BaseBenchmarkRunner):
    """Executes IAM's algorithmic time-series router and analyzers on scenario telemetry."""

    def __init__(self, config_path: str | Path | None = None) -> None:
        super().__init__(runner_id="iam_slice_runner")
        repo_root = Path(__file__).resolve().parents[3]
        self.config_path = Path(config_path) if config_path else repo_root / "config.yaml"

    def run_batch_ingest(self, scenario_dir: Path) -> BenchmarkRunResult:
        metrics_csv = scenario_dir / "metrics.csv"
        if not metrics_csv.exists():
            raise FileNotFoundError(f"Scenario metrics CSV not found at {metrics_csv}")

        df = pd.read_csv(metrics_csv)
        scenario_id = scenario_dir.name

        with state_isolation() as ctx:
            start_time = time.perf_counter()
            config = load_config(self.config_path)
            
            # Disable external heavy features for pure offline slice
            config.output.save_normalized_data = False
            config.output.save_signals = False
            config.output.save_question_answers = False

            store = IsolatedInMemoryStore()
            ctx.register_cleanup(lambda: store.engine.dispose())
            embedder = StubEmbedder()

            pipeline = SignalPipeline(config=config, store=store, embedder=embedder)
            pipeline_result = pipeline.run_dataframe(df)

            duration = time.perf_counter() - start_time

            # Retrieve any behavior intelligence causal findings
            from sqlalchemy import select
            from sqlalchemy.orm import Session
            from backend.app.models.entities import BehaviorFindingEntity

            behavior_findings = []
            if hasattr(store, "engine"):
                with Session(store.engine) as session:
                    behavior_findings = list(session.scalars(select(BehaviorFindingEntity)).all())

            normalized_rca = normalize_iam_findings(
                findings=pipeline_result.findings,
                signals=pipeline_result.signals,
                behavior_findings=behavior_findings,
            )

            return BenchmarkRunResult(
                runner_id=self.runner_id,
                scenario_id=scenario_id,
                normalized_rca=normalized_rca,
                execution_time_seconds=round(duration, 4),
                token_usage=0,  # Pure deterministic algorithmic pipeline
                cost_usd=0.0,
                tool_iterations=len(pipeline_result.executed_analyzers),
                metadata={
                    "executed_analyzers": pipeline_result.executed_analyzers,
                    "finding_count": len(pipeline_result.findings),
                    "signal_count": len(pipeline_result.signals),
                    "behavior_finding_count": len(behavior_findings),
                },
            )

    def execute(self, scenario_dir: Path) -> BenchmarkRunResult:
        """Executes telemetry triage via batch ingestion for IAM."""
        return self.run_batch_ingest(scenario_dir)

    def get_query_environment(self, scenario_dir: Path) -> Any | None:
        """IAM operates via direct batch ingestion and does not provide an interactive query environment."""
        return None
