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
    PyODOutlierAnalyzer,
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
        try:
            if self.config.output.save_normalized_data:
                self.store.save_normalized_points(normalized, analysis_run_id=analysis_run_id)

            analyzer_routing, series_profile, registry_version = self._route_analyzers(normalized)
            analyzers = self._build_analyzers(analyzer_routing)
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
                {"generated_findings_json": [finding.to_record() for finding in findings]},
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
                generated = analyzer.analyze(normalized)
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

    def _build_analyzers(self, analyzer_routing: list[dict[str, object]] | None = None) -> list:
        allowed = self._allowed_pipeline_analyzers(analyzer_routing or [])
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

        ruptures_cfg = self.config.analysis.analyzers.get("ruptures")
        if ruptures_cfg and ruptures_cfg.enabled and self._should_run_analyzer("ruptures", allowed):
            ruptures_params = self._baseline_shift_params(ruptures_cfg.params)
            analyzers.append(
                RupturesAnalyzer(
                    min_segment_size=int(ruptures_params["min_segment_size"]),
                    change_threshold=ruptures_params["change_threshold"],
                )
            )

        anomaly_cfg = self.config.analysis.analyzers.get("anomaly_zscore")
        if anomaly_cfg and anomaly_cfg.enabled and self._should_run_analyzer("anomaly_zscore", allowed):
            anomaly_impl = self._analyzer_implementation(anomaly_cfg.params) or {}
            analyzers.append(
                ZScoreAnomalyAnalyzer(
                    zscore_threshold=float(anomaly_impl.get("zscore_threshold", anomaly_cfg.params.get("zscore_threshold", 3.0))),
                    grouping_gap=str(anomaly_impl.get("grouping_gap", anomaly_cfg.params.get("grouping_gap", "15m"))),
                    finding_rules=self._analyzer_finding_rules(anomaly_cfg.params),
                    implementation=anomaly_impl,
                )
            )

        pyod_outlier_cfg = self.config.analysis.analyzers.get("pyod_outlier")
        if pyod_outlier_cfg and pyod_outlier_cfg.enabled and self._should_run_analyzer("pyod_outlier", allowed):
            pyod_impl = self._analyzer_implementation(pyod_outlier_cfg.params) or {}
            analyzers.append(
                PyODOutlierAnalyzer(
                    detector_type=str(pyod_impl.get("detector_type", pyod_outlier_cfg.params.get("detector_type", "knn"))),
                    contamination=float(pyod_impl.get("contamination", pyod_outlier_cfg.params.get("contamination", 0.05))),
                    grouping_gap=str(pyod_impl.get("grouping_gap", pyod_outlier_cfg.params.get("grouping_gap", "15m"))),
                    min_samples=int(pyod_impl.get("min_samples", pyod_outlier_cfg.params.get("min_samples", 50))),
                    finding_rule=self._analyzer_finding_rules(pyod_outlier_cfg.params),
                    implementation=pyod_impl,
                )
            )

        trend_cfg = self.config.analysis.analyzers.get("trend")
        if trend_cfg and trend_cfg.enabled and self._should_run_analyzer("trend", allowed):
            analyzers.append(
                TrendAnalyzer(
                    min_slope_percent=float(trend_cfg.params["min_slope_percent"])
                    if "min_slope_percent" in trend_cfg.params
                    else None,
                    finding_rules=self._analyzer_finding_rules(trend_cfg.params),
                    implementation=self._analyzer_implementation(trend_cfg.params),
                )
            )

        stumpy_cfg = self.config.analysis.analyzers.get("stumpy")
        if stumpy_cfg and stumpy_cfg.enabled and self._should_run_analyzer("stumpy", allowed):
            stumpy_impl = self._analyzer_implementation(stumpy_cfg.params) or {}
            analyzers.append(
                STUMPYAnalyzer(
                    window_size=int(stumpy_impl.get("window_size", stumpy_cfg.params.get("window_size", 20))),
                    motif_count=int(stumpy_impl.get("motif_count", stumpy_cfg.params.get("motif_count", 1))),
                    profile_threshold=float(stumpy_impl.get("profile_threshold", stumpy_cfg.params.get("profile_threshold", 2.0))),
                    finding_rules=self._analyzer_finding_rules(stumpy_cfg.params),
                    implementation=stumpy_impl,
                )
            )

        prophet_cfg = self.config.analysis.analyzers.get("prophet")
        if prophet_cfg and prophet_cfg.enabled and self._should_run_analyzer("prophet", allowed):
            prophet_impl = self._analyzer_implementation(prophet_cfg.params) or {}
            analyzers.append(
                ProphetAnalyzer(
                    horizon_points=int(prophet_impl.get("horizon_points", prophet_cfg.params.get("horizon_points", 10))),
                    changepoint_prior_scale=float(prophet_impl.get("changepoint_prior_scale", prophet_cfg.params.get("changepoint_prior_scale", 0.05))),
                    uncertainty_threshold=float(prophet_impl.get("uncertainty_threshold", prophet_cfg.params.get("uncertainty_threshold", 0.15))),
                    finding_rules=self._analyzer_finding_rules(prophet_cfg.params),
                    implementation=prophet_impl,
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
        selected_router_ids = self._selected_router_analyzers(analyzer_routing)
        if selected_router_ids is None:
            return None

        allowed: set[str] = set()
        router_to_pipeline = self._router_to_pipeline_analyzers()
        for analyzer_id in selected_router_ids:
            allowed.update(router_to_pipeline.get(analyzer_id, {analyzer_id}))
        return allowed

    def _selected_router_analyzers(self, analyzer_routing: list[dict[str, object]]) -> set[str] | None:
        mode = (self.config.analysis.selection_mode or "all").lower().strip()
        if mode == "all" or not analyzer_routing:
            return None

        selected = set(self.config.analysis.selected_analyzers or [])
        if mode == "manual_override":
            recommended_router_ids = {
                str(decision["analyzer_id"])
                for decision in analyzer_routing
                if str(decision.get("recommendation")) == "RECOMMENDED"
            }
            recommended_router_ids.update(selected)
            return recommended_router_ids

        if mode == "recommended_only":
            return {
                str(decision["analyzer_id"])
                for decision in analyzer_routing
                if str(decision.get("recommendation")) == "RECOMMENDED"
            }

        if mode != "recommended_threshold":
            return None

        execution_config = self.config.analysis.recommendation_execution
        allowed_recommendations = {"RECOMMENDED"}
        if execution_config.include_optional:
            allowed_recommendations.add("OPTIONAL")
        candidates = [
            (self._decision_score(decision), str(decision["analyzer_id"]))
            for decision in analyzer_routing
            if str(decision.get("recommendation")) in allowed_recommendations
            and self._decision_score(decision) >= execution_config.min_score
        ]
        candidates.sort(key=lambda item: item[0], reverse=True)
        max_analyzers = max(1, execution_config.max_analyzers)
        return {analyzer_id for _, analyzer_id in candidates[:max_analyzers]}

    def _executed_analyzer_snapshots(
        self,
        analyzer_routing: list[dict[str, object]],
        executed_analyzers: list[str],
        failed_analyzers: dict[str, str] | None = None,
        selected_analyzers: set[str] | None = None,
    ) -> list[dict[str, object]]:
        failed_analyzers = failed_analyzers or {}
        executed_set = set(executed_analyzers)
        failed_set = set(failed_analyzers)
        selected_router_ids = selected_analyzers
        snapshots = []
        routed_ids = {str(decision.get("analyzer_id")) for decision in analyzer_routing}
        router_to_pipeline = self._router_to_pipeline_analyzers()
        for decision in analyzer_routing:
            router_analyzer_id = str(decision.get("analyzer_id"))
            pipeline_ids = sorted(router_to_pipeline.get(router_analyzer_id, {router_analyzer_id}))
            matching_executed = [pipeline_id for pipeline_id in pipeline_ids if pipeline_id in executed_set]
            matching_failed = [pipeline_id for pipeline_id in pipeline_ids if pipeline_id in failed_set]
            recommended = str(decision.get("recommendation")) == "RECOMMENDED"
            selected = (
                router_analyzer_id in selected_router_ids
                if selected_router_ids is not None
                else bool(recommended and pipeline_ids)
            )
            status = "completed" if matching_executed else "skipped"
            reason = None
            if matching_failed:
                status = "failed"
                reason = "; ".join(f"{pipeline_id}: {failed_analyzers[pipeline_id]}" for pipeline_id in matching_failed)
            if not selected:
                selected = False
                status = "skipped"
                if recommended:
                    reason = "Recommended, but below the execution threshold or capped by max_analyzers."
                else:
                    reason = f"Router decision was {decision.get('recommendation')}."
            elif not matching_executed:
                if not matching_failed:
                    reason = "No enabled pipeline analyzer is available for this recommended router analyzer."
            snapshots.append(
                {
                    "router_analyzer_id": router_analyzer_id,
                    "display_name": decision.get("display_name") or router_analyzer_id,
                    "recommendation": decision.get("recommendation"),
                    "selected": selected,
                    "pipeline_analyzer_ids": pipeline_ids,
                    "executed_pipeline_analyzer_ids": matching_executed,
                    "failed_pipeline_analyzer_ids": matching_failed,
                    "execution_status": status,
                    "execution_reason": reason,
                }
            )
        for analyzer_id in executed_analyzers:
            router_analyzer_id = analyzer_id
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
                    "failed_pipeline_analyzer_ids": [],
                    "execution_status": "completed",
                    "execution_reason": None,
                }
            )
        for analyzer_id, error in failed_analyzers.items():
            router_analyzer_id = analyzer_id
            if router_analyzer_id in routed_ids:
                continue
            snapshots.append(
                {
                    "router_analyzer_id": router_analyzer_id,
                    "display_name": router_analyzer_id,
                    "recommendation": "UNROUTED",
                    "selected": True,
                    "pipeline_analyzer_ids": [analyzer_id],
                    "executed_pipeline_analyzer_ids": [],
                    "failed_pipeline_analyzer_ids": [analyzer_id],
                    "execution_status": "failed",
                    "execution_reason": f"{analyzer_id}: {error}",
                }
            )
        return snapshots

    @staticmethod
    def _router_to_pipeline_analyzers() -> dict[str, set[str]]:
        return {"trend_regression": {"trend"}}

    @staticmethod
    def _decision_score(decision: dict[str, object]) -> float:
        try:
            return float(decision.get("final_score") or 0.0)
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _analyzer_finding_rules(params: dict[str, object]) -> dict[str, object] | None:
        rules = params.get("finding_rules")
        if isinstance(rules, dict):
            return rules
        legacy_rule = params.get("finding_rule")
        if isinstance(legacy_rule, dict):
            return legacy_rule
        return None

    @staticmethod
    def _analyzer_implementation(params: dict[str, object]) -> dict[str, object] | None:
        implementation = params.get("implementation")
        return implementation if isinstance(implementation, dict) else None

    @staticmethod
    def _baseline_shift_params(params: dict[str, object]) -> dict[str, float | int | str]:
        ruptures_params = params.get("ruptures") if isinstance(params.get("ruptures"), dict) else {}
        finding_rules = params.get("finding_rules") if isinstance(params.get("finding_rules"), dict) else {}
        statistical_gate = params.get("statistical_gate") if isinstance(params.get("statistical_gate"), dict) else {}
        operational_significance = (
            params.get("operational_significance") if isinstance(params.get("operational_significance"), dict) else {}
        )
        return {
            "threshold_percent": float(
                finding_rules.get(  # type: ignore[union-attr]
                    "min_change_percent",
                    operational_significance.get("min_change_percent", params.get("threshold_percent", 25)),  # type: ignore[union-attr]
                )
            ),
            "min_segment_size": int(
                ruptures_params.get("min_size", params.get("min_segment_size", 5))  # type: ignore[union-attr]
            ),
            "change_threshold": float(
                finding_rules.get(  # type: ignore[union-attr]
                    "min_effect_size",
                    statistical_gate.get("min_effect_size", params.get("change_threshold", 1.5)),  # type: ignore[union-attr]
                )
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
