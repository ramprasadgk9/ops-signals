from __future__ import annotations

from types import SimpleNamespace
from uuid import NAMESPACE_URL

from backend.app.memory.evidence_indexer import EvidenceMemoryIndexer


class _FakeQdrantClient:
    def __init__(self, *, existing_collections: set[str] | None = None, existing_point_ids: set[str] | None = None) -> None:
        self._collections = set(existing_collections or set())
        self._existing_point_ids = set(existing_point_ids or set())
        self.created_collections: list[str] = []

    def get_collections(self):
        return SimpleNamespace(collections=[SimpleNamespace(name=name) for name in self._collections])

    def create_collection(self, collection_name: str, vectors_config) -> None:
        self._collections.add(collection_name)
        self.created_collections.append(collection_name)

    def retrieve(self, collection_name: str, ids, with_payload=False, with_vectors=False):
        return [SimpleNamespace(id=point_id) for point_id in ids if point_id in self._existing_point_ids]


class _FakeEmbedder:
    def __init__(self) -> None:
        self.encoded: list[str] = []

    def encode(self, text: str) -> list[float]:
        self.encoded.append(text)
        return [0.1, 0.2, 0.3]


class _FakeVectorStore:
    def __init__(self) -> None:
        self.upserts: list[tuple[str, list[float], dict]] = []

    def upsert(self, point_id: str, vector: list[float], payload: dict) -> None:
        self.upserts.append((point_id, vector, payload))

    def search(self, vector, filters=None, limit=5, score_threshold=0.0):
        return []

    def delete(self, point_id: str) -> None:
        raise NotImplementedError

    def health(self) -> dict:
        raise NotImplementedError


def test_ensure_collection_creates_it_when_missing() -> None:
    client = _FakeQdrantClient()
    EvidenceMemoryIndexer(client=client, embedder=_FakeEmbedder(), vector_store=_FakeVectorStore(), collection_name="operational_findings", namespace=NAMESPACE_URL)

    assert client.created_collections == ["operational_findings"]


def test_ensure_collection_is_a_no_op_when_it_already_exists() -> None:
    client = _FakeQdrantClient(existing_collections={"operational_findings"})
    EvidenceMemoryIndexer(client=client, embedder=_FakeEmbedder(), vector_store=_FakeVectorStore(), collection_name="operational_findings", namespace=NAMESPACE_URL)

    assert client.created_collections == []


def test_ensure_indexed_embeds_and_upserts_only_rows_missing_from_the_vector_store() -> None:
    embedder = _FakeEmbedder()
    vector_store = _FakeVectorStore()
    indexer = EvidenceMemoryIndexer(client=_FakeQdrantClient(), embedder=embedder, vector_store=vector_store, collection_name="operational_findings", namespace=NAMESPACE_URL)

    rows = [{"id": 1, "text": "first finding"}, {"id": 2, "text": "second finding"}]
    already_indexed_id = indexer.point_id(1)
    indexer.client._existing_point_ids = {already_indexed_id}

    indexer.ensure_indexed(
        rows,
        id_fn=lambda row: row["id"],
        text_fn=lambda row: row["text"],
        payload_fn=lambda row: {"row_id": row["id"]},
    )

    assert embedder.encoded == ["second finding"]
    assert len(vector_store.upserts) == 1
    assert vector_store.upserts[0][2] == {"row_id": 2}


def test_ensure_indexed_is_idempotent_point_ids() -> None:
    indexer = EvidenceMemoryIndexer(client=_FakeQdrantClient(), embedder=_FakeEmbedder(), vector_store=_FakeVectorStore(), collection_name="operational_findings", namespace=NAMESPACE_URL)

    assert indexer.point_id(42) == indexer.point_id(42)
    assert indexer.point_id(42) != indexer.point_id(43)


def test_ensure_indexed_does_not_raise_when_a_single_row_fails_to_embed() -> None:
    class _FlakyEmbedder(_FakeEmbedder):
        def encode(self, text: str) -> list[float]:
            if text == "boom":
                raise RuntimeError("embedding failed")
            return super().encode(text)

    embedder = _FlakyEmbedder()
    vector_store = _FakeVectorStore()
    indexer = EvidenceMemoryIndexer(client=_FakeQdrantClient(), embedder=embedder, vector_store=vector_store, collection_name="operational_findings", namespace=NAMESPACE_URL)

    rows = [{"id": 1, "text": "boom"}, {"id": 2, "text": "fine"}]
    indexer.ensure_indexed(
        rows,
        id_fn=lambda row: row["id"],
        text_fn=lambda row: row["text"],
        payload_fn=lambda row: {"row_id": row["id"]},
    )

    assert len(vector_store.upserts) == 1
    assert vector_store.upserts[0][2] == {"row_id": 2}
