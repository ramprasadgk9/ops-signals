"""Lazy semantic indexer for read-only evidence rows (findings, behavior findings).

Unlike CaseMemoryIndexer, this never touches the write path - the analysis pipeline
that creates findings/behaviors stays untouched. Instead, indexing happens on first
read: whenever the assistant searches a set of rows, any row missing from the vector
store gets embedded and upserted here, so every later search against the same rows
hits the vector store directly instead of re-embedding.
"""

from __future__ import annotations

import logging
from typing import Callable, TypeVar
from uuid import UUID, uuid5

from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams

from backend.app.memory.embedder import Embedder
from backend.app.memory.vector_store import VectorStore

logger = logging.getLogger(__name__)

T = TypeVar("T")


class EvidenceMemoryIndexer:
    VECTOR_SIZE = 384

    def __init__(
        self,
        client: QdrantClient,
        embedder: Embedder,
        vector_store: VectorStore,
        collection_name: str,
        namespace: UUID,
    ) -> None:
        self.client = client
        self.embedder = embedder
        self.vector_store = vector_store
        self.collection_name = collection_name
        self.namespace = namespace
        self._ensure_collection()

    def _ensure_collection(self) -> None:
        try:
            collections = self.client.get_collections()
            if any(collection.name == self.collection_name for collection in collections.collections):
                return
            self.client.create_collection(
                collection_name=self.collection_name,
                vectors_config=VectorParams(size=self.VECTOR_SIZE, distance=Distance.COSINE),
            )
        except Exception as exc:
            logger.warning("Failed to ensure Qdrant collection %s: %s", self.collection_name, exc)

    def point_id(self, row_id: object) -> str:
        return str(uuid5(self.namespace, f"{self.collection_name}:{row_id}"))

    def ensure_indexed(
        self,
        rows: list[T],
        *,
        id_fn: Callable[[T], object],
        text_fn: Callable[[T], str],
        payload_fn: Callable[[T], dict],
    ) -> None:
        """Embed and upsert any rows not already present in the vector store. Best-effort:
        a failure here must never block the caller's search - it just means those rows
        stay un-indexed until the next attempt."""
        if not rows:
            return
        point_ids = [self.point_id(id_fn(row)) for row in rows]
        try:
            existing_records = self.client.retrieve(
                collection_name=self.collection_name,
                ids=point_ids,
                with_payload=False,
                with_vectors=False,
            )
            existing = {str(record.id) for record in existing_records}
        except Exception as exc:
            logger.warning("Failed to check existing points in %s: %s", self.collection_name, exc)
            existing = set()

        for row, point_id in zip(rows, point_ids):
            if point_id in existing:
                continue
            try:
                vector = self.embedder.encode(text_fn(row))
                self.vector_store.upsert(point_id, vector, payload_fn(row))
            except Exception as exc:
                logger.warning("Failed to index a row into %s: %s", self.collection_name, exc)
