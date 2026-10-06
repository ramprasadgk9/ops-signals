"""Hybrid recall (meaning + keywords) and the recall ranking boosts, against in-memory Qdrant.

Vectors here are synthetic so each test controls similarity exactly: points that share a vector are
equally similar, and the only thing that can separate them is what's under test - a keyword match,
the same service, a verified root cause, or recency. test_memory_recall.py covers the same paths
with the real embedder."""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, Modifier, SparseVectorParams, VectorParams

from backend.app.config import MemoryConfig, VectorStoreConfig
from backend.app.memory.indexer import CaseMemoryIndexer
from backend.app.memory.qdrant_initializer import QdrantInitializer
from backend.app.memory.recall_scoring import MAX_TOTAL_BONUS, RecallBoost
from backend.app.memory.sparse_encoder import TEXT_VECTOR, document_vector, query_vector, tokenize
from backend.app.memory.vector_names import FULL_VECTOR, RESOLUTION_VECTOR, SYMPTOM_VECTOR
from backend.app.memory.vector_store import QdrantVectorStore
from tests.api_backend.test_memory_recall import _add_case

NOW = datetime(2026, 10, 6, tzinfo=timezone.utc)
DIM = QdrantInitializer.VECTOR_SIZE


def _vector(*weights: float) -> list[float]:
    """A unit vector whose first components are `weights`; the cosine of two of these is their dot."""
    raw = list(weights) + [0.0] * (DIM - len(weights))
    norm = math.sqrt(sum(value * value for value in raw))
    return [value / norm for value in raw]


QUERY = _vector(1.0)
CLOSE = _vector(0.9, math.sqrt(1 - 0.81))  # cosine 0.90 with QUERY
LOOSE = _vector(0.6, 0.8)                  # cosine 0.60
FAR = _vector(0.2, math.sqrt(1 - 0.04))    # cosine 0.20


@pytest.fixture()
def store() -> QdrantVectorStore:
    client = QdrantClient(":memory:")
    assert QdrantInitializer.initialize(client)["status"] == "ready"
    return QdrantVectorStore(client, QdrantInitializer.COLLECTION_NAME)


def _put(store, case_id: int, vector, *, text: str = "", service: str | None = None,
         verified: bool = False, created_at: datetime | None = NOW) -> None:
    payload = {
        "case_id": case_id,
        "service": service,
        "service_key": service.lower() if service else None,
        "rca_verified": verified,
    }
    if created_at:
        payload["created_at"] = created_at.isoformat()
    store.upsert(str(uuid4()), vector, payload, text=text)


def _ids(results) -> list[int]:
    return [result["payload"]["case_id"] for result in results]


# --- keyword vectors ---------------------------------------------------------------------------

def test_tokens_keep_ops_compounds_whole_and_split():
    tokens = tokenize("checkout-api OOMKilled on v2.3; http_requests_errors_total 5xx at p95 of the pods")

    assert {"checkout-api", "checkout", "api", "oomkilled", "v2.3", "http_requests_errors_total",
            "errors", "5xx", "p95", "pods"} <= set(tokens)
    assert not {"on", "the", "of", "at"} & set(tokens)


def test_keyword_vectors_are_stable_and_saturate_repeats():
    once = document_vector("pool exhausted")
    assert once == document_vector("pool exhausted")
    assert query_vector("") is None and document_vector("the of and") is None

    repeated = document_vector("pool " * 10 + "exhausted")
    weight = dict(zip(repeated.indices, repeated.values))
    pool, exhausted = query_vector("pool").indices[0], query_vector("exhausted").indices[0]
    # BM25 saturation: ten mentions count for more than one, but far less than ten times as much.
    assert weight[exhausted] < weight[pool] < 3 * weight[exhausted]


# --- hybrid ranking ----------------------------------------------------------------------------

def test_a_keyword_match_breaks_a_tie_in_meaning(store):
    _put(store, 1, CLOSE, text="checkout-api latency rose after a deploy")
    _put(store, 2, CLOSE, text="checkout-api pods OOMKilled and restarting")

    results = store.search(QUERY, text="checkout-api OOMKilled", limit=2)

    assert _ids(results) == [2, 1]
    # The score people see is still plain similarity, identical for both.
    assert [round(result["score"], 3) for result in results] == [0.9, 0.9]


def test_a_keyword_only_match_below_the_similarity_floor_is_not_added(store):
    _put(store, 1, CLOSE, text="latency rose after a deploy")
    _put(store, 2, FAR, text="checkout-api OOMKilled")

    results = store.search(QUERY, text="checkout-api OOMKilled", limit=5, score_threshold=0.4)

    assert _ids(results) == [1]


def test_plain_search_is_unchanged_without_text_or_boost(store):
    _put(store, 1, LOOSE, text="checkout-api OOMKilled")
    _put(store, 2, CLOSE, text="something else")

    results = store.search(QUERY, limit=5, score_threshold=0.5)

    assert _ids(results) == [2, 1]
    assert "rank_score" not in results[0]


# --- ranking boosts ----------------------------------------------------------------------------

def test_same_service_ranks_ahead_of_an_equally_similar_case_elsewhere(store):
    _put(store, 1, CLOSE, service="payments-api")
    _put(store, 2, CLOSE, service="checkout-api")

    results = store.search(QUERY, limit=2, boost=RecallBoost(service="Checkout-API", now=NOW))

    assert _ids(results) == [2, 1]


def test_a_verified_root_cause_ranks_ahead_of_an_unverified_one(store):
    _put(store, 1, CLOSE, verified=False)
    _put(store, 2, CLOSE, verified=True)

    assert _ids(store.search(QUERY, limit=2, boost=RecallBoost(now=NOW))) == [2, 1]


def test_recent_ranks_ahead_of_old_and_old_is_still_recalled(store):
    _put(store, 1, CLOSE, created_at=NOW - timedelta(days=720))
    _put(store, 2, CLOSE, created_at=NOW - timedelta(days=20))

    results = store.search(QUERY, limit=2, score_threshold=0.5, boost=RecallBoost(now=NOW))

    assert _ids(results) == [2, 1]


def test_all_bonuses_together_never_beat_a_clearly_more_similar_case(store):
    # The weaker case gets every bonus - exact keywords, same service, verified, from today; the
    # better one gets none. A 0.30 similarity gap is more than all the bonuses are worth.
    assert MAX_TOTAL_BONUS <= 0.25
    _put(store, 1, LOOSE, text="checkout-api OOMKilled", service="checkout-api", verified=True, created_at=NOW)
    _put(store, 2, CLOSE, text="memory pressure", service="payments-api", created_at=NOW - timedelta(days=1500))

    results = store.search(QUERY, text="checkout-api OOMKilled", limit=2,
                           boost=RecallBoost(service="checkout-api", now=NOW))

    assert _ids(results) == [2, 1]


def test_points_without_created_at_still_rank(store):
    _put(store, 1, CLOSE, created_at=None)

    assert _ids(store.search(QUERY, limit=1, boost=RecallBoost(now=NOW))) == [1]


def test_a_malformed_payload_falls_back_to_plain_similarity(store):
    # created_at: null fails Qdrant's recency term for the whole query; recall must survive it.
    store.upsert(str(uuid4()), LOOSE, {"case_id": 1, "created_at": None})
    _put(store, 2, CLOSE)

    results = store.search(QUERY, text="anything", limit=2, score_threshold=0.5, boost=RecallBoost(now=NOW))

    assert _ids(results) == [2, 1]


# --- older collections -------------------------------------------------------------------------

def _legacy_collection(client: QdrantClient, *, with_keywords: bool = False) -> QdrantVectorStore:
    """A collection from before named vectors: one unnamed dense vector (released versions), or
    that plus the keyword vector (an earlier build of this branch)."""
    client.create_collection(
        QdrantInitializer.COLLECTION_NAME,
        vectors_config=VectorParams(size=DIM, distance=Distance.COSINE),
        sparse_vectors_config={TEXT_VECTOR: SparseVectorParams(modifier=Modifier.IDF)} if with_keywords else None,
    )
    return QdrantVectorStore(client, QdrantInitializer.COLLECTION_NAME)


class _Embedder:
    model_name = "fake"

    def encode(self, text: str) -> list[float]:
        return LOOSE


def test_a_dense_only_collection_still_searches_with_text_and_boost():
    store = _legacy_collection(QdrantClient(":memory:"))
    _put(store, 1, CLOSE, text="checkout-api OOMKilled", service="checkout-api")

    results = store.search(QUERY, text="checkout-api OOMKilled", limit=1, boost=RecallBoost(service="checkout-api", now=NOW), using=SYMPTOM_VECTOR)

    assert _ids(results) == [1]
    assert store.points_missing(SYMPTOM_VECTOR) == [] and store.points_missing(TEXT_VECTOR) == []


@pytest.mark.parametrize("with_keywords", [False, True])
def test_startup_migrates_an_older_collection_and_backfills_its_vectors(db_session, with_keywords):
    client = QdrantClient(":memory:")
    legacy = _legacy_collection(client, with_keywords=with_keywords)
    case = _add_case(db_session, "db_pool")
    point_id = CaseMemoryIndexer._generate_point_id(case.id)
    legacy.upsert(point_id, CLOSE, {"case_id": case.id, "service": "checkout-api", "created_at": None}, text="checkout-api")

    result = QdrantInitializer.initialize(client)

    assert result["migrated"] is True
    params = client.get_collection(QdrantInitializer.COLLECTION_NAME).config.params
    assert set(params.vectors) == {FULL_VECTOR, SYMPTOM_VECTOR, RESOLUTION_VECTOR}
    assert TEXT_VECTOR in params.sparse_vectors
    store = QdrantVectorStore(client, QdrantInitializer.COLLECTION_NAME)
    # Recall works straight after the migration, before any backfill: the old vector is now
    # `full`, and a symptom search falls back to it while symptoms are still missing.
    assert _ids(store.search(QUERY, limit=1)) == [case.id]
    assert _ids(store.search(QUERY, limit=1, using=SYMPTOM_VECTOR)) == [case.id]
    assert len(store.points_missing(SYMPTOM_VECTOR)) == 1

    config = MemoryConfig(vector_store=VectorStoreConfig(collection_name=QdrantInitializer.COLLECTION_NAME))
    indexer = CaseMemoryIndexer(store, embedder=_Embedder(), config=config)
    assert indexer.backfill_vectors(db_session) == 1
    assert indexer.backfill_vectors(db_session) == 0

    point = client.retrieve(QdrantInitializer.COLLECTION_NAME, [point_id], with_vectors=True, with_payload=True)[0]
    assert {FULL_VECTOR, SYMPTOM_VECTOR, RESOLUTION_VECTOR, TEXT_VECTOR} <= set(point.vector)
    # The full-document vector is kept, not re-embedded.
    assert point.vector[FULL_VECTOR] == pytest.approx(CLOSE, abs=1e-6)
    assert point.payload["service_key"] == "checkout-api" and "created_at" not in point.payload
    # Symptom search now runs on the backfilled symptom vector.
    assert store.search(LOOSE, limit=1, using=SYMPTOM_VECTOR)[0]["score"] == pytest.approx(1.0, abs=1e-6)
    assert QdrantInitializer.initialize(client)["migrated"] is False


def test_backfill_skips_points_whose_case_is_gone(db_session):
    client = QdrantClient(":memory:")
    QdrantInitializer.initialize(client)
    store = QdrantVectorStore(client, QdrantInitializer.COLLECTION_NAME)
    store.upsert(str(uuid4()), CLOSE, {"case_id": 999_999})
    indexer = CaseMemoryIndexer(store, embedder=_Embedder(), config=MemoryConfig())

    assert indexer.backfill_vectors(db_session) == 0
