from __future__ import annotations

from pathlib import Path

import yaml

from backend.app.ai.factory import build_optional_ai_services
from backend.app.assistant.knowledge_bootstrap import ApplicationKnowledgeBootstrapService
from backend.app.assistant.service import AssistantServices, OperationalIntelligenceAssistant
from backend.app.config import AIConfig, MemoryConfig
from backend.app.memory.embedder import CaseEmbedder
from backend.app.memory.indexer import CaseMemoryIndexer
from backend.app.memory.qdrant_initializer import QdrantInitializer
from backend.app.memory.similarity_service import SimilarityService
from backend.app.memory.vector_store import QdrantVectorStore
from backend.app.memory.vector_store import VectorStore
from qdrant_client import QdrantClient


def load_memory_config() -> MemoryConfig | None:
    try:
        with open("config.yaml") as f:
            config_data = yaml.safe_load(f)
            if config_data and "memory" in config_data:
                return MemoryConfig(**config_data["memory"])
    except Exception:
        return None
    return None


def load_ai_config() -> AIConfig | None:
    try:
        with open("config.yaml") as f:
            config_data = yaml.safe_load(f)
            if config_data and "ai" in config_data:
                return AIConfig(**config_data["ai"])
    except Exception:
        return None
    return None


def initialize_memory_services(memory_config: MemoryConfig) -> tuple[VectorStore, CaseEmbedder, CaseMemoryIndexer, SimilarityService, OperationalIntelligenceAssistant, ApplicationKnowledgeBootstrapService]:
    qdrant_client = QdrantClient(
        url=memory_config.vector_store.url,
        api_key=memory_config.vector_store.api_key,
    )
    vector_store = QdrantVectorStore(
        client=qdrant_client,
        collection_name=memory_config.vector_store.collection_name,
    )
    embedder = CaseEmbedder(model_name=memory_config.embedding.model)
    indexer = CaseMemoryIndexer(vector_store=vector_store, embedder=embedder, config=memory_config)
    similarity_service = SimilarityService(vector_store=vector_store, embedder=embedder, config=memory_config)

    QdrantInitializer.initialize(qdrant_client)
    knowledge_bootstrap = ApplicationKnowledgeBootstrapService(
        client=qdrant_client,
        embedder=embedder,
        repo_root=Path.cwd(),
    )
    knowledge_bootstrap.bootstrap(force=True)

    ai_services = build_optional_ai_services(load_ai_config())
    docs_store = QdrantVectorStore(
        client=qdrant_client,
        collection_name=knowledge_bootstrap.COLLECTION_NAME,
    )
    assistant = OperationalIntelligenceAssistant(
        AssistantServices(
            embedder=embedder,
            case_similarity=similarity_service,
            docs_store=docs_store,
            ai_services=ai_services,
        )
    )
    return vector_store, embedder, indexer, similarity_service, assistant, knowledge_bootstrap
