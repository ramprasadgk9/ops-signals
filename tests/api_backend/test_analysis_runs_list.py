from datetime import datetime, timedelta

from fastapi.testclient import TestClient

from backend.app.main import create_app
from backend.app.models.db import get_session_local
from backend.app.models.entities import AnalysisRunEntity


def _add_runs(runs: list[tuple[str, str, str, int]]) -> None:
    now = datetime.utcnow()
    with get_session_local()() as db:
        for run_id, service, metric, minutes_ago in runs:
            db.add(
                AnalysisRunEntity(
                    id=run_id,
                    source_type='prometheus',
                    service=service,
                    metric_name=metric,
                    start_time=now - timedelta(hours=1),
                    end_time=now,
                    sample_count=10,
                    status='completed',
                    created_at=now - timedelta(minutes=minutes_ago),
                )
            )
        db.commit()


RUNS = [
    ('run-old', 'checkout', 'cpu_usage', 30),
    ('run-mid', 'payments', 'latency_p95', 20),
    ('run-new', 'checkout', 'latency_p95', 10),
    ('run-newest', 'checkout', 'cpu_usage', 1),
]


def test_analysis_runs_lists_all_runs_newest_first_by_default() -> None:
    app = create_app('sqlite+pysqlite:///:memory:')
    with TestClient(app) as client:
        _add_runs(RUNS)
        res = client.get('/api/analysis-runs')
    assert res.status_code == 200
    assert [run['id'] for run in res.json()] == ['run-newest', 'run-new', 'run-mid', 'run-old']


def test_analysis_runs_limit_returns_only_the_newest() -> None:
    app = create_app('sqlite+pysqlite:///:memory:')
    with TestClient(app) as client:
        _add_runs(RUNS)
        res = client.get('/api/analysis-runs', params={'limit': 2})
    assert [run['id'] for run in res.json()] == ['run-newest', 'run-new']


def test_analysis_runs_filters_by_service_and_metric() -> None:
    app = create_app('sqlite+pysqlite:///:memory:')
    with TestClient(app) as client:
        _add_runs(RUNS)
        latest = client.get('/api/analysis-runs', params={'service': 'checkout', 'metric_name': 'cpu_usage', 'limit': 1})
        by_service = client.get('/api/analysis-runs', params={'service': 'checkout'})
    assert [run['id'] for run in latest.json()] == ['run-newest']
    assert [run['id'] for run in by_service.json()] == ['run-newest', 'run-new', 'run-old']


def test_analysis_runs_rejects_an_out_of_range_limit() -> None:
    app = create_app('sqlite+pysqlite:///:memory:')
    with TestClient(app) as client:
        assert client.get('/api/analysis-runs', params={'limit': 0}).status_code == 422
        assert client.get('/api/analysis-runs', params={'limit': 1001}).status_code == 422
