from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from uuid import uuid4

import pandas as pd

from backend.app.services.timeseries_routing_service import TimeSeriesRoutingService
from intelligence.adapters.csv_adapter import CSVAdapter
from intelligence.analyzer_selection import RegistryAnalyzerSelection
from intelligence.config import AppConfig
from intelligence.daily_report import OperationalIntelligenceReport, build_daily_report
from intelligence.finding_aggregator import FindingAggregator
from intelligence.embeddings.embedder import SummaryEmbedder
from intelligence.importance_score import score_signals
from intelligence.normalize.normalizer import normalize_timeseries
from intelligence.series_identity import run_analyzer_by_cluster
from intelligence.findings.schema import OperationalFinding
from intelligence.signals.schema import OperationalSignal
from intelligence.storage.postgres_store import PostgresStore
from backend.app.behavior_intelligence.service import BehaviorIntelligenceService
from backend.app.questions.catalog import QUESTION_CATALOG
from backend.app.questions.composer import AnswerComposer


logger = logging.getLogger(__name__)

ROUTER_VERSION = "1.0"
FEATURE_EXTRACTOR_VERSION = "1.0"

# Repo root, for locating top-level config/ directories (analyzer_registry.d,
# behavior_definitions.d) that live alongside config/, not relative to whichever specific config
# file (e.g. config/providers/prometheus.yaml) was loaded for a given run - self.base_path below
# is the *active config file's own directory*, which is right for resolving relative CSV
# file_path values but wrong for these, since it varies per provider/config path.
_REPO_ROOT = Path(__file__).resolve().parents[1]


@dataclass(slots=True)
class PipelineResult:
    normalized_points: pd.DataFrame
    signals: list[OperationalSignal]
    findings: list[OperationalFinding]
    report: OperationalIntelligenceReport
    analysis_run_id: str
    analyzer_routing: list[dict[str, object]]
    executed_analyzers: list[str]
    analyzer_executions: list[dict[str, object]]


class SignalPipeline(RegistryAnalyzerSelection):
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

    def run(self, run_metadata: dict[str, object] | None = None) -> PipelineResult:
        raw = self._load_input()
        normalized = normalize_timeseries(raw, self.config.input)
        return self.run_normalized(normalized, run_metadata=run_metadata)

    def run_dataframe(self, dataframe: pd.DataFrame, run_metadata: dict[str, object] | None = None) -> PipelineResult:
        normalized = normalize_timeseries(dataframe, self.config.input)
        return self.run_normalized(normalized, run_metadata=run_metadata)

    def run_normalized(self, normalized: pd.DataFrame, run_metadata: dict[str, object] | None = None) -> PipelineResult:
        analysis_run_id = uuid4().hex

        self._create_analysis_run(analysis_run_id, normalized, run_metadata=run_metadata)
        try:
            if self.config.output.save_normalized_data:
                self.store.save_normalized_points(normalized, analysis_run_id=analysis_run_id)

            analyzer_routing, series_profile, registry_version = self._route_analyzers(normalized)
            analyzers = self._build_analyzers(analyzer_routing)
            self._apply_analysis_window(analyzers, run_metadata)
            selected_analyzers = [analyzer.analyzer_id for analyzer in analyzers]
            selected_router_analyzers = self._selected_router_analyzers(analyzer_routing)
            executed_analyzer_snapshots = self._executed_analyzer_snapshots(
                analyzer_routing,
                [],
                selected_analyzers=selected_router_analyzers,
            )
            self.store.update_analysis_run_learning_snapshot(
                analysis_run_id,
                {
                    "router_version": ROUTER_VERSION,
                    "feature_extractor_version": FEATURE_EXTRACTOR_VERSION,
                    "analyzer_registry_version": registry_version,
                    "series_profile_json": series_profile,
                    "router_decisions_json": analyzer_routing,
                    "executed_analyzers_json": executed_analyzer_snapshots,
                },
            )
            if self.config.questions.auto_generate_from_capabilities:
                self.store.save_questions(QUESTION_CATALOG)
            if self.config.capabilities.auto_register:
                self.store.save_capabilities([
                    asdict(analyzer.capability()) for analyzer in analyzers
                ])

            signals, failed_analyzers = self._run_analyzers(analyzers, normalized, analysis_run_id)
            executed_analyzers = [
                analyzer_id for analyzer_id in selected_analyzers if analyzer_id not in failed_analyzers
            ]
            executed_analyzer_snapshots = self._executed_analyzer_snapshots(
                analyzer_routing,
                executed_analyzers,
                failed_analyzers=failed_analyzers,
                selected_analyzers=selected_router_analyzers,
            )
            self.store.update_analysis_run_learning_snapshot(
                analysis_run_id,
                {"executed_analyzers_json": executed_analyzer_snapshots},
            )

            analysis_window_end = None
            if not normalized.empty:
                analysis_window_end = pd.to_datetime(normalized["timestamp"], utc=True, errors="coerce").max().to_pydatetime()

            scored_signals = score_signals(signals, analysis_window_end)

            if self.config.output.save_signals:
                embeddings = self._build_embeddings(signals)
                self.store.save_signals(scored_signals, embeddings)

            aggregation_result = FindingAggregator().aggregate(scored_signals, normalized, series_profile=series_profile)
            findings = aggregation_result.findings

            for finding in findings:
                finding.analysis_run_id = analysis_run_id

            self.store.save_findings(findings)
            self.store.update_analysis_run_learning_snapshot(
                analysis_run_id,
                {"generated_findings_json": [finding.to_json() for finding in findings]},
            )

            self._evaluate_behavior_intelligence(signals, analysis_run_id)

            if self.config.output.save_question_answers:
                self._save_question_answers(analysis_run_id, scored_signals)

            self._finalize_analysis_run(analysis_run_id, selected_analyzers, executed_analyzers, failed_analyzers)
            report = build_daily_report(findings, normalized)
            return PipelineResult(
                normalized_points=normalized,
                signals=scored_signals,
                findings=findings,
                report=report,
                analysis_run_id=analysis_run_id,
                analyzer_routing=analyzer_routing,
                executed_analyzers=executed_analyzers,
                analyzer_executions=executed_analyzer_snapshots,
            )
        except Exception:
            self.store.update_analysis_run_learning_snapshot(analysis_run_id, {"status": "failed"})
            raise

    def _run_analyzers(
        self,
        analyzers: list,
        normalized: pd.DataFrame,
        analysis_run_id: str,
    ) -> tuple[list[OperationalSignal], dict[str, str]]:
        signals: list[OperationalSignal] = []
        failed_analyzers: dict[str, str] = {}
        for analyzer in analyzers:
            analyzer_id = str(analyzer.analyzer_id)
            try:
                generated = run_analyzer_by_cluster(analyzer, normalized)
            except Exception as exc:  # pragma: no cover - exact analyzer failures vary by dependency
                logger.exception("Analyzer %s failed during execution", analyzer_id)
                failed_analyzers[analyzer_id] = f"{type(exc).__name__}: {exc}"
                continue
            for signal in generated:
                signal.analysis_run_id = analysis_run_id
            signals.extend(generated)
        return signals, failed_analyzers

    def _load_input(self) -> pd.DataFrame:
        if self.config.input.source_type != "csv":
            raise ValueError(f"Unsupported input source_type: {self.config.input.source_type}")
        adapter = CSVAdapter(self.config.input, self.base_path)
        return adapter.load()

    def _route_analyzers(self, normalized: pd.DataFrame) -> tuple[list[dict[str, object]], dict[str, object], str | None]:
        if normalized.empty:
            return [], {}, None
        try:
            result = TimeSeriesRoutingService().route_normalized(normalized)
        except Exception as exc:
            logger.exception("Analyzer router failed during pipeline routing")
            return [
                {
                    "analyzer_id": "router",
                    "display_name": "Analyzer Router",
                    "eligible": False,
                    "recommendation": "REJECTED",
                    "final_score": 0.0,
                    "reasons": [
                        "Router metadata could not be calculated for this run. Check backend logs for the full exception."
                    ],
                    "warnings": [str(exc)],
                }
            ], {}, None
        return result.analyzer_routing, result.profile, result.registry_version

    def _build_embeddings(self, signals: list[OperationalSignal]) -> dict[int, list[float]]:
        if not (self.config.embeddings.enabled and self.config.output.save_embeddings):
            return {}
        vectors: dict[int, list[float]] = {}
        for index, signal in enumerate(signals):
            embedding = self.embedder.embed(signal.summary)
            if embedding is not None:
                vectors[index] = list(embedding)
        return vectors

    def _create_analysis_run(
        self,
        analysis_run_id: str,
        normalized: pd.DataFrame,
        run_metadata: dict[str, object] | None = None,
    ) -> None:
        if normalized.empty:
            return
        payload = {
            "id": analysis_run_id,
            "source_type": self.config.input.source_type,
            "file_name": str(run_metadata.get("file_name")) if run_metadata and run_metadata.get("file_name") else None,
            "provider": (self.config.input.provider or "generic").lower(),
            "service": str(normalized["service"].dropna().iloc[0]) if "service" in normalized.columns and not normalized["service"].dropna().empty else "unknown",
            "metric_name": str(normalized["metric_name"].dropna().iloc[0]),
            "start_time": pd.to_datetime(normalized["timestamp"], utc=True, errors="coerce").min().to_pydatetime(),
            "end_time": pd.to_datetime(normalized["timestamp"], utc=True, errors="coerce").max().to_pydatetime(),
            "sample_count": int(len(normalized)),
            "status": "running",
            "connection_id": str(run_metadata["connection_id"]) if run_metadata and run_metadata.get("connection_id") else None,
            "created_at": datetime.utcnow(),
        }
        self.store.create_analysis_run(payload)

    def _finalize_analysis_run(
        self,
        analysis_run_id: str,
        selected_analyzers: list[str],
        executed_analyzers: list[str],
        failed_analyzers: dict[str, str],
    ) -> None:
        if failed_analyzers and not executed_analyzers and selected_analyzers:
            status = "failed"
        elif failed_analyzers:
            status = "completed_with_errors"
        else:
            status = "completed"
        self.store.update_analysis_run_learning_snapshot(analysis_run_id, {"status": status})

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
        behavior_definitions_path = _REPO_ROOT / "config" / "behavior_definitions.d"
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
