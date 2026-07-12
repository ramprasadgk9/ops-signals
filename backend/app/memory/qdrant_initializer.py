"""Qdrant collection initialization and health check."""

import logging
from typing import Optional

from qdrant_client import QdrantClient
from qdrant_client.models import Distance, PointStruct, VectorParams

logger = logging.getLogger(__name__)


class QdrantInitializer:
    """Initialize and verify Qdrant collection for operational cases."""

    COLLECTION_NAME = "operational_cases"
    VECTOR_SIZE = 384
    DISTANCE = Distance.COSINE

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

                logger.info(
                    f"Collection {QdrantInitializer.COLLECTION_NAME} already exists"
                )
                return {
                    "status": "ready",
                    "collection": QdrantInitializer.COLLECTION_NAME,
                    "existing": True,
                }

            # Create collection
            logger.info(
                f"Creating collection {QdrantInitializer.COLLECTION_NAME} "
                f"with {QdrantInitializer.VECTOR_SIZE}-dimensional vectors"
            )
            
            client.create_collection(
                collection_name=QdrantInitializer.COLLECTION_NAME,
                vectors_config=VectorParams(
                    size=QdrantInitializer.VECTOR_SIZE,
                    distance=QdrantInitializer.DISTANCE,
                ),
            )

            # Create payload indexes for efficient filtering
            QdrantInitializer._create_payload_indexes(client)

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
    def _create_payload_indexes(client: QdrantClient) -> None:
        """Create payload indexes for efficient filtering.

        Args:
            client: QdrantClient instance
        """
        try:
            # Index fields for faster filtering
            index_fields = [
                "metric_name",
                "service",
                "case_id",
                "case_status",
                "rca_verified",
                "category",
            ]
            
            for field in index_fields:
                try:
                    client.create_payload_index(
                        collection_name=QdrantInitializer.COLLECTION_NAME,
                        field_name=field,
                        field_schema="keyword",
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
