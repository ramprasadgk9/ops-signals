from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from uuid import uuid4

import pandas as pd

from backend.app.services.timeseries_routing_service import TimeSeriesRoutingService
from intelligence.adapters.csv_adapter import CSVAdapter
from intelligence.analyzers import (
    BaselineShiftAnalyzer,
    ProphetAnalyzer,
    RupturesAnalyzer,
    STUMPYAnalyzer,
    TrendAnalyzer,
    ZScoreAnomalyAnalyzer,
)
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


logger = logging.getLogger(__name__)

ROUTER_VERSION = "1.0"
FEATURE_EXTRACTOR_VERSION = "1.0"


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
        if self.config.output.save_normalized_data:
            self.store.save_normalized_points(normalized, analysis_run_id=analysis_run_id)

        analyzer_routing, series_profile, registry_version = self._route_analyzers(normalized)
        analyzers = self._build_analyzers(analyzer_routing)
        executed_analyzers = [analyzer.analyzer_id for analyzer in analyzers]
        executed_analyzer_snapshots = self._executed_analyzer_snapshots(analyzer_routing, executed_analyzers)
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

        aggregation_result = FindingAggregator().aggregate(scored_signals, normalized, series_profile=series_profile)
        findings = aggregation_result.findings
        
        # Set analysis_run_id on findings before saving
        for finding in findings:
            finding.analysis_run_id = analysis_run_id

        self.store.save_findings(findings)
        self.store.update_analysis_run_learning_snapshot(
            analysis_run_id,
            {"generated_findings_json": [finding.to_record() for finding in findings]},
        )

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
            analyzer_routing=analyzer_routing,
            executed_analyzers=executed_analyzers,
            analyzer_executions=executed_analyzer_snapshots,
        )

    def _load_input(self) -> pd.DataFrame:
        if self.config.input.source_type != "csv":
            raise ValueError(f"Unsupported input source_type: {self.config.input.source_type}")
        adapter = CSVAdapter(self.config.input, self.base_path)
        return adapter.load()

    def _build_analyzers(self, analyzer_routing: list[dict[str, object]] | None = None) -> list:
        allowed = self._allowed_pipeline_analyzers(analyzer_routing or [])
        analyzers = []
        baseline_cfg = self.config.analysis.analyzers.get("baseline_shift")
        if baseline_cfg and baseline_cfg.enabled and self._should_run_analyzer("baseline_shift", allowed):
            analyzers.append(BaselineShiftAnalyzer(threshold_percent=float(baseline_cfg.params["threshold_percent"])))

        ruptures_cfg = self.config.analysis.analyzers.get("ruptures")
        if ruptures_cfg and ruptures_cfg.enabled and self._should_run_analyzer("ruptures", allowed):
            analyzers.append(
                RupturesAnalyzer(
                    min_segment_size=int(ruptures_cfg.params.get("min_segment_size", 5)),
                    change_threshold=float(ruptures_cfg.params.get("change_threshold", 1.5)),
                )
            )

        anomaly_cfg = self.config.analysis.analyzers.get("anomaly_zscore")
        if anomaly_cfg and anomaly_cfg.enabled and self._should_run_analyzer("anomaly_zscore", allowed):
            analyzers.append(
                ZScoreAnomalyAnalyzer(
                    zscore_threshold=float(anomaly_cfg.params["zscore_threshold"]),
                    grouping_gap=str(anomaly_cfg.params["grouping_gap"]),
                )
            )

        trend_cfg = self.config.analysis.analyzers.get("trend")
        if trend_cfg and trend_cfg.enabled and self._should_run_analyzer("trend", allowed):
            analyzers.append(TrendAnalyzer(min_slope_percent=float(trend_cfg.params["min_slope_percent"])))

        stumpy_cfg = self.config.analysis.analyzers.get("stumpy")
        if stumpy_cfg and stumpy_cfg.enabled and self._should_run_analyzer("stumpy", allowed):
            analyzers.append(
                STUMPYAnalyzer(
                    window_size=int(stumpy_cfg.params.get("window_size", 20)),
                    motif_count=int(stumpy_cfg.params.get("motif_count", 1)),
                    profile_threshold=float(stumpy_cfg.params.get("profile_threshold", 2.0)),
                )
            )

        prophet_cfg = self.config.analysis.analyzers.get("prophet")
        if prophet_cfg and prophet_cfg.enabled and self._should_run_analyzer("prophet", allowed):
            analyzers.append(
                ProphetAnalyzer(
                    horizon_points=int(prophet_cfg.params.get("horizon_points", 10)),
                    changepoint_prior_scale=float(prophet_cfg.params.get("changepoint_prior_scale", 0.05)),
                    uncertainty_threshold=float(prophet_cfg.params.get("uncertainty_threshold", 0.15)),
                )
            )
        return analyzers

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

    def _allowed_pipeline_analyzers(self, analyzer_routing: list[dict[str, object]]) -> set[str] | None:
        mode = (self.config.analysis.selection_mode or "all").lower().strip()
        if mode == "all" or not analyzer_routing:
            return None

        selected = set(self.config.analysis.selected_analyzers or [])
        recommended_router_ids = {
            str(decision["analyzer_id"])
            for decision in analyzer_routing
            if str(decision.get("recommendation")) == "RECOMMENDED"
        }
        if mode == "manual_override":
            recommended_router_ids.update(selected)
        elif mode != "recommended_only":
            return None

        router_to_pipeline = self._router_to_pipeline_analyzers()
        allowed: set[str] = set()
        for analyzer_id in recommended_router_ids:
            allowed.update(router_to_pipeline.get(analyzer_id, {analyzer_id}))
        return allowed

    def _executed_analyzer_snapshots(
        self,
        analyzer_routing: list[dict[str, object]],
        executed_analyzers: list[str],
    ) -> list[dict[str, object]]:
        router_to_pipeline = self._router_to_pipeline_analyzers()
        reverse_mapping = {
            "ruptures": "ruptures",
            "baseline_shift": "ruptures",
            "stumpy": "stumpy",
            "prophet": "prophet",
            "trend": "trend_regression",
            "anomaly_zscore": "adtk",
        }
        executed_set = set(executed_analyzers)
        snapshots = []
        routed_ids = {str(decision.get("analyzer_id")) for decision in analyzer_routing}
        for decision in analyzer_routing:
            router_analyzer_id = str(decision.get("analyzer_id"))
            pipeline_ids = sorted(router_to_pipeline.get(router_analyzer_id, {router_analyzer_id}))
            matching_executed = [pipeline_id for pipeline_id in pipeline_ids if pipeline_id in executed_set]
            recommended = str(decision.get("recommendation")) == "RECOMMENDED"
            selected = bool(recommended and pipeline_ids)
            status = "completed" if matching_executed else "skipped"
            reason = None
            if not recommended:
                selected = False
                status = "skipped"
                reason = f"Router decision was {decision.get('recommendation')}."
            elif not matching_executed:
                reason = "No enabled pipeline analyzer is available for this recommended router analyzer."
            snapshots.append(
                {
                    "router_analyzer_id": router_analyzer_id,
                    "display_name": decision.get("display_name") or router_analyzer_id,
                    "recommendation": decision.get("recommendation"),
                    "selected": selected,
                    "pipeline_analyzer_ids": pipeline_ids,
                    "executed_pipeline_analyzer_ids": matching_executed,
                    "execution_status": status,
                    "execution_reason": reason,
                }
            )
        for analyzer_id in executed_analyzers:
            router_analyzer_id = reverse_mapping.get(analyzer_id, analyzer_id)
            if router_analyzer_id in routed_ids:
                continue
            snapshots.append(
                {
                    "router_analyzer_id": router_analyzer_id,
                    "display_name": router_analyzer_id,
                    "recommendation": "UNROUTED",
                    "selected": True,
                    "pipeline_analyzer_ids": [analyzer_id],
                    "executed_pipeline_analyzer_ids": [analyzer_id],
                    "execution_status": "completed",
                    "execution_reason": None,
                }
            )
        return snapshots

    @staticmethod
    def _router_to_pipeline_analyzers() -> dict[str, set[str]]:
        return {
            "ruptures": {"ruptures", "baseline_shift"},
            "stumpy": {"stumpy"},
            "prophet": {"prophet"},
            "darts": {"prophet"},
            "trend_regression": {"trend"},
            "adtk": {"anomaly_zscore"},
            "pyod": {"anomaly_zscore"},
        }

    @staticmethod
    def _should_run_analyzer(analyzer_id: str, allowed: set[str] | None) -> bool:
        return allowed is None or analyzer_id in allowed

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
