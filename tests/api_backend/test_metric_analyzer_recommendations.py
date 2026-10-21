from datetime import datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import event

from backend.app.main import create_app
from backend.app.models.db import get_session_local
from backend.app.models.entities import AnalysisRunEntity, NormalizedPoint
from backend.app.metric_analyzer_recommendations.service import MetricAnalyzerRecommendationService


def test_metric_analyzer_recommendations_api_returns_profile_and_ranked_analyzers() -> None:
    app = create_app('sqlite+pysqlite:///:memory:')
    with TestClient(app) as client:
        session_local = get_session_local()
        with session_local() as db:
            start = datetime.utcnow() - timedelta(hours=2)
            for index in range(60):
                db.add(
                    NormalizedPoint(
                        metric_name='memory_usage',
                        timestamp=start + timedelta(minutes=index * 2),
                        value=100 + index * 0.5,
                        service='checkout-service',
                        analysis_run_id='run-123',
                    )
                )
            db.commit()

        response = client.post(
            '/api/metric-analyzer-recommendations/evaluate',
            json={'service': 'checkout-service', 'metric_name': 'memory_usage', 'analysis_run_id': 'run-123'},
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload['sample']['metric_name'] == 'memory_usage'
        assert payload['profile']['sample_count'] == 60
        assert payload['recommendations']
        assert any(item['analyzer_id'] == 'trend' for item in payload['recommendations'])


def test_metric_analyzer_recommendations_metrics_ignores_non_finite_values() -> None:
    start = datetime.utcnow() - timedelta(hours=1)
    values = [(start, 1.0), (start + timedelta(minutes=5), 2.0), (start + timedelta(minutes=10), float('nan')), (start + timedelta(minutes=15), 3.0)]

    sample = MetricAnalyzerRecommendationService()._summarize_sample('checkout-service', 'cpu_usage', 'run-with-nan', values)

    assert sample['sample_count'] == 4
    assert sample['missing_ratio'] == 0.25
    assert sample['mean_value'] == 2.0


def test_the_sample_list_reads_runs_newest_first_and_never_the_stored_points() -> None:
    # Summarising every stored point took minutes on a real database (46M rows) and starved the
    # backend's connections; the list is one row per run from the runs table.
    app = create_app('sqlite+pysqlite:///:memory:')
    with TestClient(app) as client:
        session_local = get_session_local()
        with session_local() as db:
            now = datetime.utcnow()
            for index in range(5):
                db.add(
                    AnalysisRunEntity(
                        id=f'run-{index}', source_type='csv', service='checkout-service', metric_name='cpu_usage',
                        start_time=now - timedelta(hours=1), end_time=now, sample_count=60 if index != 2 else 0,
                        status='completed', created_at=now - timedelta(minutes=10 - index),
                    )
                )
            db.commit()

            statements: list[str] = []
            event.listen(db.get_bind(), 'before_cursor_execute', lambda *args: statements.append(args[2]))
            samples = MetricAnalyzerRecommendationService().list_samples(db, limit=3)

        assert [sample['analysis_run_id'] for sample in samples] == ['run-4', 'run-3', 'run-1']
        assert samples[0]['sample_count'] == 60 and samples[0].get('missing_ratio') is None
        assert not any('ops_normalized_timeseries_points' in statement for statement in statements)
        listed = client.get('/api/metric-analyzer-recommendations/metrics').json()
        assert listed[0]['analysis_run_id'] == 'run-4' and listed[0]['missing_ratio'] is None


def test_evaluate_without_a_run_id_uses_the_latest_run() -> None:
    # QA-15: analysis_run_id is optional, but leaving it out was always a 404 "sample not found".
    app = create_app('sqlite+pysqlite:///:memory:')
    with TestClient(app) as client:
        session_local = get_session_local()
        with session_local() as db:
            start = datetime.utcnow() - timedelta(hours=6)
            for run_id, offset, count in (('run-old', 0, 60), ('run-new', 180, 80)):
                for index in range(count):
                    db.add(
                        NormalizedPoint(
                            metric_name='memory_usage',
                            timestamp=start + timedelta(minutes=offset + index * 2),
                            value=100 + index * 0.5,
                            service='checkout-service',
                            analysis_run_id=run_id,
                        )
                    )
            db.commit()

        for path in ('/api/metric-analyzer-recommendations/evaluate', '/api/mcp/metric-analyzer-recommendations/evaluate'):
            response = client.post(path, json={'service': 'checkout-service', 'metric_name': 'memory_usage'})

            assert response.status_code == 200, path
            assert response.json()['sample']['analysis_run_id'] == 'run-new'
            # Only the latest run's points, not every run's merged together.
            assert response.json()['profile']['sample_count'] == 80

        assert client.post(
            '/api/metric-analyzer-recommendations/evaluate',
            json={'service': 'checkout-service', 'metric_name': 'memory_usage', 'analysis_run_id': 'run-old'},
        ).json()['profile']['sample_count'] == 60
        missing = client.post('/api/metric-analyzer-recommendations/evaluate', json={'service': 'checkout-service', 'metric_name': 'nope'})
        assert missing.status_code == 404
