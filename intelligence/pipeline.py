from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from uuid import uuid4

import pandas as pd

from intelligence.adapters.csv_adapter import CSVAdapter
from intelligence.analyzers import BaselineShiftAnalyzer, RupturesAnalyzer, TrendAnalyzer, ZScoreAnomalyAnalyzer
from intelligence.config import AppConfig
from intelligence.daily_report import OperationalIntelligenceReport, build_daily_report
from intelligence.finding_aggregator import FindingAggregator
from intelligence.embeddings.embedder import SummaryEmbedder
from intelligence.importance_score import score_signals
from intelligence.normalize.normalizer import normalize_timeseries
from intelligence.findings.schema import OperationalFinding
from intelligence.signals.schema import OperationalSignal
from intelligence.storage.postgres_store import PostgresStore
from backend.app.behavior_intelligence.service import BehaviorIntelligenceService
from backend.app.questions.catalog import QUESTION_CATALOG
from backend.app.questions.composer import AnswerComposer


@dataclass(slots=True)
class PipelineResult:
    normalized_points: pd.DataFrame
    signals: list[OperationalSignal]
    findings: list[OperationalFinding]
    report: OperationalIntelligenceReport
    analysis_run_id: str


class SignalPipeline:
    def __init__(self, config: AppConfig, store: PostgresStore | None = None, embedder: SummaryEmbedder | None = None) -> None:
        self.config = config
        self.base_path = config.config_path.parent
        self.store = store or PostgresStore(config)
        self.embedder = embedder or SummaryEmbedder(config.embeddings)

    def init_db(self) -> None:
        sql_path = self.base_path / "sql" / "init.sql"
        if sql_path.exists() and self.config.storage.postgres.table_prefix == "ops_":
            self.store.init_db_from_sql(sql_path)
            return
        self.store.init_db()

    def run(self) -> PipelineResult:
        raw = self._load_input()
        normalized = normalize_timeseries(raw, self.config.input)
        analysis_run_id = uuid4().hex

        self._create_analysis_run(analysis_run_id, normalized)
        if self.config.output.save_normalized_data:
            self.store.save_normalized_points(normalized, analysis_run_id=analysis_run_id)

        analyzers = self._build_analyzers()
        if self.config.questions.auto_generate_from_capabilities:
            self.store.save_questions(QUESTION_CATALOG)
        if self.config.capabilities.auto_register:
            self.store.save_capabilities([
                asdict(analyzer.capability()) for analyzer in analyzers
            ])

        signals: list[OperationalSignal] = []
        for analyzer in analyzers:
            generated = analyzer.analyze(normalized)
            for signal in generated:
                signal.analysis_run_id = analysis_run_id
            signals.extend(generated)

        analysis_window_end = None
        if not normalized.empty:
            analysis_window_end = pd.to_datetime(normalized["timestamp"], utc=True, errors="coerce").max().to_pydatetime()

        scored_signals = score_signals(signals, analysis_window_end)

        if self.config.output.save_signals:
            embeddings = self._build_embeddings(signals)
            self.store.save_signals(scored_signals, embeddings)

        aggregation_result = FindingAggregator().aggregate(scored_signals, normalized)
        findings = aggregation_result.findings
        
        # Set analysis_run_id on findings before saving
        for finding in findings:
            finding.analysis_run_id = analysis_run_id

        self.store.save_findings(findings)

        self._evaluate_behavior_intelligence(signals, analysis_run_id)

        if self.config.output.save_question_answers:
            self._save_question_answers(analysis_run_id, scored_signals)

        report = build_daily_report(findings, normalized)
        return PipelineResult(
            normalized_points=normalized,
            signals=scored_signals,
            findings=findings,
            report=report,
            analysis_run_id=analysis_run_id,
        )

    def _load_input(self) -> pd.DataFrame:
        if self.config.input.source_type != "csv":
            raise ValueError(f"Unsupported input source_type: {self.config.input.source_type}")
        adapter = CSVAdapter(self.config.input, self.base_path)
        return adapter.load()

    def _build_analyzers(self) -> list:
        analyzers = []
        baseline_cfg = self.config.analysis.analyzers.get("baseline_shift")
        if baseline_cfg and baseline_cfg.enabled:
            analyzers.append(BaselineShiftAnalyzer(threshold_percent=float(baseline_cfg.params["threshold_percent"])))

        ruptures_cfg = self.config.analysis.analyzers.get("ruptures")
        if ruptures_cfg and ruptures_cfg.enabled:
            analyzers.append(
                RupturesAnalyzer(
                    min_segment_size=int(ruptures_cfg.params.get("min_segment_size", 5)),
                    change_threshold=float(ruptures_cfg.params.get("change_threshold", 1.5)),
                )
            )

        anomaly_cfg = self.config.analysis.analyzers.get("anomaly_zscore")
        if anomaly_cfg and anomaly_cfg.enabled:
            analyzers.append(
                ZScoreAnomalyAnalyzer(
                    zscore_threshold=float(anomaly_cfg.params["zscore_threshold"]),
                    grouping_gap=str(anomaly_cfg.params["grouping_gap"]),
                )
            )

        trend_cfg = self.config.analysis.analyzers.get("trend")
        if trend_cfg and trend_cfg.enabled:
            analyzers.append(TrendAnalyzer(min_slope_percent=float(trend_cfg.params["min_slope_percent"])))
        return analyzers

    def _build_embeddings(self, signals: list[OperationalSignal]) -> dict[int, list[float]]:
        if not (self.config.embeddings.enabled and self.config.output.save_embeddings):
            return {}
        vectors: dict[int, list[float]] = {}
        for index, signal in enumerate(signals):
            embedding = self.embedder.embed(signal.summary)
            if embedding is not None:
                vectors[index] = list(embedding)
        return vectors

    def _create_analysis_run(self, analysis_run_id: str, normalized: pd.DataFrame) -> None:
        if normalized.empty:
            return
        payload = {
            "id": analysis_run_id,
            "source_type": self.config.input.source_type,
            "provider": (self.config.input.provider or "generic").lower(),
            "service": str(normalized["service"].dropna().iloc[0]) if "service" in normalized.columns and not normalized["service"].dropna().empty else "unknown",
            "metric_name": str(normalized["metric_name"].dropna().iloc[0]),
            "start_time": pd.to_datetime(normalized["timestamp"], utc=True, errors="coerce").min().to_pydatetime(),
            "end_time": pd.to_datetime(normalized["timestamp"], utc=True, errors="coerce").max().to_pydatetime(),
            "sample_count": int(len(normalized)),
            "status": "completed",
            "created_at": datetime.utcnow(),
        }
        self.store.create_analysis_run(payload)

    def _save_question_answers(self, analysis_run_id: str, signals: list[OperationalSignal]) -> None:
        if not signals:
            return
        composer = AnswerComposer()
        signal_dicts = [
            {
                "id": signal.signal_id,
                "signal_type": signal.signal_type,
                "analyzer_id": signal.analyzer_id,
                "severity": signal.severity,
                "confidence": signal.confidence,
                "importance_score": signal.importance_score,
                "summary": signal.summary,
                "evidence": signal.evidence,
            }
            for signal in signals
        ]
        answers: list[dict[str, object]] = []
        for question in QUESTION_CATALOG:
            question_id = str(question["id"])
            answer = composer.compose(question_id, signal_dicts)
            answers.append(
                {
                    "analysis_run_id": analysis_run_id,
                    "question_id": question_id,
                    "headline": answer.headline,
                    "answer": answer.answer,
                    "status": answer.status,
                    "priority": answer.priority,
                    "confidence": answer.confidence,
                    "key_points_json": answer.key_points,
                    "evidence_signal_ids": answer.evidence_signal_ids,
                }
            )
        self.store.save_question_answers(answers)

    def _evaluate_behavior_intelligence(self, signals: list[OperationalSignal], analysis_run_id: str) -> None:
        behavior_definitions_path = self.base_path / "config" / "behavior_definitions.yml"
        if not behavior_definitions_path.exists() or not hasattr(self.store, "engine"):
            return
        service = BehaviorIntelligenceService(behavior_definitions_path)
        signal_dicts = [
            {
                "id": signal.signal_id,
                "signal_type": signal.signal_type,
                "analyzer_id": signal.analyzer_id,
                "metric_name": signal.metric_name,
                "service": signal.service,
                "severity": signal.severity,
                "confidence": signal.confidence,
                "start_time": signal.start_time,
                "end_time": signal.end_time,
                "summary": signal.summary,
                "evidence": signal.evidence,
                "importance_score": signal.importance_score,
                "analysis_run_id": analysis_run_id,
            }
            for signal in signals
        ]
        from sqlalchemy.orm import sessionmaker

        session_local = sessionmaker(bind=self.store.engine, autocommit=False, autoflush=False)
        with session_local() as db:
            service.evaluate(signal_dicts, db)
