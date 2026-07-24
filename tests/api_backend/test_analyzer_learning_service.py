from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from sqlalchemy.orm import Session

from backend.app.models.entities import (
    AnalysisRunEntity,
    AnalyzerLearningOutcomeEntity,
    FindingEntity,
    OperationalCaseEntity,
    SignalEntity,
)
from backend.app.services.analyzer_learning_service import AnalyzerLearningService, LearningOutcomeError


def _seed_case(db: Session, *, outcome_status: str = "resolved") -> OperationalCaseEntity:
    now = datetime.utcnow()
    db.add(
        AnalysisRunEntity(
            id="run-1",
            source_type="prometheus",
            provider="prometheus",
            service="ruptures-lab",
            metric_name="cpu_usage",
            start_time=now - timedelta(hours=1),
            end_time=now,
            sample_count=120,
            status="completed",
            router_version="1.0",
            feature_extractor_version="1.0",
            analyzer_registry_version="1.0",
            series_profile_json={"sample_count": 120, "shift_index": 0.82, "regular_sampling": True},
            router_decisions_json=[
                {
                    "analyzer_id": "ruptures",
                    "eligible": True,
                    "eligibility_score": 1.0,
                    "suitability_score": 0.91,
                    "final_score": 0.91,
                    "recommendation": "RECOMMENDED",
                }
            ],
            executed_analyzers_json=[
                {
                    "router_analyzer_id": "ruptures",
                    "pipeline_analyzer_id": "ruptures",
                    "execution_status": "completed",
                },
                {
                    "router_analyzer_id": "ruptures",
                    "pipeline_analyzer_id": "baseline_shift",
                    "execution_status": "completed",
                },
            ],
            generated_findings_json=[{"id": 1, "title": "CPU baseline changed"}],
        )
    )
    finding = FindingEntity(
        analysis_run_id="run-1",
        service="ruptures-lab",
        metric_name="cpu_usage",
        title="CPU baseline changed",
        summary="CPU baseline decreased by approximately 35%.",
        category="operational_insight",
        health_status="significant",
        importance_score=0.91,
        investigation_priority=1,
        signal_ids=["sig-ruptures", "sig-baseline"],
        comparison_json={},
    )
    db.add(finding)
    db.flush()
    db.add_all(
        [
            SignalEntity(
                signal_id="sig-ruptures",
                signal_type="change_point",
                analyzer_id="ruptures",
                metric_name="cpu_usage",
                service="ruptures-lab",
                severity="medium",
                confidence=0.91,
                start_time=now - timedelta(minutes=30),
                end_time=now,
                summary="change point detected",
                evidence_json={},
                importance_score=0.91,
                status="new",
                analysis_run_id="run-1",
            ),
            SignalEntity(
                signal_id="sig-baseline",
                signal_type="baseline_shift",
                analyzer_id="baseline_shift",
                metric_name="cpu_usage",
                service="ruptures-lab",
                severity="medium",
                confidence=0.88,
                start_time=now - timedelta(minutes=30),
                end_time=now,
                summary="baseline shifted",
                evidence_json={},
                importance_score=0.88,
                status="new",
                analysis_run_id="run-1",
            ),
        ]
    )
    case = OperationalCaseEntity(
        finding_id=finding.id,
        analysis_run_id="run-1",
        case_title=finding.title,
        case_status="open",
        finding_snapshot={"service": "ruptures-lab", "metric_name": "cpu_usage", "summary": finding.summary},
        investigation_status="completed",
        investigation_notes=[],
        root_cause_status="confirmed",
        root_cause_summary="Deployment changed CPU baseline.",
        root_cause_confidence=0.9,
        root_cause_verified=True,
        corrective_action="Documented expected baseline.",
        outcome_status=outcome_status,
        outcome_summary="Resolved locally.",
    )
    db.add(case)
    db.commit()
    db.refresh(case)
    return case


def test_confirmed_finding_creates_learning_outcome(db_session: Session) -> None:
    case = _seed_case(db_session)

    outcome = AnalyzerLearningService(db_session).create_from_case_resolution(
        case_id=case.id,
        outcome_status="confirmed",
        outcome_summary="The finding matched the incident.",
        root_cause_category="deployment_change",
        resolution_summary="Deployment changed resource allocation.",
    )
    db_session.commit()

    assert outcome.outcome_status == "confirmed"
    assert outcome.series_profile["shift_index"] == 0.82
    assert outcome.router_decisions[0]["analyzer_id"] == "ruptures"
    assert outcome.executed_analyzers[0]["pipeline_analyzer_id"] == "ruptures"
    assert outcome.confirmed_analyzers == ["baseline_shift", "ruptures"]
    assert outcome.rejected_analyzers == []
    assert outcome.analyzer_registry_version == "1.0"


def test_rejected_finding_records_source_analyzers_as_rejected(db_session: Session) -> None:
    case = _seed_case(db_session)

    outcome = AnalyzerLearningService(db_session).create_from_case_resolution(
        case_id=case.id,
        outcome_status="rejected",
    )

    assert outcome.confirmed_analyzers == []
    assert outcome.rejected_analyzers == ["baseline_shift", "ruptures"]


def test_inconclusive_finding_does_not_assume_analyzer_result(db_session: Session) -> None:
    case = _seed_case(db_session)

    outcome = AnalyzerLearningService(db_session).create_from_case_resolution(
        case_id=case.id,
        outcome_status="inconclusive",
    )

    assert outcome.confirmed_analyzers == []
    assert outcome.rejected_analyzers == []


def test_duplicate_learning_outcome_is_prevented(db_session: Session) -> None:
    case = _seed_case(db_session)
    service = AnalyzerLearningService(db_session)
    service.create_from_case_resolution(case_id=case.id, outcome_status="confirmed")
    db_session.commit()

    with pytest.raises(LearningOutcomeError, match="already exists"):
        service.create_from_case_resolution(case_id=case.id, outcome_status="confirmed")


def test_case_not_in_final_state_is_rejected(db_session: Session) -> None:
    case = _seed_case(db_session, outcome_status="pending")

    with pytest.raises(LearningOutcomeError, match="not in a final"):
        AnalyzerLearningService(db_session).create_from_case_resolution(
            case_id=case.id,
            outcome_status="confirmed",
        )


def test_missing_router_snapshot_is_rejected(db_session: Session) -> None:
    case = _seed_case(db_session)
    run = db_session.get(AnalysisRunEntity, "run-1")
    assert run is not None
    run.series_profile_json = None
    db_session.add(run)
    db_session.commit()

    with pytest.raises(LearningOutcomeError, match="missing router learning snapshots"):
        AnalyzerLearningService(db_session).create_from_case_resolution(
            case_id=case.id,
            outcome_status="confirmed",
        )


def test_learning_record_is_persisted(db_session: Session) -> None:
    case = _seed_case(db_session)
    outcome = AnalyzerLearningService(db_session).create_from_case_resolution(
        case_id=case.id,
        outcome_status="partially_confirmed",
    )
    db_session.commit()

    stored = db_session.get(AnalyzerLearningOutcomeEntity, outcome.id)
    assert stored is not None
    assert stored.outcome_status == "partially_confirmed"
    assert stored.confirmed_analyzers == ["baseline_shift", "ruptures"]

