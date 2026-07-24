from __future__ import annotations

from typing import Any

import yaml
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from qdrant_client import QdrantClient
from sqlalchemy import delete
from sqlalchemy.orm import Session

from backend.app.config import MemoryConfig
from backend.app.memory.qdrant_initializer import QdrantInitializer
from backend.app.models.db import get_db
from backend.app.models.entities import (
    AnalysisRunEntity,
    AnalyzerLearningOutcomeEntity,
    BehaviorFindingEntity,
    FindingEntity,
    NormalizedPoint,
    OperationalCaseEntity,
    QuestionAnswerEntity,
    SignalEntity,
)


router = APIRouter(prefix="/api/testing", tags=["testing"])


class TestingResetRequest(BaseModel):
    confirm: str
    clear_vector_memory: bool = True


class TestingResetResponse(BaseModel):
    status: str
    deleted_rows: dict[str, int]
    vector_memory: dict[str, Any]


@router.post("/reset-operational-data", response_model=TestingResetResponse)
def reset_operational_data(payload: TestingResetRequest, db: Session = Depends(get_db)) -> TestingResetResponse:
    if payload.confirm != "RESET_OPS_SIGNALS_TEST_DATA":
        raise HTTPException(status_code=400, detail="Invalid confirmation token for testing reset")

    deleted_rows: dict[str, int] = {}
    for entity in (
        AnalyzerLearningOutcomeEntity,
        QuestionAnswerEntity,
        BehaviorFindingEntity,
        OperationalCaseEntity,
        FindingEntity,
        SignalEntity,
        NormalizedPoint,
        AnalysisRunEntity,
    ):
        result = db.execute(delete(entity))
        deleted_rows[entity.__tablename__] = int(result.rowcount or 0)
    db.commit()

    vector_result: dict[str, Any] = {"skipped": not payload.clear_vector_memory}
    if payload.clear_vector_memory:
        vector_result = _clear_case_vector_memory()

    return TestingResetResponse(status="reset", deleted_rows=deleted_rows, vector_memory=vector_result)


def _clear_case_vector_memory() -> dict[str, Any]:
    memory_config = _load_memory_config()
    if not memory_config or not memory_config.enabled:
        return {"status": "skipped", "reason": "memory is not enabled"}

    client = QdrantClient(
        url=memory_config.vector_store.url,
        api_key=memory_config.vector_store.api_key,
    )
    collection_name = memory_config.vector_store.collection_name
    try:
        collections = client.get_collections()
        if any(collection.name == collection_name for collection in collections.collections):
            client.delete_collection(collection_name=collection_name)
        init_result = QdrantInitializer.initialize(client)
        return {"status": "cleared", "collection": collection_name, "reinitialized": init_result}
    except Exception as exc:  # pragma: no cover - depends on local Qdrant availability
        return {"status": "failed", "collection": collection_name, "error": str(exc)}


def _load_memory_config() -> MemoryConfig | None:
    try:
        with open("config.yaml") as handle:
            config_data = yaml.safe_load(handle) or {}
        if "memory" in config_data:
            return MemoryConfig(**config_data["memory"])
    except Exception:
        return None
    return None
