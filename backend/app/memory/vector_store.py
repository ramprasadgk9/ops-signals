"""Abstract VectorStore interface and Qdrant implementation."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from uuid import UUID

from qdrant_client import QdrantClient, models
from qdrant_client.models import Filter, PointStruct

from backend.app.memory.recall_scoring import RecallBoost, recall_formula
from backend.app.memory.sparse_encoder import TEXT_VECTOR, document_vector, query_vector
from backend.app.memory.vector_names import ALWAYS_INDEXED, FULL_VECTOR

logger = logging.getLogger(__name__)

# Candidates each recall branch (meaning, keywords) contributes before ranking and the score floor.
HYBRID_CANDIDATES = 40


class VectorStore(ABC):
    """Abstract interface for vector storage operations."""

    @abstractmethod
    def upsert(
        self,
        point_id: str,
        vector: list[float],
        payload: dict,
        *,
        text: str | None = None,
        vectors: dict[str, list[float] | None] | None = None,
    ) -> None:
        """Insert or update a point in the vector store.

        Args:
            point_id: Unique identifier for the point
            vector: Vector embedding (the `full` vector in a collection with named vectors)
            payload: Metadata to store with the point
            text: The embedded text, for keyword (hybrid) matching where the store supports it
            vectors: Further named vectors (vector_names), where the collection has them
        """
        ...

    @abstractmethod
    def search(
        self,
        vector: list[float],
        filters: dict | None = None,
        limit: int = 5,
        score_threshold: float = 0.0,
        *,
        text: str | None = None,
        boost: RecallBoost | None = None,
        using: str | None = None,
    ) -> list[dict]:
        """Search for similar vectors.

        Args:
            vector: Query vector
            filters: Optional Qdrant filter conditions
            limit: Maximum number of results
            score_threshold: Minimum similarity score
            text: The query's text, adding keyword matching to the ranking where supported
            boost: Ranking context (service, recency) applied as a score formula
            using: Which named vector to search (vector_names); the full document by default

        Returns:
            List of search results with point_id, score, and payload. score is always the
            similarity of the two vectors, whatever ranked the results. A ranked search also
            returns each point's full-document vector as `vector` (diversity.collapse_near_copies).
        """
        ...

    def points_missing(self, vector_name: str, limit: int = 256) -> list[dict]:
        """Points stored without `vector_name` (indexed before it existed); none by default."""
        return []

    def set_vectors(
        self,
        point_id: str,
        vectors: dict[str, list[float] | None],
        *,
        text: str | None = None,
        payload: dict | None = None,
    ) -> None:
        """Add named vectors, the keyword vector and payload fields to an existing point."""

    def get_vector(self, point_id: str, vector_name: str) -> list[float] | None:
        """One stored vector of a point, or None when the point or that vector is missing."""
        return self.get_vectors([point_id], vector_name).get(point_id)

    def get_vectors(self, point_ids: list[str], vector_name: str) -> dict[str, list[float]]:
        """`vector_name` for each point that has it, by point id; none by default."""
        return {}

    def similarity_pairs(
        self,
        filters: dict | None = None,
        sample: int = 500,
        neighbours: int = 20,
        using: str | None = None,
    ) -> list[tuple[str, str, float]]:
        """Each sampled point's closest neighbours as (point_id, point_id, similarity) pairs."""
        raise NotImplementedError(f"{type(self).__name__} can't compare stored points with each other")

    @abstractmethod
    def delete(self, point_id: str) -> None:
        """Delete a point from the vector store.

        Args:
            point_id: Unique identifier for the point to delete
        """
        ...

    @abstractmethod
    def health(self) -> dict:
        """Get health status of the vector store.

        Returns:
            Dictionary with status information
        """
        ...


class QdrantVectorStore(VectorStore):
    """Qdrant-based vector store implementation."""

    def __init__(self, client: QdrantClient, collection_name: str):
        """Initialize Qdrant vector store.

        Args:
            client: Initialized QdrantClient
            collection_name: Name of the collection to use
        """
        self.client = client
        self.collection_name = collection_name
        self._schema: tuple[frozenset[str], bool] | None = None
        self._complete: set[str] = set()

    def _read_schema(self) -> tuple[frozenset[str], bool]:
        """(named dense vectors, has keyword vector), read once. A collection with no named dense
        vectors - docs, evidence, or a case collection from before QdrantInitializer's migration -
        is searched on its single unnamed vector."""
        if self._schema is None:
            try:
                params = self.client.get_collection(self.collection_name).config.params
            except Exception as e:
                logger.warning(f"Could not read {self.collection_name} config, using dense search: {e}")
                return frozenset(), False
            named = frozenset(params.vectors) if isinstance(params.vectors, dict) else frozenset()
            self._schema = (named, TEXT_VECTOR in (params.sparse_vectors or {}))
        return self._schema

    def has_text_vector(self) -> bool:
        """Whether the collection was created for hybrid recall (QdrantInitializer)."""
        return self._read_schema()[1]

    def _dense_name(self, using: str | None) -> str | None:
        """The named vector to search, falling back to the full document; None when unnamed."""
        named, _ = self._read_schema()
        if not named:
            return None
        if using and using in named and self._is_complete(using):
            return using
        return FULL_VECTOR if FULL_VECTOR in named else sorted(named)[0]

    def _is_complete(self, vector_name: str) -> bool:
        """Whether every point has `vector_name`. While the startup backfill is still adding
        symptom vectors to older cases, searching on them would miss those cases, so search stays
        on the full document until none is left. Once complete it stays so: new cases are always
        indexed with it. Only vectors every case has are checked: a resolution vector is missing
        from every open case by design, so it is always searched as is."""
        if vector_name not in ALWAYS_INDEXED or vector_name == FULL_VECTOR or vector_name in self._complete:
            return True
        try:
            missing = self.client.count(
                collection_name=self.collection_name,
                count_filter=models.Filter(must_not=[models.HasVectorCondition(has_vector=vector_name)]),
                exact=True,
            ).count
        except Exception:
            return False
        if missing == 0:
            self._complete.add(vector_name)
        return missing == 0

    def upsert(
        self,
        point_id: str,
        vector: list[float],
        payload: dict,
        *,
        text: str | None = None,
        vectors: dict[str, list[float] | None] | None = None,
    ) -> None:
        """Upsert a point into Qdrant."""
        try:
            named, has_text = self._read_schema()
            sparse = document_vector(text) if text and has_text else None
            if named:
                point_vector: dict | list = {FULL_VECTOR: vector}
                point_vector.update({name: value for name, value in (vectors or {}).items() if value is not None and name in named})
            else:
                point_vector = {"": vector} if sparse else vector
            if sparse:
                point_vector[TEXT_VECTOR] = sparse
            point = PointStruct(
                id=_point_id_value(point_id),
                vector=point_vector,
                payload=payload,
            )
            self.client.upsert(
                collection_name=self.collection_name,
                points=[point],
            )
        except Exception as e:
            raise RuntimeError(f"Failed to upsert point into Qdrant: {e}")

    def search(
        self,
        vector: list[float],
        filters: dict | None = None,
        limit: int = 5,
        score_threshold: float = 0.0,
        *,
        text: str | None = None,
        boost: RecallBoost | None = None,
        using: str | None = None,
    ) -> list[dict]:
        """Search Qdrant collection.

        Plain vector search unless text or boost is given. Otherwise the meaning (dense) search
        and, on a hybrid collection, the keyword (sparse) search run as prefetches, and the
        recall_scoring formula ranks the candidates: similarity plus capped bonuses. Either way
        score_threshold and the returned score are the cosine similarity on the searched vector,
        so the strong/possible tiers keep meaning the same thing - keywords and bonuses only
        change the order."""
        try:
            name = self._dense_name(using)
            query_filter = Filter.model_validate(filters) if filters else None
            sparse = query_vector(text) if text and self.has_text_vector() else None
            if sparse is None and boost is None:
                results = self.client.query_points(
                    collection_name=self.collection_name,
                    query=vector,
                    using=name,
                    query_filter=query_filter,
                    limit=limit,
                    score_threshold=score_threshold,
                    with_payload=True,
                )
                return [
                    {
                        "point_id": str(result.id),
                        "score": result.score,
                        "payload": result.payload,
                    }
                    for result in results.points
                ]

            candidates = max(HYBRID_CANDIDATES, limit * 4)
            dense = models.Prefetch(query=vector, using=name, filter=query_filter, limit=candidates, score_threshold=score_threshold)
            prefetch = [dense]
            if sparse is not None:
                prefetch.append(models.Prefetch(query=sparse, using=TEXT_VECTOR, filter=query_filter, limit=candidates))
            try:
                results = self.client.query_points(
                    collection_name=self.collection_name,
                    prefetch=prefetch,
                    query=recall_formula(boost, keywords=sparse is not None),
                    query_filter=query_filter,
                    limit=candidates,
                    with_payload=True,
                    with_vectors=sorted({name, FULL_VECTOR}) if name else True,
                )
            except Exception as e:
                # Ranking is a refinement; one malformed payload must not take recall down with it.
                logger.warning(f"Ranked recall on {self.collection_name} failed, using plain similarity: {e}")
                return self.search(vector, filters, limit, score_threshold, using=using)
            ranked = []
            for result in results.points:
                # Keyword-only candidates below the similarity floor are dropped here: they may
                # reorder matches, never add ones the floor would have hidden.
                similarity = cosine_similarity(vector, _dense(result.vector, name))
                if similarity < score_threshold:
                    continue
                ranked.append({
                    "point_id": str(result.id),
                    "score": similarity,
                    "rank_score": result.score,
                    "payload": result.payload,
                    "vector": _dense(result.vector, FULL_VECTOR if name else None),
                })
            return ranked[:limit]
        except Exception as e:
            raise RuntimeError(f"Failed to search Qdrant: {e}")

    def similarity_pairs(
        self,
        filters: dict | None = None,
        sample: int = 500,
        neighbours: int = 20,
        using: str | None = None,
    ) -> list[tuple[str, str, float]]:
        """Qdrant's distance matrix: `sample` points matching `filters` (all of them when there are
        fewer), each with its `neighbours` most similar points among the same sample. With `using`,
        only points that have that vector are sampled."""
        name = self._dense_name(using)
        conditions: list = [Filter.model_validate(filters)] if filters else []
        if using and name == using:
            conditions.append(models.HasVectorCondition(has_vector=using))
        try:
            result = self.client.search_matrix_pairs(
                collection_name=self.collection_name,
                query_filter=Filter(must=conditions) if conditions else None,
                sample=sample,
                limit=neighbours,
                using=name,
            )
        except Exception as e:
            raise RuntimeError(f"Failed to compare points in Qdrant: {e}")
        return [(str(pair.a), str(pair.b), pair.score) for pair in result.pairs]

    def points_missing(self, vector_name: str, limit: int = 256) -> list[dict]:
        named, has_text = self._read_schema()
        if vector_name not in named and not (vector_name == TEXT_VECTOR and has_text):
            return []
        points, _ = self.client.scroll(
            collection_name=self.collection_name,
            scroll_filter=models.Filter(must_not=[models.HasVectorCondition(has_vector=vector_name)]),
            limit=limit,
            with_payload=True,
            with_vectors=False,
        )
        return [{"point_id": str(point.id), "payload": point.payload or {}} for point in points]

    def set_vectors(
        self,
        point_id: str,
        vectors: dict[str, list[float] | None],
        *,
        text: str | None = None,
        payload: dict | None = None,
    ) -> None:
        named, has_text = self._read_schema()
        point_id_value = _point_id_value(point_id)
        update: dict = {name: value for name, value in vectors.items() if value is not None and name in named}
        sparse = document_vector(text) if text and has_text else None
        if sparse is not None:
            update[TEXT_VECTOR] = sparse
        if update:
            self.client.update_vectors(
                collection_name=self.collection_name,
                points=[models.PointVectors(id=point_id_value, vector=update)],
            )
        if payload:
            self.client.set_payload(collection_name=self.collection_name, payload=payload, points=[point_id_value])

    def get_vectors(self, point_ids: list[str], vector_name: str) -> dict[str, list[float]]:
        named, _ = self._read_schema()
        if not point_ids or (named and vector_name not in named):
            return {}
        name = vector_name if named else None
        records = self.client.retrieve(
            collection_name=self.collection_name,
            ids=[_point_id_value(point_id) for point_id in point_ids],
            with_vectors=[name] if name else True,
        )
        vectors = {str(record.id): _dense(record.vector, name) for record in records}
        return {point_id: vector for point_id, vector in vectors.items() if vector}

    def delete(self, point_id: str) -> None:
        """Delete a point from Qdrant."""
        try:
            self.client.delete(
                collection_name=self.collection_name,
                points_selector=[_point_id_value(point_id)],
            )
        except Exception as e:
            raise RuntimeError(f"Failed to delete point from Qdrant: {e}")

    def health(self) -> dict:
        """Get Qdrant health status."""
        try:
            response = self.client.get_collections()
            collection_exists = any(coll.name == self.collection_name for coll in response.collections)

            if not collection_exists:
                return {
                    "status": "unhealthy",
                    "collection": self.collection_name,
                    "reason": f"Collection {self.collection_name} not found",
                }

            collection_info = self.client.get_collection(self.collection_name)
            
            return {
                "status": "healthy",
                "collection": self.collection_name,
                "points_count": collection_info.points_count,
            }
        except Exception as e:
            return {
                "status": "unhealthy",
                "collection": self.collection_name,
                "error": str(e),
            }


def _point_id_value(point_id: str) -> str | int:
    # Qdrant accepts both UUID strings and unsigned integers
    try:
        # Validate it's a valid UUID format
        UUID(point_id)
        # Use UUID string as is - Qdrant will accept it
        return point_id
    except ValueError:
        # If not a UUID, use hash converted to unsigned integer
        return hash(point_id) & 0x7FFFFFFFFFFFFFFF


def _dense(stored: object, name: str | None) -> list[float] | None:
    """One dense vector from a returned point: a plain list, or an entry of a named-vector dict."""
    if isinstance(stored, dict):
        return stored.get(name if name else "")
    return stored


def cosine_similarity(query: list[float], dense: list[float] | None) -> float:
    """Cosine similarity of two dense vectors. Qdrant stores cosine vectors normalized; both are
    normalized here anyway, so the result never depends on that."""
    if not dense:
        return 0.0
    dot = sum(a * b for a, b in zip(query, dense))
    query_norm = sum(a * a for a in query) ** 0.5
    stored_norm = sum(b * b for b in dense) ** 0.5
    return dot / (query_norm * stored_norm) if query_norm and stored_norm else 0.0
