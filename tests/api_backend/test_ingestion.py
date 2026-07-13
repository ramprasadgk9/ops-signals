from datetime import datetime
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from backend.app.models.db import get_session_local
from backend.app.models.entities import FindingEntity
from ops_signals.daily_report import OperationalIntelligenceReport
from ops_signals.pipeline import PipelineResult


SAMPLE_CSV = Path(__file__).resolve().parents[2] / 'sample_data' / 'cpu_usage_sample.csv'


def _pipeline_result(analysis_run_id: str = 'run-ingest-1') -> PipelineResult:
    points = pd.DataFrame(
        {
            'timestamp': [datetime.utcnow()],
            'metric_name': ['cpu_usage'],
            'value': [55.0],
            'service': ['checkout-service'],
        }
    )
    return PipelineResult(
        normalized_points=points,
        signals=[],
        findings=[],
        report=OperationalIntelligenceReport(
            analysis_window_start=datetime.utcnow(),
            analysis_window_end=datetime.utcnow(),
            overall_health_score=100.0,
            critical_findings=0,
            significant_findings=0,
            normal_findings=0,
            metrics_analysed=1,
            answers={},
            top_findings=[],
        ),
        analysis_run_id=analysis_run_id,
    )


def test_csv_ingestion_rejects_invalid_provider(client) -> None:
    response = client.post(
        '/api/ingestion/csv-run',
        data={
            'provider': 'splunk',
            'service': 'checkout-service',
            'metric_name': 'cpu_usage',
            'interval': '5m',
        },
        files={'file': ('sample.csv', b'timestamp,metric_name,value\n', 'text/csv')},
    )
    assert response.status_code == 400
    assert 'provider must be one of' in response.json()['detail']


def test_csv_ingestion_rejects_non_csv(client) -> None:
    response = client.post(
        '/api/ingestion/csv-run',
        data={
            'provider': 'generic',
            'service': 'checkout-service',
            'metric_name': 'cpu_usage',
            'interval': '5m',
        },
        files={'file': ('notes.txt', b'not csv', 'text/plain')},
    )
    assert response.status_code == 400
    assert response.json()['detail'] == 'only .csv uploads are supported'


def test_csv_ingestion_success(client) -> None:
    analysis_run_id = 'run-ingest-success'
    result = _pipeline_result(analysis_run_id)

    with patch('backend.app.api.ingestion.SignalPipeline') as pipeline_cls:
        pipeline_cls.return_value.run.return_value = result

        csv_bytes = SAMPLE_CSV.read_bytes()
        response = client.post(
            '/api/ingestion/csv-run',
            data={
                'provider': 'generic',
                'service': 'checkout-service',
                'metric_name': 'cpu_usage',
                'interval': '5m',
            },
            files={'file': ('cpu_usage_sample.csv', BytesIO(csv_bytes), 'text/csv')},
        )

    assert response.status_code == 200
    body = response.json()
    assert body['analysis_run_id'] == analysis_run_id
    assert body['provider'] == 'generic'
    assert body['source_type'] == 'csv'
    assert body['service'] == 'checkout-service'
    assert body['metric_name'] == 'cpu_usage'
    assert body['sample_count'] == 1
    assert body['findings_count'] == 0
    pipeline_cls.assert_called_once()
    pipeline_cls.return_value.run.assert_called_once()


def test_csv_ingestion_counts_persisted_findings(client) -> None:
    analysis_run_id = 'run-ingest-findings'
    result = _pipeline_result(analysis_run_id)

    session_local = get_session_local()
    with session_local() as db:
        db.add(
            FindingEntity(
                analysis_run_id=analysis_run_id,
                service='checkout-service',
                metric_name='cpu_usage',
                title='Ingested finding',
                summary='Created by ingestion test',
                category='baseline',
                health_status='degraded',
                importance_score=0.7,
                investigation_priority=2,
                signal_ids=['sig-i1'],
                comparison_json={},
                created_at=datetime.utcnow(),
            )
        )
        db.commit()

    with patch('backend.app.api.ingestion.SignalPipeline') as pipeline_cls:
        pipeline_cls.return_value.run.return_value = result
        response = client.post(
            '/api/ingestion/csv-run',
            data={
                'provider': 'prometheus',
                'service': 'checkout-service',
                'metric_name': 'cpu_usage',
                'interval': '5m',
            },
            files={'file': ('sample.csv', b'timestamp,metric,value\n', 'text/csv')},
        )

    assert response.status_code == 200
    assert response.json()['findings_count'] == 1
    assert response.json()['provider'] == 'prometheus'
