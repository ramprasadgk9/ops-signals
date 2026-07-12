from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from backend.app.models.entities import CapabilityEntity, SignalEntity
from backend.app.questions.router import QuestionRouter


def test_question_router_selects_supported_analyzers(db_session: Session) -> None:
    db_session.add(
        CapabilityEntity(
            id='baseline_analysis',
            analyzer_id='baseline_shift',
            title='Baseline Analysis',
            description='desc',
            enabled=True,
            metadata_json={'supported_question_ids': ['what_changed']},
        )
    )
    db_session.add(
        SignalEntity(
            signal_id='sig-1',
            signal_type='baseline_shift',
            analyzer_id='baseline_shift',
            metric_name='cpu_usage',
            service='checkout-service',
            severity='high',
            confidence=0.9,
            start_time=datetime.utcnow() - timedelta(hours=1),
            end_time=datetime.utcnow(),
            summary='baseline shifted',
            evidence_json={},
            importance_score=0.9,
            status='new',
            analysis_run_id='run-1',
        )
    )
    db_session.commit()

    routed = QuestionRouter(db_session).route('what_changed', 'checkout-service', 'cpu_usage', 'run-1')
    assert routed.analyzer_ids == ['baseline_shift']
    assert len(routed.signals) == 1
