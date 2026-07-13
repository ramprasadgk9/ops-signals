from datetime import datetime
from unittest.mock import MagicMock, patch

from backend.app.api import memory as memory_module
from backend.app.config import MemoryConfig, VectorStoreConfig, EmbeddingConfig
from backend.app.main import create_app
from backend.app.memory.schemas import MemoryIndexResponse, SimilarCaseMatch, SimilarCasesResponse
from backend.app.models.db import get_session_local
from backend.app.models.entities import FindingEntity, OperationalCaseEntity
from fastapi.testclient import TestClient


def _seed_case() -> int:
    session_local = get_session_local()
    with session_local() as db:
        finding = FindingEntity(
            analysis_run_id='run-mem-1',
            service='checkout-service',
            metric_name='cpu_usage',
            title='Memory test finding',
            summary='Finding used for memory API tests',
            category='baseline',
            health_status='degraded',
            importance_score=0.8,
            investigation_priority=2,
            signal_ids=['sig-m1'],
            comparison_json={},
            created_at=datetime.utcnow(),
        )
        db.add(finding)
        db.commit()
        db.refresh(finding)

        case = OperationalCaseEntity(
            finding_id=finding.id,
            analysis_run_id='run-mem-1',
            case_title=finding.title,
            case_status='open',
            finding_snapshot={
                'id': finding.id,
                'service': finding.service,
                'metric_name': finding.metric_name,
                'title': finding.title,
                'category': finding.category,
            },
            investigation_status='not_started',
            investigation_notes=[],
            root_cause_status='unknown',
            root_cause_verified=False,
            outcome_status='pending',
            memory_status='not_indexed',
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        db.add(case)
        db.commit()
        db.refresh(case)
        return case.id


def _enabled_config() -> MemoryConfig:
    return MemoryConfig(
        enabled=True,
        vector_store=VectorStoreConfig(collection_name='operational_cases'),
        embedding=EmbeddingConfig(model='sentence-transformers/all-MiniLM-L6-v2', dimension=384),
    )


def test_memory_health_disabled(client) -> None:
    response = client.get('/api/memory/health')
    assert response.status_code == 200
    body = response.json()
    assert body['enabled'] is False
    assert body['status'] == 'disabled'


def test_memory_status_and_disabled_index(client) -> None:
    case_id = _seed_case()

    status = client.get(f'/api/cases/{case_id}/memory/status')
    assert status.status_code == 200
    assert status.json() == {
        'case_id': case_id,
        'memory_status': 'not_indexed',
        'memory_indexed_at': None,
        'memory_content_version': None,
        'memory_error': None,
    }

    index = client.post(f'/api/cases/{case_id}/memory/index')
    assert index.status_code == 400
    assert index.json()['detail'] == 'Operational Memory is not enabled'

    delete = client.delete(f'/api/cases/{case_id}/memory')
    assert delete.status_code == 400

    similar = client.get(f'/api/cases/{case_id}/similar')
    assert similar.status_code == 400


def test_memory_index_delete_and_similar_with_mocks() -> None:
    config = _enabled_config()
    indexer = MagicMock()
    similarity = MagicMock()
    store = MagicMock()
    store.health.return_value = {'status': 'healthy'}

    indexed_at = datetime.utcnow()
    indexer.index_case.return_value = MemoryIndexResponse(
        case_id=1,
        memory_status='indexed',
        collection='operational_cases',
        embedding_model='sentence-transformers/all-MiniLM-L6-v2',
        content_version=1,
        indexed_at=indexed_at,
    )
    similarity.find_similar_cases.return_value = SimilarCasesResponse(
        source_case_id=1,
        matches=[
            SimilarCaseMatch(
                case_id=2,
                similarity_score=0.91,
                title='Prior CPU incident',
                service='checkout-service',
                metric_name='cpu_usage',
                category='baseline',
                case_status='resolved',
                investigation_status='completed',
                rca_verified=True,
                root_cause_summary='Deploy regression',
                corrective_action='Rollback',
                outcome_status='resolved',
                outcome_summary='Recovered',
            )
        ],
    )

    with patch('backend.app.main.load_memory_config', return_value=config):
        with patch('backend.app.main.initialize_memory_services', return_value=(store, indexer, similarity)):
            app = create_app('sqlite+pysqlite:///:memory:')
            with TestClient(app) as client:
                case_id = _seed_case()

                # Ensure dependency injection sees the mocked services
                memory_module._services['indexer'] = indexer
                memory_module._services['similarity_service'] = similarity
                memory_module._services['config'] = config
                memory_module._services['vector_store'] = store

                def _index_side_effect(case, db):
                    case.memory_status = 'indexed'
                    case.memory_indexed_at = indexed_at
                    case.memory_content_version = 1
                    db.commit()
                    return MemoryIndexResponse(
                        case_id=case.id,
                        memory_status='indexed',
                        collection='operational_cases',
                        embedding_model='sentence-transformers/all-MiniLM-L6-v2',
                        content_version=1,
                        indexed_at=indexed_at,
                    )

                def _delete_side_effect(case, db):
                    case.memory_status = 'not_indexed'
                    case.memory_indexed_at = None
                    db.commit()

                indexer.index_case.side_effect = _index_side_effect
                indexer.delete_memory.side_effect = _delete_side_effect

                health = client.get('/api/memory/health')
                assert health.status_code == 200
                assert health.json()['enabled'] is True
                assert health.json()['status'] == 'healthy'

                indexed = client.post(f'/api/cases/{case_id}/memory/index')
                assert indexed.status_code == 200
                assert indexed.json()['memory_status'] == 'indexed'
                assert indexed.json()['case_id'] == case_id
                indexer.index_case.assert_called_once()

                status = client.get(f'/api/cases/{case_id}/memory/status')
                assert status.json()['memory_status'] == 'indexed'

                similar = client.get(f'/api/cases/{case_id}/similar', params={'top_k': 3})
                assert similar.status_code == 200
                assert similar.json()['matches'][0]['similarity_score'] == 0.91
                similarity.find_similar_cases.assert_called_once()

                deleted = client.delete(f'/api/cases/{case_id}/memory')
                assert deleted.status_code == 200
                assert deleted.json()['status'] == 'deleted'
                assert deleted.json()['memory_status'] == 'not_indexed'


def test_memory_status_missing_case(client) -> None:
    response = client.get('/api/cases/99999/memory/status')
    assert response.status_code == 404
