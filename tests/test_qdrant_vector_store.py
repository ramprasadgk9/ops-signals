from types import SimpleNamespace

from backend.app.memory.vector_store import QdrantVectorStore


class FakeQdrantClient:
    def get_collections(self):
        return SimpleNamespace(collections=[SimpleNamespace(name="operational_cases")])

    def get_collection(self, collection_name: str):
        assert collection_name == "operational_cases"
        return SimpleNamespace(points_count=4)


def test_qdrant_health_uses_detailed_collection_info_for_point_count() -> None:
    store = QdrantVectorStore(FakeQdrantClient(), "operational_cases")

    assert store.health() == {
        "status": "healthy",
        "collection": "operational_cases",
        "points_count": 4,
    }
