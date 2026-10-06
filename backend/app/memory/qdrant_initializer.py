"""Qdrant collection initialization and health check."""

import logging
from typing import Optional

from qdrant_client import QdrantClient
from qdrant_client.models import Distance, Modifier, PayloadSchemaType, PointStruct, SparseVectorParams, VectorParams

from backend.app.memory.sparse_encoder import TEXT_VECTOR
from backend.app.memory.vector_names import DENSE_VECTORS, FULL_VECTOR

logger = logging.getLogger(__name__)


class QdrantInitializer:
    """Initialize and verify Qdrant collection for operational cases."""

    COLLECTION_NAME = "operational_cases"
    VECTOR_SIZE = 384
    DISTANCE = Distance.COSINE
    MIGRATION_BATCH = 256

    @staticmethod
    def initialize(client: QdrantClient) -> dict:
        """Initialize Qdrant collection if it doesn't exist.

        Args:
            client: QdrantClient instance

        Returns:
            Dictionary with initialization status
        """
        try:
            # Check if collection exists
            collections = client.get_collections()
            collection_exists = any(
                c.name == QdrantInitializer.COLLECTION_NAME
                for c in collections.collections
            )

            if collection_exists:
                # Verify collection configuration
                collection_info = client.get_collection(
                    QdrantInitializer.COLLECTION_NAME
                )
                
                # Check vector size
                if (
                    hasattr(collection_info.config, 'params')
                    and hasattr(collection_info.config.params, 'vectors')
                ):
                    if isinstance(collection_info.config.params.vectors, dict):
                        # Multiple vector types configured
                        for vector_config in collection_info.config.params.vectors.values():
                            if vector_config.size != QdrantInitializer.VECTOR_SIZE:
                                logger.warning(
                                    f"Collection {QdrantInitializer.COLLECTION_NAME} exists "
                                    f"with incompatible vector size {vector_config.size}. "
                                    f"Expected {QdrantInitializer.VECTOR_SIZE}."
                                )
                    else:
                        # Single vector type
                        if (
                            collection_info.config.params.vectors.size
                            != QdrantInitializer.VECTOR_SIZE
                        ):
                            logger.warning(
                                f"Collection {QdrantInitializer.COLLECTION_NAME} exists "
                                f"with incompatible vector size "
                                f"{collection_info.config.params.vectors.size}. "
                                f"Expected {QdrantInitializer.VECTOR_SIZE}."
                            )

                migrated = False
                if not QdrantInitializer._is_current(collection_info.config.params):
                    QdrantInitializer._migrate(client)
                    migrated = True
                else:
                    # Indexes added in later versions; creating an existing index is a no-op.
                    QdrantInitializer._create_payload_indexes(client)

                logger.info(
                    f"Collection {QdrantInitializer.COLLECTION_NAME} already exists"
                )
                return {
                    "status": "ready",
                    "collection": QdrantInitializer.COLLECTION_NAME,
                    "existing": True,
                    "migrated": migrated,
                }

            # Create collection
            logger.info(
                f"Creating collection {QdrantInitializer.COLLECTION_NAME} "
                f"with {QdrantInitializer.VECTOR_SIZE}-dimensional vectors"
            )
            
            QdrantInitializer._create_collection(client)

            logger.info(f"Collection {QdrantInitializer.COLLECTION_NAME} created successfully")
            
            return {
                "status": "ready",
                "collection": QdrantInitializer.COLLECTION_NAME,
                "existing": False,
            }

        except Exception as e:
            logger.error(f"Failed to initialize Qdrant collection: {e}")
            return {
                "status": "failed",
                "error": str(e),
            }

    @staticmethod
    def _is_current(params) -> bool:
        """Every named dense vector (vector_names) and the keyword vector are there."""
        named = params.vectors if isinstance(params.vectors, dict) else {}
        return all(name in named for name in DENSE_VECTORS) and TEXT_VECTOR in (params.sparse_vectors or {})

    @staticmethod
    def _create_collection(client: QdrantClient) -> None:
        """One named dense vector per view of a case - full document, symptom, resolution
        (vector_names) - plus the keyword vector for hybrid recall (sparse_encoder). IDF is
        computed by Qdrant, so the keyword vector needs no corpus stats."""
        client.create_collection(
            collection_name=QdrantInitializer.COLLECTION_NAME,
            vectors_config={
                name: VectorParams(size=QdrantInitializer.VECTOR_SIZE, distance=QdrantInitializer.DISTANCE)
                for name in DENSE_VECTORS
            },
            sparse_vectors_config={TEXT_VECTOR: SparseVectorParams(modifier=Modifier.IDF)},
        )

        # Create payload indexes for efficient filtering
        QdrantInitializer._create_payload_indexes(client)

    @staticmethod
    def _migrate(client: QdrantClient) -> None:
        """Recreate an older collection with every current vector, keeping every point.

        Qdrant can't add a vector to an existing collection, so the points are read out, the
        collection is recreated and the points written back: the old single vector becomes `full`,
        with the payload. Recall keeps working on the full document straight away;
        CaseMemoryIndexer.backfill_vectors then adds the symptom, resolution and keyword vectors
        from the cases in PostgreSQL. Everything here is derived from PostgreSQL, so a failure
        part-way loses nothing that re-indexing the cases can't rebuild."""
        name = QdrantInitializer.COLLECTION_NAME
        points: list[PointStruct] = []
        offset = None
        while True:
            records, offset = client.scroll(
                collection_name=name,
                limit=QdrantInitializer.MIGRATION_BATCH,
                offset=offset,
                with_payload=True,
                with_vectors=True,
            )
            points.extend(
                PointStruct(id=record.id, vector=_as_named(record.vector), payload=_without_null_created_at(record.payload))
                for record in records
            )
            if offset is None:
                break
        logger.info(f"Migrating {name} to named and keyword vectors: recreating with {len(points)} points")
        client.delete_collection(name)
        QdrantInitializer._create_collection(client)
        for start in range(0, len(points), QdrantInitializer.MIGRATION_BATCH):
            client.upsert(collection_name=name, points=points[start:start + QdrantInitializer.MIGRATION_BATCH])

    @staticmethod
    def _create_payload_indexes(client: QdrantClient) -> None:
        """Create payload indexes for efficient filtering.

        Args:
            client: QdrantClient instance
        """
        try:
            # Index fields for faster filtering and for the recall_scoring formula
            index_fields = {
                "metric_name": PayloadSchemaType.KEYWORD,
                "service": PayloadSchemaType.KEYWORD,
                "service_key": PayloadSchemaType.KEYWORD,
                "origin": PayloadSchemaType.KEYWORD,
                "case_id": PayloadSchemaType.INTEGER,
                "case_status": PayloadSchemaType.KEYWORD,
                "rca_verified": PayloadSchemaType.BOOL,
                "category": PayloadSchemaType.KEYWORD,
                "created_at": PayloadSchemaType.DATETIME,
            }

            for field, schema in index_fields.items():
                try:
                    client.create_payload_index(
                        collection_name=QdrantInitializer.COLLECTION_NAME,
                        field_name=field,
                        field_schema=schema,
                    )
                    logger.debug(f"Created payload index for {field}")
                except Exception as e:
                    logger.debug(f"Could not create index for {field}: {e}")

        except Exception as e:
            logger.warning(f"Failed to create payload indexes: {e}")

    @staticmethod
    def health_check(client: QdrantClient) -> dict:
        """Check Qdrant and collection health.

        Args:
            client: QdrantClient instance

        Returns:
            Dictionary with health status
        """
        try:
            # Check Qdrant server health
            response = client.get_collections()
            
            # Check if our collection exists
            collection_exists = any(
                c.name == QdrantInitializer.COLLECTION_NAME
                for c in response.collections
            )
            
            if not collection_exists:
                return {
                    "status": "unhealthy",
                    "reason": f"Collection {QdrantInitializer.COLLECTION_NAME} not found",
                }

            # Get collection info
            collection_info = client.get_collection(
                QdrantInitializer.COLLECTION_NAME
            )
            
            return {
                "status": "healthy",
                "collection": QdrantInitializer.COLLECTION_NAME,
                "points_count": collection_info.points_count,
                "vector_size": QdrantInitializer.VECTOR_SIZE,
            }

        except Exception as e:
            return {
                "status": "unhealthy",
                "error": str(e),
            }


def _without_null_created_at(payload: dict | None) -> dict:
    """Older indexers wrote created_at: null, which fails the recency bonus; a missing one doesn't."""
    payload = dict(payload or {})
    if payload.get("created_at", "") is None:
        del payload["created_at"]
    return payload


def _as_named(vector) -> dict:
    """An older point's vectors under the current names: its single (or unnamed) vector is `full`."""
    if isinstance(vector, dict):
        return {(FULL_VECTOR if name == "" else name): value for name, value in vector.items()}
    return {FULL_VECTOR: vector}
