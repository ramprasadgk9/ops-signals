"""Memory management API endpoints for operational cases."""

import logging
from datetime import datetime, timezone
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, select

from backend.app.api.assistant import get_assistant
from backend.app.assistant.service import OperationalIntelligenceAssistant
from backend.app.config import MemoryConfig
from backend.app.memory.indexer import CaseMemoryIndexer
from backend.app.memory.schemas import (
    AlertContextResponse,
    MemoryHealthResponse,
    MemoryStatsResponse,
    MemoryChatRequest,
    MemoryChatResponse,
    MemoryChatSource,
    MemoryIndexResponse,
    MemoryStatusResponse,
    SimilarCasesResponse,
)
from backend.app.memory.alert_context import build_alert_context
from backend.app.memory.schemas import SeenBeforeResponse
from backend.app.memory.seen_before import find_seen_before
from backend.app.memory.similarity_service import SimilarityService
from backend.app.memory.vector_store import VectorStore
from backend.app.models.db import get_db
from backend.app.models.entities import FindingEntity, OperationalCaseEntity
from backend.app.memory.embedder import Embedder
from backend.app.memory.document_builder import CaseDocumentBuilder

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["memory"])

# Shared container for memory services - will be populated during app startup
_services = {
    "indexer": None,
    "similarity_service": None,
    "config": None,
    "vector_store": None,
    "embedder": None,
}


# Dependency for memory configuration and services
def get_memory_indexer(
    db: Session = Depends(get_db),
) -> CaseMemoryIndexer | None:
    """Get memory indexer if memory is enabled."""
    return _services["indexer"]


def get_similarity_service(
    db: Session = Depends(get_db),
) -> SimilarityService | None:
    """Get similarity service if memory is enabled."""
    return _services["similarity_service"]


def get_memory_config() -> MemoryConfig | None:
    """Get memory configuration."""
    return _services["config"]


def get_vector_store() -> VectorStore | None:
    """Get vector store."""
    return _services["vector_store"]


def get_embedder() -> Embedder | None:
    """Get embedder."""
    return _services.get("embedder")


@router.post("/cases/{case_id}/memory/index", response_model=MemoryIndexResponse)
async def index_case_memory(
    case_id: int,
    db: Session = Depends(get_db),
    indexer: CaseMemoryIndexer | None = Depends(get_memory_indexer),
    config: MemoryConfig | None = Depends(get_memory_config),
) -> MemoryIndexResponse:
    """Index a case into operational memory.

    Args:
        case_id: ID of the case to index
        db: Database session
        indexer: Memory indexer service
        config: Memory configuration

    Returns:
        MemoryIndexResponse with indexing status

    Raises:
        HTTPException: If memory is disabled, case not found, or indexing fails
    """
    if not config or not config.enabled:
        raise HTTPException(status_code=400, detail="Operational Memory is not enabled")

    if not indexer:
        raise HTTPException(status_code=503, detail="Memory indexer not initialized")

    # Load case
    case = db.execute(
        select(OperationalCaseEntity).where(OperationalCaseEntity.id == case_id)
    ).scalar_one_or_none()

    if not case:
        raise HTTPException(status_code=404, detail="Case not found")

    try:
        return indexer.index_case(case, db)
    except Exception as e:
        logger.error(f"Failed to index case {case_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Indexing failed: {str(e)}")


@router.delete("/cases/{case_id}/memory")
async def delete_case_memory(
    case_id: int,
    db: Session = Depends(get_db),
    indexer: CaseMemoryIndexer | None = Depends(get_memory_indexer),
    config: MemoryConfig | None = Depends(get_memory_config),
) -> dict:
    """Delete a case from operational memory.

    Args:
        case_id: ID of the case to delete
        db: Database session
        indexer: Memory indexer service
        config: Memory configuration

    Returns:
        Status dictionary

    Raises:
        HTTPException: If memory is disabled or case not found
    """
    if not config or not config.enabled:
        raise HTTPException(status_code=400, detail="Operational Memory is not enabled")

    if not indexer:
        raise HTTPException(status_code=503, detail="Memory indexer not initialized")

    # Load case
    case = db.execute(
        select(OperationalCaseEntity).where(OperationalCaseEntity.id == case_id)
    ).scalar_one_or_none()

    if not case:
        raise HTTPException(status_code=404, detail="Case not found")

    try:
        indexer.delete_memory(case, db)
        return {
            "status": "deleted",
            "case_id": case_id,
            "memory_status": case.memory_status,
        }
    except Exception as e:
        logger.error(f"Failed to delete case {case_id} from memory: {e}")
        raise HTTPException(status_code=500, detail=f"Deletion failed: {str(e)}")


@router.get("/cases/{case_id}/memory/status", response_model=MemoryStatusResponse)
async def get_case_memory_status(
    case_id: int,
    db: Session = Depends(get_db),
) -> MemoryStatusResponse:
    """Get memory status of a case.

    Args:
        case_id: ID of the case
        db: Database session

    Returns:
        MemoryStatusResponse with current memory status

    Raises:
        HTTPException: If case not found
    """
    case = db.execute(
        select(OperationalCaseEntity).where(OperationalCaseEntity.id == case_id)
    ).scalar_one_or_none()

    if not case:
        raise HTTPException(status_code=404, detail="Case not found")

    return MemoryStatusResponse(
        case_id=case.id,
        memory_status=case.memory_status,
        memory_indexed_at=case.memory_indexed_at,
        memory_content_version=case.memory_content_version,
        memory_error=case.memory_error,
    )


@router.get("/findings/{finding_id}/seen-before", response_model=SeenBeforeResponse)
def finding_seen_before(
    finding_id: int,
    db: Session = Depends(get_db),
    service: SimilarityService | None = Depends(get_similarity_service),
    embedder: Embedder | None = Depends(get_embedder),
    config: MemoryConfig | None = Depends(get_memory_config),
) -> SeenBeforeResponse:
    """Past cases (detected or imported) that look like this finding, ranked same service first.
    Works before any case is opened for the finding."""
    finding = db.get(FindingEntity, finding_id)
    if finding is None:
        raise HTTPException(status_code=404, detail="finding not found")
    enabled = bool(config and config.enabled)
    try:
        return find_seen_before(db, finding, service if enabled else None, embedder if enabled else None)
    except Exception as e:
        logger.warning(f"Seen-before search failed for finding {finding_id}: {e}")
        return SeenBeforeResponse(
            finding_id=finding_id, available=False, reason="Past cases could not be searched right now.", service=finding.service
        )


@router.get("/cases/{case_id}/similar", response_model=SimilarCasesResponse)
async def find_similar_cases(
    case_id: int,
    db: Session = Depends(get_db),
    service: SimilarityService | None = Depends(get_similarity_service),
    config: MemoryConfig | None = Depends(get_memory_config),
    top_k: Annotated[int | None, Query(ge=1, le=20)] = None,
    minimum_score: Annotated[float | None, Query(ge=0.0, le=1.0)] = None,
    same_service_only: bool | None = None,
) -> SimilarCasesResponse:
    """Find similar operational cases.

    Args:
        case_id: ID of the case to find similar cases for
        db: Database session
        service: Similarity service
        config: Memory configuration
        top_k: Maximum number of results (1-20)
        minimum_score: Minimum similarity score (0-1)
        same_service_only: Filter by same service

    Returns:
        SimilarCasesResponse with ranked similar cases

    Raises:
        HTTPException: If memory is disabled, case not found, or search fails
    """
    if not config or not config.enabled:
        raise HTTPException(status_code=400, detail="Operational Memory is not enabled")

    if not service:
        raise HTTPException(status_code=503, detail="Similarity service not initialized")

    try:
        return service.find_similar_cases(
            case_id=case_id,
            db=db,
            top_k=top_k,
            minimum_score=minimum_score,
            same_service_only=same_service_only,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to search similar cases for {case_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Search failed: {str(e)}")


@router.post("/memory/chat", response_model=MemoryChatResponse)
async def chat_memory(
    payload: MemoryChatRequest,
    db: Session = Depends(get_db),
    service: SimilarityService | None = Depends(get_similarity_service),
    config: MemoryConfig | None = Depends(get_memory_config),
    embedder: Embedder | None = Depends(get_embedder),
) -> MemoryChatResponse:
    """Answer a natural-language question using operational memory retrieval."""
    if not config or not config.enabled:
        raise HTTPException(status_code=400, detail="Operational Memory is not enabled")
    if not service or not embedder:
        raise HTTPException(status_code=503, detail="Memory services are not initialized")

    question = payload.message.strip()
    if not question:
        raise HTTPException(status_code=422, detail="Message cannot be empty")

    current_case = None
    if payload.case_id is not None:
        current_case = db.execute(
            select(OperationalCaseEntity).where(OperationalCaseEntity.id == payload.case_id)
        ).scalar_one_or_none()
        if not current_case:
            raise HTTPException(status_code=404, detail="Case not found")

    query_text = question
    if current_case:
        query_text = "\n".join(
            [
                "Operational case context:",
                CaseDocumentBuilder.build(current_case),
                "",
                f"User question: {question}",
            ]
        )

    try:
        vector = embedder.encode(query_text)
        filters = None
        if current_case:
            filters = service._build_filters(current_case, payload.same_service_only)

        search_results = service.vector_store.search(
            vector=vector,
            filters=filters,
            limit=payload.top_k * 2,
            score_threshold=payload.minimum_score,
        )

        if current_case:
            search_results = [
                result
                for result in search_results
                if result["payload"].get("case_id") != current_case.id
            ]

        filtered_results = search_results[: payload.top_k]
        source_case_ids = [result["payload"].get("case_id") for result in filtered_results if result["payload"].get("case_id")]
        matched_cases = db.execute(
            select(OperationalCaseEntity).where(OperationalCaseEntity.id.in_(source_case_ids))
        ).scalars().all() if source_case_ids else []
        case_by_id = {case.id: case for case in matched_cases}

        sources: list[MemoryChatSource] = []
        for result in filtered_results:
            case_id = result["payload"].get("case_id")
            if not case_id:
                continue
            matched_case = case_by_id.get(case_id)
            if not matched_case:
                continue
            sources.append(
                MemoryChatSource(
                    case_id=matched_case.id,
                    title=matched_case.case_title,
                    similarity_score=float(result["score"]),
                    service=result["payload"].get("service"),
                    metric_name=result["payload"].get("metric_name"),
                    category=result["payload"].get("category"),
                    case_status=matched_case.case_status,
                    root_cause_summary=matched_case.root_cause_summary,
                    outcome_summary=matched_case.outcome_summary,
                )
            )

        if sources:
            top = sources[0]
            answer_lines = [
                f"I found {len(sources)} related case{'s' if len(sources) != 1 else ''} in operational memory.",
                f"The closest match is case #{top.case_id} ({top.title}) with a similarity score of {top.similarity_score:.2f}.",
            ]
            if top.root_cause_summary:
                answer_lines.append(f"That case recorded this RCA summary: {top.root_cause_summary}")
            elif top.outcome_summary:
                answer_lines.append(f"That case recorded this outcome: {top.outcome_summary}")
            else:
                answer_lines.append("The match contains useful operational context, but no RCA or outcome summary yet.")
            answer_lines.append("Use the source cases below to inspect the evidence before treating this as a final conclusion.")
        else:
            answer_lines = [
                "I could not find a strong operational-memory match for that question.",
                "Try asking about a specific service, metric, or case, or lower the similarity threshold.",
            ]

        suggested_questions = [
            "Have we seen this before?",
            "What changed in the most similar case?",
            "Show the RCA for the closest match.",
        ]
        if current_case:
            suggested_questions.insert(0, "What changed compared with this case?")

        limitations = [
            "Answers are grounded in retrieved case memory, not direct root-cause proof.",
            "Chat does not change systems or perform remediation.",
            "Results depend on the quality of indexed case summaries and metadata.",
        ]

        return MemoryChatResponse(
            conversation_id=payload.conversation_id or uuid4(),
            answer="\n".join(answer_lines),
            limitations=limitations,
            suggested_questions=suggested_questions[:4],
            sources=sources,
        )
    except Exception as e:
        logger.error(f"Failed to answer memory chat request: {e}")
        raise HTTPException(status_code=500, detail=f"Chat failed: {str(e)}")


@router.get("/memory/health", response_model=MemoryHealthResponse)
async def get_memory_health(
    store: VectorStore | None = Depends(get_vector_store),
    config: MemoryConfig | None = Depends(get_memory_config),
) -> MemoryHealthResponse:
    """Get memory system health status.

    Args:
        store: Vector store
        config: Memory configuration

    Returns:
        MemoryHealthResponse with system health

    Raises:
        HTTPException: If memory is not initialized
    """
    if not config:
        return MemoryHealthResponse(
            enabled=False,
            provider="none",
            status="disabled",
            collection="",
            embedding_model="",
            dimension=0,
        )

    if not config.enabled:
        return MemoryHealthResponse(
            enabled=False,
            provider=config.vector_store.provider,
            status="disabled",
            collection=config.vector_store.collection_name,
            embedding_model=config.embedding.model,
            dimension=config.embedding.dimension,
        )

    if not store:
        return MemoryHealthResponse(
            enabled=True,
            provider=config.vector_store.provider,
            status="initializing",
            collection=config.vector_store.collection_name,
            embedding_model=config.embedding.model,
            dimension=config.embedding.dimension,
        )

    health = store.health()
    status_map = {"healthy": "healthy", "unhealthy": "unhealthy", "unknown": "unknown"}
    status = status_map.get(health.get("status", "unknown"), "unknown")

    return MemoryHealthResponse(
        enabled=True,
        provider=config.vector_store.provider,
        status=status,
        collection=config.vector_store.collection_name,
        embedding_model=config.embedding.model,
        dimension=config.embedding.dimension,
    )


@router.get("/memory/stats", response_model=MemoryStatsResponse)
async def get_memory_stats(
    db: Session = Depends(get_db),
    store: VectorStore | None = Depends(get_vector_store),
    config: MemoryConfig | None = Depends(get_memory_config),
) -> MemoryStatsResponse:
    """Return authoritative operational-memory counts from case metadata."""
    rows = db.execute(
        select(OperationalCaseEntity.memory_status, func.count()).group_by(OperationalCaseEntity.memory_status)
    ).all()
    counts = {str(memory_status): int(count) for memory_status, count in rows}

    if not config or not config.enabled:
        enabled = False
        status = "disabled"
    elif not store:
        enabled = True
        status = "initializing"
    else:
        health = store.health()
        status = str(health.get("status", "unknown"))
        enabled = True

    return MemoryStatsResponse(
        generated_at=datetime.now(timezone.utc),
        enabled=enabled,
        status=status,
        indexed_cases=counts.get("indexed", 0),
        not_indexed_cases=counts.get("not_indexed", 0),
        stale_cases=counts.get("stale", 0),
        error_cases=counts.get("error", 0),
        total_cases=sum(counts.values()),
    )


@router.get("/alert-context", response_model=AlertContextResponse)
def get_alert_context(
    metric_name: str,
    service: str | None = None,
    message: str | None = None,
    db: Session = Depends(get_db),
    similarity: SimilarityService | None = Depends(get_similarity_service),
    embedder: Embedder | None = Depends(get_embedder),
    assistant: OperationalIntelligenceAssistant | None = Depends(get_assistant),
) -> AlertContextResponse:
    """Decision-support lookup for an incoming alert, meant for an external
    alert manager to call before firing: has this service/metric fired before,
    was it real, and what similar cases (if any) were resolved.

    Works from Postgres learning outcomes alone (exact service+metric match);
    if `message` is given and operational memory is enabled, also runs a
    free-text semantic search over past cases - no prior case_id required.
    """
    return build_alert_context(
        db,
        metric_name=metric_name,
        service=service,
        message=message,
        similarity=similarity,
        embedder=embedder,
        assistant=assistant,
    )
