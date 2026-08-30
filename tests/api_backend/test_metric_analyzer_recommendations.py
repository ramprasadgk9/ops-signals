from datetime import datetime, timedelta

from fastapi.testclient import TestClient

from backend.app.main import create_app
from backend.app.models.db import get_session_local
from backend.app.models.entities import NormalizedPoint
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

    class _Result:
        def all(self):
            return [
                ('checkout-service', 'cpu_usage', 'run-with-nan', start, 1.0),
                ('checkout-service', 'cpu_usage', 'run-with-nan', start + timedelta(minutes=5), 2.0),
                ('checkout-service', 'cpu_usage', 'run-with-nan', start + timedelta(minutes=10), float('nan')),
                ('checkout-service', 'cpu_usage', 'run-with-nan', start + timedelta(minutes=15), 3.0),
            ]

    class _Db:
        def execute(self, _query):
            return _Result()

    samples = MetricAnalyzerRecommendationService().list_samples(_Db())

    assert samples[0]['sample_count'] == 4
    assert samples[0]['missing_ratio'] == 0.25
    assert samples[0]['mean_value'] == 2.0
