from datetime import datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient

from backend.app.main import create_app
from backend.app.models.db import get_session_local
from backend.app.models.entities import AnalysisRunEntity, FindingEntity, NormalizedPoint, SignalEntity


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


def test_findings_window_filter_matches_overview_window() -> None:
    app = create_app('sqlite+pysqlite:///:memory:')
    now = datetime.utcnow()
    with TestClient(app) as client:
        session_local = get_session_local()
        with session_local() as db:
            db.add_all(
                [
                    FindingEntity(
                        id=1,
                        analysis_run_id='run-recent',
                        service='checkout',
                        metric_name='cpu_usage',
                        title='Recent finding',
                        summary='recent',
                        category='behavior_change',
                        health_status='critical',
                        importance_score=0.9,
                        investigation_priority=1,
                        signal_ids=[],
                        comparison_json={},
                        created_at=now - timedelta(hours=2),
                    ),
                    FindingEntity(
                        id=2,
                        analysis_run_id='run-old',
                        service='checkout',
                        metric_name='cpu_usage',
                        title='Old finding',
                        summary='old',
                        category='trend',
                        health_status='low',
                        importance_score=0.8,
                        investigation_priority=3,
                        signal_ids=[],
                        comparison_json={},
                        created_at=now - timedelta(days=3),
                    ),
                ]
            )
            db.commit()

        res = client.get('/api/findings', params={'window': '24h'})

    assert res.status_code == 200
    payload = res.json()
    assert [item['title'] for item in payload] == ['Recent finding']


def test_csv_validation_uses_router_pipeline() -> None:
    app = create_app('sqlite+pysqlite:///:memory:')
    dataset_path = Path(__file__).resolve().parents[2] / 'benchmark' / 'scenarios' / 'cpu_pure_baseline_shift_v1' / 'dataset.csv'

    with TestClient(app) as client:
        with dataset_path.open('rb') as handle:
            res = client.post(
                '/api/ingestion/csv-validate',
                data={
                    'provider': 'prometheus',
                    'analyzer_id': 'all',
                    'service': 'benchmark-cpu',
                    'metric_name': 'cpu.usage_user',
                    'interval': '5m',
                },
                files={'file': ('dataset.csv', handle, 'text/csv')},
            )

    assert res.status_code == 200
    payload = res.json()
    assert payload['analyzer_id'] == 'router'
    assert payload['analyzer_selection_mode'] == 'recommended_threshold'
    assert payload['analyzer_routing']
    assert payload['executed_analyzers']
    assert any(decision['analyzer_id'] == 'ruptures' for decision in payload['analyzer_routing'])
