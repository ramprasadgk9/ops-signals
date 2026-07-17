from datetime import datetime, timedelta

from fastapi.testclient import TestClient

from backend.app.main import create_app
from backend.app.models.db import get_session_local
from backend.app.models.entities import NormalizedPoint


def test_metric_analyzer_chat_returns_preliminary_recommendation_without_sample() -> None:
    app = create_app('sqlite+pysqlite:///:memory:')
    with TestClient(app) as client:
        response = client.post(
            '/api/metric-analyzer-recommendations/chat',
            json={
                'message': 'Give me matching analyzers for this metric.',
                'metric_context': {
                    'metric_name': 'container_memory_usage_bytes',
                    'metric_description': 'Current memory consumed by a Kubernetes container.',
                    'metric_type': 'gauge',
                    'provider': 'prometheus',
                    'unit': 'bytes',
                    'operational_purpose': 'Monitor container memory health and identify memory growth before OOMKill events.',
                    'use_cases': ['Detect gradual trend', 'Detect baseline changes'],
                    'operational_questions': ['Is memory gradually increasing?'],
                    'example_values': [],
                    'additional_notes': 'Memory should drop after batch processing.',
                },
                'options': {'include_vector_discovery': True, 'run_sample_evaluation': True, 'requested_analyzers': None},
            },
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload['recommendation_mode'] == 'preliminary'
        assert payload['assistant_message']['headline']
        assert payload['normalized_goals']


def test_metric_analyzer_chat_returns_evaluated_recommendation_with_sample() -> None:
    app = create_app('sqlite+pysqlite:///:memory:')
    with TestClient(app) as client:
        session_local = get_session_local()
        with session_local() as db:
            start = datetime.utcnow() - timedelta(hours=2)
            for index in range(60):
                db.add(
                    NormalizedPoint(
                        metric_name='container_memory_usage_bytes',
                        timestamp=start + timedelta(minutes=index * 2),
                        value=100 + index * 0.5,
                        service='prometheus',
                        analysis_run_id='run-123',
                    )
                )
            db.commit()

        response = client.post(
            '/api/metric-analyzer-recommendations/chat',
            json={
                'message': 'Give me matching analyzers for this metric.',
                'metric_context': {
                    'sample_id': 1,
                    'metric_name': 'container_memory_usage_bytes',
                    'metric_description': 'Current memory consumed by a Kubernetes container.',
                    'metric_type': 'gauge',
                    'provider': 'prometheus',
                    'unit': 'bytes',
                    'operational_purpose': 'Monitor container memory health and identify memory growth before OOMKill events.',
                    'use_cases': ['Detect gradual trend', 'Detect baseline changes'],
                    'operational_questions': ['Is memory gradually increasing?'],
                    'example_values': [],
                    'additional_notes': 'Memory should drop after batch processing.',
                },
                'options': {'include_vector_discovery': True, 'run_sample_evaluation': True, 'requested_analyzers': None},
            },
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload['recommendation_mode'] == 'evaluated'
        assert payload['recommendations']

