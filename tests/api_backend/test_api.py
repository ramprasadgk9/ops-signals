from datetime import datetime, timedelta

from fastapi.testclient import TestClient

from backend.app.main import create_app
from backend.app.models.db import get_session_local
from backend.app.models.entities import AnalysisRunEntity, NormalizedPoint, SignalEntity


def test_available_questions_and_answer_api() -> None:
    app = create_app('sqlite+pysqlite:///:memory:')
    with TestClient(app) as client:
        session_local = get_session_local()
        with session_local() as db:
            db.add(
                AnalysisRunEntity(
                    id='run-1',
                    source_type='csv',
                    service='checkout-service',
                    metric_name='cpu_usage',
                    start_time=datetime.utcnow() - timedelta(days=1),
                    end_time=datetime.utcnow(),
                    sample_count=20,
                    status='completed',
                )
            )
            db.add(
                NormalizedPoint(
                    metric_name='cpu_usage',
                    timestamp=datetime.utcnow(),
                    value=52.1,
                    service='checkout-service',
                    analysis_run_id='run-1',
                )
            )
            db.add(
                SignalEntity(
                    signal_id='sig-1',
                    signal_type='baseline_shift',
                    analyzer_id='baseline_shift',
                    metric_name='cpu_usage',
                    service='checkout-service',
                    severity='high',
                    confidence=0.91,
                    start_time=datetime.utcnow() - timedelta(hours=2),
                    end_time=datetime.utcnow() - timedelta(hours=1),
                    summary='baseline shifted',
                    evidence_json={'percent_change': 56.5},
                    importance_score=0.95,
                    status='new',
                    analysis_run_id='run-1',
                )
            )
            db.commit()

        qres = client.get('/api/questions/available', params={'service': 'checkout-service', 'metric_name': 'cpu_usage', 'analysis_run_id': 'run-1'})
        assert qres.status_code == 200
        assert any(item['id'] == 'what_changed' for item in qres.json())

        rres = client.get('/api/analysis-runs')
        assert rres.status_code == 200
        assert rres.json()[0]['provider'] == 'generic'

        ares = client.post(
            '/api/questions/answer',
            json={
                'question_id': 'what_changed',
                'service': 'checkout-service',
                'metric_name': 'cpu_usage',
                'analysis_run_id': 'run-1',
            },
        )
        assert ares.status_code == 200
        assert ares.json()['question_id'] == 'what_changed'
        assert 'headline' in ares.json()
