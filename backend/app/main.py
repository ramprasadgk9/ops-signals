from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

import yaml
from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from qdrant_client import QdrantClient
from sqlalchemy.orm import Session

from backend.app.api.analysis_runs import router as analysis_runs_router
from backend.app.api.admin_analyzers import router as admin_analyzers_router
from backend.app.api.assistant import router as assistant_router
from backend.app.api.analyzer_router import router as analyzer_router
from backend.app.api.autonomous import router as autonomous_router
from backend.app.api.mcp import router as mcp_router
from backend.app.api.experiments import router as experiments_router
from backend.app.api.behavior_definitions import router as behavior_definitions_router
from backend.app.api.behavior_evaluations import router as behavior_evaluations_router
from backend.app.api.capabilities import router as capabilities_router
from backend.app.api.cases import router as cases_router
from backend.app.api.findings import router as findings_router
from backend.app.api.ingestion import router as ingestion_router
from backend.app.api.direct_prometheus import analysis_router as direct_prometheus_analysis_router
from backend.app.api.direct_prometheus import router as direct_prometheus_router
from backend.app.api.learning_outcomes import router as learning_outcomes_router
from backend.app.api.memory import router as memory_router
from backend.app.api.overview import router as overview_router
from backend.app.api.questions import router as questions_router
from backend.app.api.services import router as services_router
from backend.app.api.signals import router as signals_router
from backend.app.api.testing import router as testing_router
from backend.app.api.timeseries import router as timeseries_router
from backend.app.metric_analyzer_recommendations.api import router as metric_analyzer_recommendations_router
from backend.app.config import MemoryConfig, get_settings
from backend.app.config import AIConfig
from backend.app.assistant.knowledge_bootstrap import ApplicationKnowledgeBootstrapService
from backend.app.memory.embedder import CaseEmbedder
from backend.app.memory.indexer import CaseMemoryIndexer
from backend.app.assistant.service import AssistantServices, OperationalIntelligenceAssistant
from backend.app.ai.factory import build_optional_ai_services
from backend.app.memory.qdrant_initializer import QdrantInitializer
from backend.app.memory.similarity_service import SimilarityService
from backend.app.memory.vector_store import QdrantVectorStore, VectorStore
from backend.app.models.db import get_engine, get_session_local, init_engine, get_db
from backend.app.models.entities import Base
from backend.app.models.schema_compat import ensure_learning_schema
from backend.app.storage.bootstrap import seed_reference_data

logger = logging.getLogger(__name__)


def load_memory_config() -> MemoryConfig | None:
    """Load memory configuration from config.yaml."""
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
    except Exception as e:
        logger.warning(f"Failed to load memory configuration: {e}")
    return None


def load_ai_config() -> AIConfig | None:
    try:
        with open("config.yaml") as f:
            config_data = yaml.safe_load(f)
            if config_data and "ai" in config_data:
                ai_config = AIConfig(**config_data["ai"])
                if os.getenv("OPS_SIGNALS_OLLAMA_URL"):
                    ai_config.ollama.base_url = os.environ["OPS_SIGNALS_OLLAMA_URL"]
                if os.getenv("OPS_SIGNALS_OLLAMA_MODEL"):
                    ai_config.ollama.model = os.environ["OPS_SIGNALS_OLLAMA_MODEL"]
                return ai_config
    except Exception as e:
        logger.warning(f"Failed to load AI configuration: {e}")
    return None


def initialize_memory_services(memory_config: MemoryConfig) -> tuple:
    """Initialize Qdrant client, vector store, embedder, indexer, and similarity service.

    Args:
        memory_config: Memory configuration

    Returns:
        Tuple of (vector_store, embedder, indexer, similarity_service)
    """
    try:
        # Connect to Qdrant
        logger.info(f"Connecting to Qdrant at {memory_config.vector_store.url}")
        qdrant_client = QdrantClient(
            url=memory_config.vector_store.url,
            api_key=memory_config.vector_store.api_key,
        )

        # Initialize vector store
        vector_store = QdrantVectorStore(
            client=qdrant_client,
            collection_name=memory_config.vector_store.collection_name,
        )

        # Initialize embedder (singleton)
        embedder = CaseEmbedder(model_name=memory_config.embedding.model)
        logger.info(f"Embedder initialized: {embedder.model_name} ({embedder.dimension}D)")

        # Initialize indexer
        indexer = CaseMemoryIndexer(
            vector_store=vector_store,
            embedder=embedder,
            config=memory_config,
        )

        # Initialize similarity service
        similarity_service = SimilarityService(
            vector_store=vector_store,
            embedder=embedder,
            config=memory_config,
        )

        # Initialize collections
        init_result = QdrantInitializer.initialize(qdrant_client)
        knowledge_bootstrap = ApplicationKnowledgeBootstrapService(
            client=qdrant_client,
            embedder=embedder,
            repo_root=Path.cwd(),
        )
        knowledge_init = knowledge_bootstrap.bootstrap(force=True)
        logger.info(f"Qdrant collection initialization: {init_result}")
        logger.info(
            "Knowledge collection bootstrap: created=%s updated=%s missing=%s",
            knowledge_init.created_documents,
            knowledge_init.updated_documents,
            knowledge_init.verification.missing_document_ids,
        )

        ai_config = load_ai_config()
        ai_services = build_optional_ai_services(ai_config)

        # Initialize assistant services
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

        logger.info("Memory services initialized successfully")
        return vector_store, embedder, indexer, similarity_service, assistant, knowledge_bootstrap

    except Exception as e:
        logger.error(f"Failed to initialize memory services: {e}")
        return None, None, None, None, None, None


def create_app(database_url: str | None = None) -> FastAPI:
    settings = get_settings()
    
    # Shared state for memory services
    memory_services = {
        "vector_store": None,
        "indexer": None,
        "similarity_service": None,
        "config": None,
        "embedder": None,
        "assistant": None,
        "knowledge_bootstrap": None,
        "ai_config": None,
    }

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        init_engine(database_url)
        Base.metadata.create_all(bind=get_engine())
        ensure_learning_schema(get_engine())
        session_local = get_session_local()
        with session_local() as db:
            seed_reference_data(db)

        # Load memory config at startup
        memory_config = load_memory_config()
        memory_services["ai_config"] = load_ai_config()
        memory_services["config"] = memory_config
        
        # Initialize memory services if enabled
        if memory_config and memory_config.enabled:
            logger.info("Initializing operational memory services...")
            (
                memory_services["vector_store"],
                memory_services["embedder"],
                memory_services["indexer"],
                memory_services["similarity_service"],
                memory_services["assistant"],
                memory_services["knowledge_bootstrap"],
            ) = initialize_memory_services(memory_config)
            logger.info(f"✓ Memory services initialized successfully")
        else:
            logger.info(f"Memory services disabled")

        # Populate the shared services container for the API endpoints
        from backend.app.api import memory as memory_module
        memory_module._services["indexer"] = memory_services["indexer"]
        memory_module._services["similarity_service"] = memory_services["similarity_service"]
        memory_module._services["config"] = memory_services["config"]
        memory_module._services["vector_store"] = memory_services["vector_store"]
        memory_module._services["embedder"] = memory_services["embedder"]
        from backend.app.api import assistant as assistant_module
        assistant_module._services["assistant"] = memory_services["assistant"]
        assistant_module._services["knowledge_bootstrap"] = memory_services["knowledge_bootstrap"]

        yield

    app = FastAPI(title=settings.app_name, version=settings.app_version, lifespan=lifespan)
    
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:3000",
            "http://127.0.0.1:3000",
            "http://localhost:5173",
            "http://127.0.0.1:5173",
            "http://localhost:5174",
            "http://127.0.0.1:5174",
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    
    # Register routers
    app.include_router(services_router)
    app.include_router(admin_analyzers_router)
    app.include_router(overview_router)
    app.include_router(analysis_runs_router)
    app.include_router(behavior_definitions_router)
    app.include_router(behavior_evaluations_router)
    app.include_router(capabilities_router)
    app.include_router(questions_router)
    app.include_router(signals_router)
    app.include_router(findings_router)
    app.include_router(cases_router)
    app.include_router(timeseries_router)
    app.include_router(metric_analyzer_recommendations_router)
    app.include_router(analyzer_router)
    app.include_router(autonomous_router)
    app.include_router(experiments_router)
    app.include_router(ingestion_router)
    app.include_router(direct_prometheus_router)
    app.include_router(direct_prometheus_analysis_router)
    app.include_router(learning_outcomes_router)
    app.include_router(assistant_router)
    app.include_router(mcp_router)
    app.include_router(testing_router)
    
    # Register memory router
    app.include_router(memory_router)
    
    return app


app = create_app()
