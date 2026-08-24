from __future__ import annotations

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
from intelligence.analyzers import (
    BaselineShiftAnalyzer,
    ProphetAnalyzer,
    PyODOutlierAnalyzer,
    STUMPYAnalyzer,
    TrendAnalyzer,
    ZScoreAnomalyAnalyzer,
)
from intelligence.config import AppConfig
from intelligence.finding_aggregator import FindingAggregator
from intelligence.findings.schema import OperationalFinding
from intelligence.importance_score import score_signals
from intelligence.normalize.normalizer import normalize_timeseries
from intelligence.signals.schema import OperationalSignal
from intelligence.storage.postgres_store import PostgresStore

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


class MetricAnalysisExecutor:
    """Autonomous technical executor for one logical time series.

    This intentionally does not inherit from or call SignalPipeline. It reuses
    shared low-level components: normalization, router, analyzers, scoring,
    finding aggregation, behavior evaluation, and PostgresStore persistence.
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
    ) -> MetricAnalysisExecutionResult:
        normalized = normalize_timeseries(dataframe, self.config.input)
        return self.execute_normalized(normalized, run_metadata=run_metadata, db=db)

    def execute_normalized(
        self,
        normalized: pd.DataFrame,
        *,
        run_metadata: dict[str, object] | None = None,
        db: Session | None = None,
    ) -> MetricAnalysisExecutionResult:
        analysis_run_id = uuid4().hex
        self._create_analysis_run(analysis_run_id, normalized, run_metadata)
        if self.config.output.save_normalized_data:
            self.store.save_normalized_points(normalized, analysis_run_id=analysis_run_id)

        analyzer_routing, series_profile, registry_version = self._route_analyzers(normalized)
        analyzers = self._build_analyzers(analyzer_routing)
        executed_analyzers = [analyzer.analyzer_id for analyzer in analyzers]
        analyzer_executions = self._executed_analyzer_snapshots(analyzer_routing, executed_analyzers)
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
            self.store.save_signals(scored_signals, embeddings={})

        findings = FindingAggregator().aggregate(scored_signals, normalized, series_profile=series_profile).findings
        for finding in findings:
            finding.analysis_run_id = analysis_run_id
        self.store.save_findings(findings)
        self.store.update_analysis_run_learning_snapshot(
            analysis_run_id,
            {"generated_findings_json": [finding.to_record() for finding in findings]},
        )
        self._evaluate_behavior_intelligence(scored_signals, analysis_run_id, db=db)

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

    def _create_analysis_run(self, analysis_run_id: str, normalized: pd.DataFrame, run_metadata: dict[str, object] | None) -> None:
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

    def _route_analyzers(self, normalized: pd.DataFrame) -> tuple[list[dict[str, object]], dict[str, object], str | None]:
        if normalized.empty:
            return [], {}, None
        result = TimeSeriesRoutingService().route_normalized(normalized)
        return result.analyzer_routing, result.profile, result.registry_version

    def _build_analyzers(self, analyzer_routing: list[dict[str, object]]) -> list:
        allowed = self._allowed_pipeline_analyzers(analyzer_routing)
        analyzers = []
        baseline_cfg = self.config.analysis.analyzers.get("baseline_shift")
        if baseline_cfg and baseline_cfg.enabled and self._should_run_analyzer("baseline_shift", allowed):
            baseline_params = self._baseline_shift_params(baseline_cfg.params)
            analyzers.append(
                BaselineShiftAnalyzer(
                    threshold_percent=baseline_params["threshold_percent"],
                    min_segment_size=int(baseline_params["min_segment_size"]),
                    change_threshold=baseline_params["change_threshold"],
                    ruptures_algorithm=str(baseline_params["ruptures_algorithm"]),
                    ruptures_model=str(baseline_params["ruptures_model"]),
                    ruptures_jump=int(baseline_params["ruptures_jump"]),
                    ruptures_n_bkps=int(baseline_params["ruptures_n_bkps"]),
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
        pyod_outlier_cfg = self.config.analysis.analyzers.get("pyod_outlier")
        if pyod_outlier_cfg and pyod_outlier_cfg.enabled and self._should_run_analyzer("pyod_outlier", allowed):
            analyzers.append(
                PyODOutlierAnalyzer(
                    detector_type=str(pyod_outlier_cfg.params.get("detector_type", "knn")),
                    contamination=float(pyod_outlier_cfg.params.get("contamination", 0.05)),
                    grouping_gap=str(pyod_outlier_cfg.params.get("grouping_gap", "15m")),
                    min_samples=int(pyod_outlier_cfg.params.get("min_samples", 50)),
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

    def _executed_analyzer_snapshots(self, analyzer_routing: list[dict[str, object]], executed_analyzers: list[str]) -> list[dict[str, object]]:
        router_to_pipeline = self._router_to_pipeline_analyzers()
        reverse_mapping = {
            "baseline_shift": "ruptures",
            "stumpy": "stumpy",
            "prophet": "prophet",
            "trend": "trend_regression",
            "anomaly_zscore": "adtk",
            "pyod_outlier": "pyod_outlier",
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

    def _evaluate_behavior_intelligence(self, signals: list[OperationalSignal], analysis_run_id: str, db: Session | None = None) -> None:
        behavior_definitions_path = self._repo_root() / "config" / "behavior_definitions.yml"
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
    def _router_to_pipeline_analyzers() -> dict[str, set[str]]:
        return {
            "ruptures": {"baseline_shift"},
            "stumpy": {"stumpy"},
            "prophet": {"prophet"},
            "darts": {"prophet"},
            "kats": {"baseline_shift", "trend", "anomaly_zscore", "stumpy", "prophet"},
            "trend_regression": {"trend"},
            "adtk": {"anomaly_zscore"},
            "pyod": {"anomaly_zscore"},
            "pyod_outlier": {"pyod_outlier"},
        }

    @staticmethod
    def _baseline_shift_params(params: dict[str, object]) -> dict[str, float | int | str]:
        ruptures_params = params.get("ruptures") if isinstance(params.get("ruptures"), dict) else {}
        statistical_gate = params.get("statistical_gate") if isinstance(params.get("statistical_gate"), dict) else {}
        operational_significance = (
            params.get("operational_significance") if isinstance(params.get("operational_significance"), dict) else {}
        )
        return {
            "threshold_percent": float(
                operational_significance.get("min_change_percent", params.get("threshold_percent", 25))  # type: ignore[union-attr]
            ),
            "min_segment_size": int(
                ruptures_params.get("min_size", params.get("min_segment_size", 5))  # type: ignore[union-attr]
            ),
            "change_threshold": float(
                statistical_gate.get("min_effect_size", params.get("change_threshold", 1.5))  # type: ignore[union-attr]
            ),
            "ruptures_algorithm": str(
                ruptures_params.get("algorithm", params.get("ruptures_algorithm", "binseg"))  # type: ignore[union-attr]
            ),
            "ruptures_model": str(
                ruptures_params.get("model", params.get("ruptures_model", "l2"))  # type: ignore[union-attr]
            ),
            "ruptures_jump": int(
                ruptures_params.get("jump", params.get("ruptures_jump", 5))  # type: ignore[union-attr]
            ),
            "ruptures_n_bkps": int(
                ruptures_params.get("n_bkps", params.get("ruptures_n_bkps", 1))  # type: ignore[union-attr]
            ),
        }

    @staticmethod
    def _should_run_analyzer(analyzer_id: str, allowed: set[str] | None) -> bool:
        return allowed is None or analyzer_id in allowed

    @staticmethod
    def _repo_root() -> Path:
        return Path(__file__).resolve().parents[3]
