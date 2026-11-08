from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from uuid import uuid4

import pandas as pd
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from backend.app.behavior_intelligence.service import BehaviorIntelligenceService
from backend.app.models.entities import BehaviorFindingEntity, FindingEntity, SignalEntity
from backend.app.services.timeseries_routing_service import TimeSeriesRoutingService
from intelligence.analyzer_selection import RegistryAnalyzerSelection
from intelligence.config import AppConfig
from intelligence.finding_aggregator import FindingAggregator
from intelligence.findings.schema import OperationalFinding
from intelligence.importance_score import score_signals
from intelligence.normalize.normalizer import normalize_timeseries
from intelligence.series_identity import run_analyzer_by_cluster
from intelligence.signals.schema import OperationalSignal
from intelligence.storage.postgres_store import PostgresStore

logger = logging.getLogger(__name__)

ROUTER_VERSION = "1.0"
FEATURE_EXTRACTOR_VERSION = "1.0"


@dataclass(slots=True)
class MetricAnalysisExecutionResult:
    analysis_run_id: str
    normalized_points: pd.DataFrame
    signals: list[OperationalSignal]
    findings: list[OperationalFinding]
    analyzer_routing: list[dict[str, object]]
    executed_analyzers: list[str]
    analyzer_executions: list[dict[str, object]]
    signal_count: int
    findings_count: int
    behavior_findings_count: int


class MetricAnalysisExecutor(RegistryAnalyzerSelection):
    """Autonomous technical executor for one logical time series.

    This intentionally does not inherit from or call SignalPipeline. It reuses
    shared low-level components: normalization, router, analyzer construction and
    selection (RegistryAnalyzerSelection), scoring, finding aggregation, behavior
    evaluation, and PostgresStore persistence.
    """

    def __init__(self, config: AppConfig, store: PostgresStore | None = None) -> None:
        self.config = config
        self.store = store or PostgresStore(config)
        self.base_path = config.config_path.parent

    def execute_dataframe(
        self,
        dataframe: pd.DataFrame,
        *,
        run_metadata: dict[str, object] | None = None,
        db: Session | None = None,
        persist_points_after: datetime | None = None,
        series_key: str | None = None,
    ) -> MetricAnalysisExecutionResult:
        normalized = normalize_timeseries(dataframe, self.config.input)
        return self.execute_normalized(normalized, run_metadata=run_metadata, db=db, persist_points_after=persist_points_after, series_key=series_key)

    def execute_normalized(
        self,
        normalized: pd.DataFrame,
        *,
        run_metadata: dict[str, object] | None = None,
        db: Session | None = None,
        persist_points_after: datetime | None = None,
        series_key: str | None = None,
    ) -> MetricAnalysisExecutionResult:
        """`persist_points_after`: store only the normalized points after this time, when the
        earlier ones are history that is already stored (OTLP runs). `series_key`: the stored
        series these points belong to; only points after its newest stored one are saved, since
        the earlier ones were saved by an earlier run of the same window (backend/app/services/run_points.py)."""
        analysis_run_id = uuid4().hex
        self._create_analysis_run(analysis_run_id, normalized, run_metadata, series_key=series_key)
        try:
            if self.config.output.save_normalized_data:
                to_save = normalized
                if series_key and persist_points_after is None:
                    persist_points_after = self.store.latest_point_time(series_key)
                if persist_points_after is not None:
                    to_save = normalized[pd.to_datetime(normalized["timestamp"], utc=True) > pd.Timestamp(persist_points_after)]
                if not to_save.empty:
                    self.store.save_normalized_points(to_save, analysis_run_id=analysis_run_id, series_key=series_key)

            analyzer_routing, series_profile, registry_version = self._route_analyzers(normalized)
            # Per-service settings for this series, if any override applies to it.
            series_analyzers = self._build_series_analyzers(normalized, analyzer_routing, run_metadata)
            series_settings = [settings for settings, _ in series_analyzers]
            selected_analyzers = list(dict.fromkeys(analyzer.analyzer_id for _, group in series_analyzers for analyzer in group))
            analyzer_executions = self._series_snapshots(
                series_settings, analyzer_routing, [[] for _ in series_settings], [{} for _ in series_settings]
            )
            self.store.update_analysis_run_learning_snapshot(
                analysis_run_id,
                {
                    "router_version": ROUTER_VERSION,
                    "feature_extractor_version": FEATURE_EXTRACTOR_VERSION,
                    "analyzer_registry_version": registry_version,
                    "series_profile_json": series_profile,
                    "router_decisions_json": analyzer_routing,
                    "executed_analyzers_json": analyzer_executions,
                },
            )

            signals, executed_by_series, failed_by_series = self._run_series_analyzers(series_analyzers, normalized, analysis_run_id)
            failed_analyzers = {analyzer_id: error for failed in failed_by_series for analyzer_id, error in failed.items()}
            executed_analyzers = [
                analyzer_id for analyzer_id in selected_analyzers if any(analyzer_id in executed for executed in executed_by_series)
            ]
            analyzer_executions = self._series_snapshots(series_settings, analyzer_routing, executed_by_series, failed_by_series)
            self.store.update_analysis_run_learning_snapshot(
                analysis_run_id,
                {"executed_analyzers_json": analyzer_executions},
            )

            analysis_window_end = None
            if not normalized.empty:
                analysis_window_end = pd.to_datetime(normalized["timestamp"], utc=True, errors="coerce").max().to_pydatetime()
            scored_signals = score_signals(signals, analysis_window_end)

            if self.config.output.save_signals:
                self.store.save_signals(scored_signals, embeddings={})

            findings = FindingAggregator().aggregate(scored_signals, normalized, series_profile=series_profile).findings
            for finding in findings:
                finding.analysis_run_id = analysis_run_id
            self.store.save_findings(findings)
            self._save_level_events(analysis_run_id, normalized)
            self._mark_finding_contributors(analyzer_executions, scored_signals, findings)
            self.store.update_analysis_run_learning_snapshot(
                analysis_run_id,
                {
                    "generated_findings_json": [finding.to_json() for finding in findings],
                    "executed_analyzers_json": analyzer_executions,
                },
            )
            self._evaluate_behavior_intelligence(scored_signals, analysis_run_id, db=db)

            self._finalize_analysis_run(analysis_run_id, selected_analyzers, executed_analyzers, failed_analyzers)
            signal_count, finding_count, behavior_count = self._counts(analysis_run_id, db=db)
            return MetricAnalysisExecutionResult(
                analysis_run_id=analysis_run_id,
                normalized_points=normalized,
                signals=scored_signals,
                findings=findings,
                analyzer_routing=analyzer_routing,
                executed_analyzers=executed_analyzers,
                analyzer_executions=analyzer_executions,
                signal_count=signal_count,
                findings_count=finding_count,
                behavior_findings_count=behavior_count,
            )
        except Exception:
            self.store.update_analysis_run_learning_snapshot(analysis_run_id, {"status": "failed"})
            raise

    def _save_level_events(self, analysis_run_id: str, normalized: pd.DataFrame) -> None:
        """As SignalPipeline: whether open level changes on this series came back. It only labels
        earlier problems, so a failure is logged and the run goes on."""
        try:
            self.store.save_level_events(analysis_run_id, normalized)
        except Exception:
            logger.warning("Checking whether level changes came back failed for run %s", analysis_run_id, exc_info=True)

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
                logger.exception("Analyzer %s failed during autonomous execution", analyzer_id)
                failed_analyzers[analyzer_id] = f"{type(exc).__name__}: {exc}"
                continue
            for signal in generated:
                signal.analysis_run_id = analysis_run_id
            signals.extend(generated)
        return signals, failed_analyzers

    def _create_analysis_run(
        self, analysis_run_id: str, normalized: pd.DataFrame, run_metadata: dict[str, object] | None, series_key: str | None = None
    ) -> None:
        if normalized.empty:
            return
        payload = {
            "id": analysis_run_id,
            "source_type": self.config.input.source_type,
            "file_name": str(run_metadata.get("file_name")) if run_metadata and run_metadata.get("file_name") else None,
            # The Prometheus connection (Mimir tenant) it queried, as SignalPipeline records it.
            "connection_id": str(run_metadata["connection_id"]) if run_metadata and run_metadata.get("connection_id") else None,
            "promql": str(run_metadata["promql"]) if run_metadata and run_metadata.get("promql") else None,
            "series_key": series_key,
            "provider": (self.config.input.provider or "generic").lower(),
            "service": str(normalized["service"].dropna().iloc[0]) if "service" in normalized.columns and not normalized["service"].dropna().empty else "unknown",
            "metric_name": str(normalized["metric_name"].dropna().iloc[0]),
            "start_time": pd.to_datetime(normalized["timestamp"], utc=True, errors="coerce").min().to_pydatetime(),
            "end_time": pd.to_datetime(normalized["timestamp"], utc=True, errors="coerce").max().to_pydatetime(),
            "sample_count": int(len(normalized)),
            "status": "running",
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

    def _route_analyzers(self, normalized: pd.DataFrame) -> tuple[list[dict[str, object]], dict[str, object], str | None]:
        if normalized.empty:
            return [], {}, None
        result = TimeSeriesRoutingService().route_normalized(normalized)
        return result.analyzer_routing, result.profile, result.registry_version

    def _evaluate_behavior_intelligence(self, signals: list[OperationalSignal], analysis_run_id: str, db: Session | None = None) -> None:
        behavior_definitions_path = self._repo_root() / "config" / "behavior_definitions.d"
        if not behavior_definitions_path.exists():
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
        if db is not None:
            service.evaluate(signal_dicts, db)
            return
        session_local = sessionmaker(bind=self.store.engine, autocommit=False, autoflush=False)
        with session_local() as session:
            service.evaluate(signal_dicts, session)

    def _counts(self, analysis_run_id: str, db: Session | None = None) -> tuple[int, int, int]:
        if db is None:
            session_local = sessionmaker(bind=self.store.engine, autocommit=False, autoflush=False)
            with session_local() as session:
                return self._counts(analysis_run_id, db=session)
        findings_count = db.execute(select(func.count(FindingEntity.id)).where(FindingEntity.analysis_run_id == analysis_run_id)).scalar() or 0
        signal_count = db.execute(select(func.count(SignalEntity.id)).where(SignalEntity.analysis_run_id == analysis_run_id)).scalar() or 0
        behavior_count = db.execute(select(func.count(BehaviorFindingEntity.id)).where(BehaviorFindingEntity.analysis_run_id == analysis_run_id)).scalar() or 0
        return int(signal_count), int(findings_count), int(behavior_count)

    @staticmethod
    def _repo_root() -> Path:
        return Path(__file__).resolve().parents[3]
