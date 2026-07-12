"""Memory management API endpoints for operational cases."""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from backend.app.config import MemoryConfig
from backend.app.memory.indexer import CaseMemoryIndexer
from backend.app.memory.schemas import (
    MemoryHealthResponse,
    MemoryIndexResponse,
    MemoryStatusResponse,
    SimilarCasesResponse,
)
from backend.app.memory.similarity_service import SimilarityService
from backend.app.memory.vector_store import VectorStore
from backend.app.models.db import get_db
from backend.app.models.entities import OperationalCaseEntity
from sqlalchemy import select

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["memory"])

# Shared container for memory services - will be populated during app startup
_services = {
    "indexer": None,
    "similarity_service": None,
    "config": None,
    "vector_store": None,
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
