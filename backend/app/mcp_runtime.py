from __future__ import annotations

import os
from pathlib import Path
from uuid import UUID

import yaml

from backend.app.ai.config import apply_ai_env_overrides
from backend.app.ai.factory import build_optional_ai_services
from backend.app.assistant.knowledge_bootstrap import ApplicationKnowledgeBootstrapService
from backend.app.assistant.service import AssistantServices, OperationalIntelligenceAssistant
from backend.app.config import AIConfig, MemoryConfig
from backend.app.memory.embedder import CaseEmbedder
from backend.app.memory.evidence_indexer import EvidenceMemoryIndexer
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
                memory_config = MemoryConfig(**config_data["memory"])
                if os.getenv("OPS_SIGNALS_QDRANT_URL"):
                    memory_config.vector_store.url = os.environ["OPS_SIGNALS_QDRANT_URL"]
                if os.getenv("OPS_SIGNALS_QDRANT_API_KEY"):
                    memory_config.vector_store.api_key = os.environ["OPS_SIGNALS_QDRANT_API_KEY"]
                return memory_config
    except Exception:
        return None
    return None


def load_ai_config() -> AIConfig | None:
    try:
        with open("config.yaml") as f:
            config_data = yaml.safe_load(f)
            ai_config = AIConfig(**config_data["ai"]) if config_data and "ai" in config_data else AIConfig()
            return apply_ai_env_overrides(ai_config)
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
    knowledge_bootstrap.bootstrap()

    ai_services = build_optional_ai_services(load_ai_config())
    docs_store = QdrantVectorStore(
        client=qdrant_client,
        collection_name=knowledge_bootstrap.COLLECTION_NAME,
    )
    findings_indexer = EvidenceMemoryIndexer(
        client=qdrant_client,
        embedder=embedder,
        vector_store=QdrantVectorStore(client=qdrant_client, collection_name="operational_findings"),
        collection_name="operational_findings",
        namespace=UUID("6ba7b812-9dad-11d1-80b4-00c04fd430c8"),
    )
    behaviors_indexer = EvidenceMemoryIndexer(
        client=qdrant_client,
        embedder=embedder,
        vector_store=QdrantVectorStore(client=qdrant_client, collection_name="operational_behaviors"),
        collection_name="operational_behaviors",
        namespace=UUID("6ba7b813-9dad-11d1-80b4-00c04fd430c8"),
    )
    assistant = OperationalIntelligenceAssistant(
        AssistantServices(
            embedder=embedder,
            case_similarity=similarity_service,
            docs_store=docs_store,
            ai_services=ai_services,
            findings_indexer=findings_indexer,
            behaviors_indexer=behaviors_indexer,
        )
    )
    return vector_store, embedder, indexer, similarity_service, assistant, knowledge_bootstrap
