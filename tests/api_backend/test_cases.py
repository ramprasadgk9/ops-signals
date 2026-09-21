from datetime import datetime, timedelta

from backend.app.models.db import get_session_local
from backend.app.models.entities import AnalysisRunEntity, FindingEntity, OperationalCaseEntity


def _create_finding(**overrides) -> FindingEntity:
    payload = {
        'analysis_run_id': 'run-test-1',
        'service': 'checkout-service',
        'metric_name': 'cpu_usage',
        'title': 'CPU baseline shift',
        'summary': 'CPU usage shifted above baseline',
        'category': 'baseline',
        'health_status': 'degraded',
        'importance_score': 0.9,
        'investigation_priority': 1,
        'signal_ids': ['sig-1'],
        'comparison_json': {'percent_change': 42.0},
        'created_at': datetime.utcnow(),
    }
    payload.update(overrides)
    finding = FindingEntity(**payload)
    session_local = get_session_local()
    now = datetime.utcnow()
    with session_local() as db:
        db.add(
            AnalysisRunEntity(
                id=payload['analysis_run_id'],
                source_type='prometheus',
                provider='prometheus',
                service=payload['service'],
                metric_name=payload['metric_name'],
                start_time=now - timedelta(hours=1),
                end_time=now,
                sample_count=120,
                status='completed',
                router_version='1.0',
                feature_extractor_version='1.0',
                analyzer_registry_version='1.0',
                series_profile_json={'sample_count': 120, 'shift_index': 0.82, 'regular_sampling': True},
                router_decisions_json=[
                    {
                        'analyzer_id': 'baseline_shift',
                        'eligible': True,
                        'eligibility_score': 1.0,
                        'suitability_score': 0.91,
                        'final_score': 0.91,
                        'recommendation': 'RECOMMENDED',
                    }
                ],
            )
        )
        db.add(finding)
        db.commit()
        db.refresh(finding)
        finding_id = finding.id
    return finding_id


def test_create_case_from_finding(client) -> None:
    finding_id = _create_finding()

    response = client.post(f'/api/cases/findings/{finding_id}/create')
    assert response.status_code == 200
    body = response.json()
    assert body['finding_id'] == finding_id
    assert body['case_status'] == 'open'
    assert body['memory_status'] == 'not_indexed'
    assert isinstance(body['case_id'], int)


def test_create_case_is_idempotent(client) -> None:
    finding_id = _create_finding()

    first = client.post(f'/api/cases/findings/{finding_id}/create')
    second = client.post(f'/api/cases/findings/{finding_id}/create')

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()['case_id'] == second.json()['case_id']


def test_create_case_missing_finding_returns_404(client) -> None:
    response = client.post('/api/cases/findings/99999/create')
    assert response.status_code == 404
    assert response.json()['detail'] == 'finding not found'


def test_get_case_and_lifecycle_updates(client) -> None:
    finding_id = _create_finding()
    created = client.post(f'/api/cases/findings/{finding_id}/create')
    case_id = created.json()['case_id']

    fetched = client.get(f'/api/cases/{case_id}')
    assert fetched.status_code == 200
    assert fetched.json()['case_title'] == 'CPU baseline shift'
    assert fetched.json()['investigation_status'] == 'not_started'

    investigation = client.patch(
        f'/api/cases/{case_id}/investigation',
        json={
            'investigation_status': 'in_progress',
            'investigation_note': 'Checked deploy timeline',
        },
    )
    assert investigation.status_code == 200
    assert investigation.json()['investigation_status'] == 'in_progress'
    assert len(investigation.json()['investigation_notes']) == 1
    assert investigation.json()['investigation_notes'][0]['note'] == 'Checked deploy timeline'

    rca = client.patch(
        f'/api/cases/{case_id}/rca',
        json={
            'root_cause_status': 'identified',
            'root_cause_summary': 'Bad canary rollout',
            'root_cause_confidence': 0.85,
            'root_cause_verified': False,
        },
    )
    assert rca.status_code == 200
    assert rca.json()['root_cause_summary'] == 'Bad canary rollout'
    assert rca.json()['case_status'] == 'open'

    resolution = client.patch(
        f'/api/cases/{case_id}/resolution',
        json={
            'outcome_status': 'mitigated',
            'outcome_summary': 'Rolled back canary',
            'corrective_action': 'Rollback deploy',
            'learning_outcome_status': 'confirmed',
        },
    )
    assert resolution.status_code == 200
    assert resolution.json()['corrective_action'] == 'Rollback deploy'
    assert resolution.json()['case_status'] == 'in_progress'

    verified = client.patch(
        f'/api/cases/{case_id}/rca',
        json={
            'root_cause_status': 'confirmed',
            'root_cause_summary': 'Bad canary rollout',
            'root_cause_confidence': 0.95,
            'root_cause_verified': True,
        },
    )
    assert verified.status_code == 200
    assert verified.json()['case_status'] == 'resolved'
    assert verified.json()['investigation_status'] == 'completed'


def test_get_case_not_found(client) -> None:
    response = client.get('/api/cases/99999')
    assert response.status_code == 404


def test_memory_marked_stale_after_indexed_case_update(client) -> None:
    finding_id = _create_finding()
    created = client.post(f'/api/cases/findings/{finding_id}/create')
    case_id = created.json()['case_id']

    session_local = get_session_local()
    with session_local() as db:
        case = db.get(OperationalCaseEntity, case_id)
        assert case is not None
        case.memory_status = 'indexed'
        db.commit()

    response = client.patch(
        f'/api/cases/{case_id}/rca',
        json={
            'root_cause_status': 'identified',
            'root_cause_summary': 'Updated RCA',
            'root_cause_confidence': 0.7,
            'root_cause_verified': False,
        },
    )
    assert response.status_code == 200
    assert response.json()['memory_status'] == 'stale'
