from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models.entities import (
    AnalysisRunEntity,
    AnalyzerLearningOutcomeEntity,
    FindingEntity,
    OperationalCaseEntity,
    SignalEntity,
)

VALID_LEARNING_OUTCOMES = {"confirmed", "partially_confirmed", "rejected", "inconclusive"}


class LearningOutcomeError(ValueError):
    pass


class AnalyzerLearningService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def create_from_case_resolution(
        self,
        case_id: int,
        outcome_status: str,
        outcome_summary: str | None = None,
        root_cause_category: str | None = None,
        resolution_summary: str | None = None,
        resolved_by: str | None = None,
    ) -> AnalyzerLearningOutcomeEntity:
        if outcome_status not in VALID_LEARNING_OUTCOMES:
            raise LearningOutcomeError(f"Invalid learning outcome status: {outcome_status}")

        case = self.db.execute(
            select(OperationalCaseEntity).where(OperationalCaseEntity.id == case_id)
        ).scalar_one_or_none()
        if case is None:
            raise LearningOutcomeError("case not found")

        if case.outcome_status not in {"resolved", "mitigated", "won_t_fix"}:
            raise LearningOutcomeError("case is not in a final resolution state")

        existing = self.db.execute(
            select(AnalyzerLearningOutcomeEntity).where(
                AnalyzerLearningOutcomeEntity.case_id == case.id,
                AnalyzerLearningOutcomeEntity.finding_id == case.finding_id,
            )
        ).scalar_one_or_none()
        if existing is not None:
            raise LearningOutcomeError("learning outcome already exists for this case and finding")

        analysis_run = self.db.execute(
            select(AnalysisRunEntity).where(AnalysisRunEntity.id == case.analysis_run_id)
        ).scalar_one_or_none()
        if analysis_run is None:
            raise LearningOutcomeError("analysis run not found")
        if not analysis_run.series_profile_json or not analysis_run.router_decisions_json:
            raise LearningOutcomeError("analysis run is missing router learning snapshots")

        finding = self.db.execute(
            select(FindingEntity).where(FindingEntity.id == case.finding_id)
        ).scalar_one_or_none()
        source_analyzers = self._source_analyzers(finding)
        confirmed, rejected = self._classify_analyzers(outcome_status, source_analyzers)

        resolved_at = datetime.utcnow()
        case.resolved_at = case.resolved_at or resolved_at

        record = AnalyzerLearningOutcomeEntity(
            id=uuid4().hex,
            organization_id=None,
            service_id=case.finding_snapshot.get("service") if case.finding_snapshot else None,
            metric_name=case.finding_snapshot.get("metric_name") if case.finding_snapshot else analysis_run.metric_name,
            analysis_run_id=analysis_run.id,
            finding_id=case.finding_id,
            case_id=case.id,
            router_version=analysis_run.router_version,
            feature_extractor_version=analysis_run.feature_extractor_version,
            analyzer_registry_version=analysis_run.analyzer_registry_version,
            series_profile=analysis_run.series_profile_json or {},
            router_decisions=analysis_run.router_decisions_json or [],
            executed_analyzers=analysis_run.executed_analyzers_json or [],
            generated_findings=analysis_run.generated_findings_json or [],
            outcome_status=outcome_status,
            outcome_summary=outcome_summary,
            root_cause_category=root_cause_category,
            resolution_summary=resolution_summary,
            confirmed_analyzers=confirmed,
            rejected_analyzers=rejected,
            resolved_by=resolved_by,
            resolved_at=case.resolved_at,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        self.db.add(record)
        self.db.flush()
        return record

    def _source_analyzers(self, finding: FindingEntity | None) -> list[str]:
        if finding is None or not finding.signal_ids:
            return []
        signals = self.db.execute(
            select(SignalEntity).where(SignalEntity.signal_id.in_(finding.signal_ids))
        ).scalars().all()
        analyzers = sorted({signal.analyzer_id for signal in signals if signal.analyzer_id})
        return [str(analyzer) for analyzer in analyzers]

    @staticmethod
    def _classify_analyzers(outcome_status: str, source_analyzers: list[str]) -> tuple[list[str], list[str]]:
        if outcome_status in {"confirmed", "partially_confirmed"}:
            return source_analyzers, []
        if outcome_status == "rejected":
            return [], source_analyzers
        return [], []

