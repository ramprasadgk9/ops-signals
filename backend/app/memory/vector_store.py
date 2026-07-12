"""Abstract VectorStore interface and Qdrant implementation."""

from abc import ABC, abstractmethod
from uuid import UUID

from qdrant_client import QdrantClient
from qdrant_client.models import PointStruct


class VectorStore(ABC):
    """Abstract interface for vector storage operations."""

    @abstractmethod
    def upsert(
        self,
        point_id: str,
        vector: list[float],
        payload: dict,
    ) -> None:
        """Insert or update a point in the vector store.

        Args:
            point_id: Unique identifier for the point
            vector: Vector embedding
            payload: Metadata to store with the point
        """
        ...

    @abstractmethod
    def search(
        self,
        vector: list[float],
        filters: dict | None = None,
        limit: int = 5,
        score_threshold: float = 0.0,
    ) -> list[dict]:
        """Search for similar vectors.

        Args:
            vector: Query vector
            filters: Optional Qdrant filter conditions
            limit: Maximum number of results
            score_threshold: Minimum similarity score

        Returns:
            List of search results with point_id, score, and payload
        """
        ...

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

    def upsert(
        self,
        point_id: str,
        vector: list[float],
        payload: dict,
    ) -> None:
        """Upsert a point into Qdrant."""
        try:
            # Qdrant accepts both UUID strings and unsigned integers
            # Try to use UUID string directly
            try:
                # Validate it's a valid UUID format
                UUID(point_id)
                # Use UUID string as is - Qdrant will accept it
                point_id_value = point_id
            except ValueError:
                # If not a UUID, use hash converted to unsigned integer
                point_id_value = hash(point_id) & 0x7FFFFFFFFFFFFFFF
            
            point = PointStruct(
                id=point_id_value,
                vector=vector,
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
    ) -> list[dict]:
        """Search Qdrant collection."""
        try:
            # Use query_points for vector similarity search
            results = self.client.query_points(
                collection_name=self.collection_name,
                query=vector,
                query_filter=filters,
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
        except Exception as e:
            raise RuntimeError(f"Failed to search Qdrant: {e}")

    def delete(self, point_id: str) -> None:
        """Delete a point from Qdrant."""
        try:
            # Qdrant accepts both UUID strings and unsigned integers
            try:
                # Validate it's a valid UUID format
                UUID(point_id)
                # Use UUID string as is - Qdrant will accept it
                point_id_value = point_id
            except ValueError:
                # If not a UUID, use hash converted to unsigned integer
                point_id_value = hash(point_id) & 0x7FFFFFFFFFFFFFFF
            
            self.client.delete(
                collection_name=self.collection_name,
                points_selector=[point_id_value],
            )
        except Exception as e:
            raise RuntimeError(f"Failed to delete point from Qdrant: {e}")

    def health(self) -> dict:
        """Get Qdrant health status."""
        try:
            response = self.client.get_collections()
            collection = None
            for coll in response.collections:
                if coll.name == self.collection_name:
                    collection = coll
                    break
            
            return {
                "status": "healthy",
                "collection": self.collection_name,
                "points_count": collection.points_count if collection else 0,
            }
        except Exception as e:
            return {
                "status": "unhealthy",
                "error": str(e),
            }
