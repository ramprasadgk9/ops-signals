from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from uuid import UUID

import yaml
from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from qdrant_client import QdrantClient
from sqlalchemy.orm import Session

from backend.app.api.ai import router as ai_router
from backend.app.api.errors import unhandled_error
from backend.app.api.alerts import router as alerts_router
from backend.app.api.analysis_runs import router as analysis_runs_router
from backend.app.api.admin_analyzers import router as admin_analyzers_router
from backend.app.api.analyzer_labs import router as analyzer_labs_router
from backend.app.api.analyzer_settings import router as analyzer_settings_router
from backend.app.api.assistant import router as assistant_router
from backend.app.api.analyzer_router import router as analyzer_router
from backend.app.api.autonomous import router as autonomous_router
from backend.app.api.mcp import router as mcp_router
from backend.app.api.events import router as events_router
from backend.app.api.behavior_definitions import router as behavior_definitions_router
from backend.app.api.behavior_evaluations import router as behavior_evaluations_router
from backend.app.api.behavior_lab import router as behavior_lab_router
from backend.app.api.capabilities import router as capabilities_router
from backend.app.api.case_imports import router as case_imports_router
from backend.app.api.cases import router as cases_router
from backend.app.api.findings import router as findings_router
from backend.app.api.ingestion import router as ingestion_router
from backend.app.api.ingestion_status import router as ingestion_status_router
from backend.app.api.direct_prometheus import analysis_router as direct_prometheus_analysis_router
from backend.app.api.direct_prometheus import router as direct_prometheus_router
from backend.app.api.learning_outcomes import router as learning_outcomes_router
from backend.app.api.memory import router as memory_router
from backend.app.api.metrics import router as self_metrics_router
from backend.app.api.metric_usage import router as metric_usage_router
from backend.app.api.otlp import router as otlp_router
from backend.app.api.overview import router as overview_router
from backend.app.api.questions import router as questions_router
from backend.app.api.notifications import router as notifications_router
from backend.app.api.services import router as services_router
from backend.app.api.setup_check import router as setup_check_router
from backend.app.api.me import router as me_router
from backend.app.api.auth import router as auth_router
from backend.app.api.signals import router as signals_router
from backend.app.api.testing import router as testing_router
from backend.app.api.timeseries import router as timeseries_router
from backend.app.metric_analyzer_recommendations.api import router as metric_analyzer_recommendations_router
from backend.app.config import MemoryConfig, get_auth_config, get_prometheus_connections, get_security_config, get_settings, get_slack_config
from backend.app.config import AIConfig, TicketingConfig, get_alert_enrichment_config, get_ticketing_config, ui_base_url
from backend.app.assistant.knowledge_bootstrap import ApplicationKnowledgeBootstrapService
from backend.app.memory.embedder import CaseEmbedder
from backend.app.memory.evidence_indexer import EvidenceMemoryIndexer
from backend.app.memory import availability as memory_availability
from backend.app.memory.catch_up import run_memory_catch_up_loop, waiting_at_startup
from backend.app.memory.indexer import CaseMemoryIndexer
from backend.app.memory.vector_names import SYMPTOM_VECTOR
from backend.app.notifications.slack_client import SlackNotifier
from backend.app.notifications.worker import run_slack_retry_loop
from backend.app.services.case_status import backfill_case_statuses
from backend.app.assistant.service import AssistantServices, OperationalIntelligenceAssistant
from backend.app.ai.config import apply_ai_env_overrides
from backend.app.ai.factory import build_optional_ai_services
from backend.app.memory.qdrant_initializer import QdrantInitializer
from backend.app.memory.similarity_service import SimilarityService
from backend.app.memory.vector_store import QdrantVectorStore, VectorStore
from backend.app.models.db import get_engine, get_session_local, init_engine, get_db
from backend.app.api.ticketing import router as ticketing_router, get_ticketing_service
from backend.app.integrations.ticketing.worker import run_ticketing_worker_loop
from backend.app.models.entities import Base
from backend.app.models.schema_compat import (
    ensure_ai_narrative_schema,
    ensure_autonomous_policy_scheduling_schema,
    ensure_case_behavior_link_schema,
    ensure_case_import_schema,
    ensure_case_link_unique_schema,
    ensure_case_memory_schema,
    ensure_actor_schema,
    ensure_cluster_schema,
    ensure_finding_problem_schema,
    ensure_problem_event_schema,
    ensure_metric_usage_schema,
    ensure_point_series_key_schema,
    ensure_server_defaults,
    ensure_learning_schema,
    ensure_ticketing_schema,
)
from backend.app.roles import require_grafana_role
from backend.app.demo import refuse_in_demo
from backend.app.api.demo import router as demo_router
from backend.app.oidc import setup_problem as oidc_setup_problem
from backend.app.security import require_api_token
from backend.app.storage.bootstrap import seed_reference_data
from intelligence.storage.postgres_store import register_findings_hook

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
            ai_config = AIConfig(**config_data["ai"]) if config_data and "ai" in config_data else AIConfig()
            return apply_ai_env_overrides(ai_config)
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
        # Unchanged documents are skipped; only added, edited or removed docs cost anything.
        knowledge_init = knowledge_bootstrap.bootstrap()
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

        logger.info("Memory services initialized successfully")
        return vector_store, embedder, indexer, similarity_service, assistant, knowledge_bootstrap

    except Exception as e:
        logger.error(f"Failed to initialize memory services: {e}")
        memory_availability.mark(memory_availability.UNAVAILABLE)
        return None, None, None, None, None, None


MEMORY_RETRY_FIRST_SECONDS = 15
MEMORY_RETRY_MAX_SECONDS = 300


def _publish_memory_services(memory_services: dict) -> None:
    """Shares the memory services with the API modules that read them."""
    from backend.app.api import ai as ai_module
    from backend.app.api import assistant as assistant_module
    from backend.app.api import memory as memory_module

    for key in ("indexer", "similarity_service", "config", "vector_store", "embedder"):
        memory_module._services[key] = memory_services[key]
    assistant_module._services["assistant"] = memory_services["assistant"]
    assistant_module._services["knowledge_bootstrap"] = memory_services["knowledge_bootstrap"]
    ai_module._services["config"] = memory_services["ai_config"]


def warn_if_links_have_no_ui_address() -> None:
    """Alert messages and tickets link back to the UI; without OPS_SIGNALS_UI_BASE_URL those links
    are left out (they used to point at localhost:3000), so say so where an operator looks."""
    if ui_base_url():
        return
    users = [name for name, on in (("alert messages", get_alert_enrichment_config().enabled), ("tickets", get_ticketing_config().enabled)) if on]
    if users:
        logger.warning(
            "OPS_SIGNALS_UI_BASE_URL is not set, so %s won't link to Ops Signals. Set it to the address people open the web UI at.",
            " and ".join(users),
        )


def ticketing_worker_enabled(config: TicketingConfig) -> bool:
    """The outbox worker only runs when ticketing is on; OPS_SIGNALS_TICKETING_WORKER_ENABLED=false
    turns it off even then (e.g. to run the worker in a separate process)."""
    worker_switch = os.getenv("OPS_SIGNALS_TICKETING_WORKER_ENABLED", "true").strip().lower() != "false"
    return config.enabled and worker_switch


def _needs_backfill(indexer: CaseMemoryIndexer) -> bool:
    try:
        return bool(indexer.vector_store.points_missing(SYMPTOM_VECTOR, limit=1))
    except Exception as e:
        logger.warning(f"Could not check for cases needing vector backfill: {e}")
        return False


def _backfill_vectors(indexer: CaseMemoryIndexer, session_local) -> None:
    try:
        with session_local() as db:
            indexer.backfill_vectors(db)
    except Exception as e:
        logger.warning(f"Vector backfill failed; older cases keep full-document recall until re-indexed: {e}")


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
        # A broken connections file stops startup instead of failing (or misrouting) a later query.
        get_prometheus_connections()
        init_engine(database_url)
        Base.metadata.create_all(bind=get_engine())
        ensure_server_defaults(get_engine())
        ensure_learning_schema(get_engine())
        ensure_ai_narrative_schema(get_engine())
        ensure_case_behavior_link_schema(get_engine())
        ensure_case_import_schema(get_engine())
        ensure_case_link_unique_schema(get_engine())
        ensure_autonomous_policy_scheduling_schema(get_engine())
        ensure_ticketing_schema(get_engine())
        ensure_cluster_schema(get_engine())
        ensure_finding_problem_schema(get_engine())
        ensure_problem_event_schema(get_engine())
        ensure_metric_usage_schema(get_engine())
        ensure_point_series_key_schema(get_engine())
        ensure_case_memory_schema(get_engine())
        ensure_actor_schema(get_engine())
        session_local = get_session_local()
        with session_local() as db:
            seed_reference_data(db)
        try:
            with session_local() as db:
                backfill_case_statuses(db)
        except Exception as e:
            logger.warning(f"Case status backfill failed; resolved cases may still count as open: {e}")

        # Load memory config at startup
        memory_tasks: list[asyncio.Task] = []
        memory_config = load_memory_config()
        memory_services["ai_config"] = load_ai_config()
        memory_services["config"] = memory_config

        def install_memory_services(services: tuple) -> bool:
            """Publishes started memory services to the API and starts their background jobs;
            False when they didn't start (Qdrant unreachable)."""
            (
                memory_services["vector_store"],
                memory_services["embedder"],
                memory_services["indexer"],
                memory_services["similarity_service"],
                memory_services["assistant"],
                memory_services["knowledge_bootstrap"],
            ) = services
            _publish_memory_services(memory_services)
            indexer = memory_services["indexer"]
            if indexer is None:
                return False
            memory_availability.mark(memory_availability.READY)
            memory_tasks.append(
                asyncio.create_task(
                    run_memory_catch_up_loop(indexer, memory_config, session_local, run_now=waiting_at_startup(session_local, memory_config))
                )
            )
            if _needs_backfill(indexer):
                # Cases indexed before symptom/resolution/keyword vectors get them, in the background:
                # it embeds each older case, and recall uses the full document until it is done.
                # Started only when there is something to fill, so a normal startup runs nothing.
                memory_tasks.append(asyncio.create_task(asyncio.to_thread(_backfill_vectors, indexer, session_local)))
            return True

        async def retry_memory_start() -> None:
            """Qdrant was unreachable at startup: keep trying, so memory comes up when Qdrant does
            instead of staying off until the backend is restarted."""
            delay = MEMORY_RETRY_FIRST_SECONDS
            while True:
                await asyncio.sleep(delay)
                if install_memory_services(await asyncio.to_thread(initialize_memory_services, memory_config)):
                    logger.info("✓ Operational memory connected after startup")
                    return
                delay = min(delay * 2, MEMORY_RETRY_MAX_SECONDS)

        if memory_config and memory_config.enabled:
            logger.info("Initializing operational memory services...")
            memory_availability.mark(memory_availability.STARTING)
            if install_memory_services(initialize_memory_services(memory_config)):
                logger.info(f"✓ Memory services initialized successfully")
            else:
                logger.warning("Operational memory is unavailable; retrying in the background")
                memory_tasks.append(asyncio.create_task(retry_memory_start()))
        else:
            memory_availability.mark(memory_availability.DISABLED)
            _publish_memory_services(memory_services)
            logger.info(f"Memory services disabled")

        # Slack notifications: config-driven, disabled unless OPS_SIGNALS_SLACK_ENABLED=true
        # and a webhook URL are both set. SlackNotifier no-ops internally when disabled, so
        # this registration is unconditional — one code path either way.
        slack_config = get_slack_config()
        slack_notifier = SlackNotifier(slack_config, session_local, background=True)
        register_findings_hook(slack_notifier.notify_findings, on_seen_again=slack_notifier.notify_seen_again)
        slack_task: asyncio.Task | None = None
        if slack_notifier.enabled:
            logger.info("Slack notifications enabled")
            slack_task = asyncio.create_task(run_slack_retry_loop(slack_notifier))
        else:
            logger.info("Slack notifications disabled")

        scheduler_task: asyncio.Task | None = None
        if os.getenv("OPS_SIGNALS_AUTONOMOUS_SCHEDULER_ENABLED", "true").lower() != "false":
            from backend.app.autonomous.scheduler import run_scheduler_loop

            scheduler_task = asyncio.create_task(run_scheduler_loop())
        else:
            logger.info("Autonomous policy scheduler disabled via OPS_SIGNALS_AUTONOMOUS_SCHEDULER_ENABLED")

        ticketing_task: asyncio.Task | None = None
        ticketing_config = get_ticketing_config()
        if ticketing_worker_enabled(ticketing_config):
            ticketing_service = get_ticketing_service(ticketing_config)
            ticketing_task = asyncio.create_task(
                run_ticketing_worker_loop(ticketing_service, ticketing_config.worker_poll_interval_seconds)
            )
        else:
            logger.info("Ticketing outbox worker not started (ticketing disabled or OPS_SIGNALS_TICKETING_WORKER_ENABLED=false)")

        yield

        for task in memory_tasks:
            if not task.done():
                task.cancel()
                with suppress(asyncio.CancelledError, Exception):
                    await task

        if slack_task is not None:
            slack_task.cancel()
            with suppress(asyncio.CancelledError):
                await slack_task
        # A first send still in flight finishes (bounded by the Slack timeout); its row stays in the outbox.
        await asyncio.to_thread(slack_notifier.close)
        if ticketing_task is not None:
            ticketing_task.cancel()
            with suppress(asyncio.CancelledError):
                await ticketing_task
        if scheduler_task is not None:
            scheduler_task.cancel()
            with suppress(asyncio.CancelledError):
                await scheduler_task

    warn_if_links_have_no_ui_address()
    security = get_security_config()
    if not security.api_token:
        logger.warning(
            "OPS_SIGNALS_API_TOKEN is not set: the API is open to anyone who can reach it. "
            "Only run it on a trusted network (docs/security-model.md)."
        )
    auth = get_auth_config()
    if auth.dev_user and not security.api_token:
        logger.warning("OPS_SIGNALS_DEV_USER is set: every request without a Grafana user acts as %s. For trying sign-in locally only.", auth.dev_user)
    elif auth.dev_user:
        logger.warning("OPS_SIGNALS_DEV_USER is ignored because OPS_SIGNALS_API_TOKEN is set.")
    if auth.mode == "proxy-headers" and not security.api_token:
        logger.warning("OPS_SIGNALS_AUTH_MODE=proxy-headers needs OPS_SIGNALS_API_TOKEN; the user headers are ignored until it is set.")
    if auth.mode == "oidc":
        problem = oidc_setup_problem(auth, security.api_token)
        if problem:
            logger.warning("Company sign-in can't turn on: %s", problem)
        else:
            logger.info("Company sign-in is on with %s", auth.oidc_issuer_url)
    # With an API token, the interactive API docs and the OpenAPI schema are off: FastAPI serves
    # them outside the token check, and a browser can't send the token to them anyway.
    docs_open = not security.api_token
    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        lifespan=lifespan,
        # The token first (who may call at all), then the Grafana user's role (what they may change),
        # then what demo mode turns off for visitors (backend/app/demo.py; nothing when it's off).
        dependencies=[Depends(require_api_token), Depends(require_grafana_role), Depends(refuse_in_demo)],
        docs_url="/docs" if docs_open else None,
        redoc_url="/redoc" if docs_open else None,
        openapi_url="/openapi.json" if docs_open else None,
    )
    app.add_exception_handler(Exception, unhandled_error)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=security.cors_origins,
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
    app.include_router(behavior_lab_router)
    app.include_router(capabilities_router)
    app.include_router(questions_router)
    app.include_router(signals_router)
    app.include_router(findings_router)
    app.include_router(case_imports_router)
    app.include_router(cases_router)
    app.include_router(ticketing_router)
    app.include_router(timeseries_router)
    app.include_router(metric_analyzer_recommendations_router)
    app.include_router(analyzer_router)
    app.include_router(analyzer_labs_router)
    app.include_router(analyzer_settings_router)
    app.include_router(autonomous_router)
    app.include_router(ingestion_router)
    app.include_router(ingestion_status_router)
    app.include_router(otlp_router)
    app.include_router(self_metrics_router)
    app.include_router(direct_prometheus_router)
    app.include_router(direct_prometheus_analysis_router)
    app.include_router(learning_outcomes_router)
    app.include_router(assistant_router)
    app.include_router(mcp_router)
    app.include_router(alerts_router)
    app.include_router(ai_router)
    app.include_router(demo_router)
    app.include_router(events_router)
    app.include_router(metric_usage_router)
    app.include_router(notifications_router)
    app.include_router(setup_check_router)
    app.include_router(me_router)
    app.include_router(auth_router)
    
    # Register memory router
    app.include_router(memory_router)

    # Wipes all findings, cases and memory: only for demos and test suites.
    if security.enable_testing_api:
        logger.warning("OPS_SIGNALS_ENABLE_TESTING_API is on: /api/testing/reset-operational-data can wipe all data")
        app.include_router(testing_router)

    return app


app = create_app()
