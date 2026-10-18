from __future__ import annotations

from dataclasses import asdict
from uuid import uuid4
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import inspect, select, distinct, text
from sqlalchemy.orm import Session

from backend.app.api.cases import _to_case_out
from backend.app.api.errors import memory_error, memory_not_ready
from backend.app.api.findings import _to_finding_out
from backend.app.assistant.schemas import AssistantChatRequest
from backend.app.metric_analyzer_recommendations.api import _analyzer_config
from backend.app.metric_analyzer_recommendations.schemas import (
    AnalyzerRecommendationOut,
    MetricProfileOut,
    MetricSampleOut,
    RecommendationResponseOut,
)
from backend.app.metric_analyzer_recommendations.service import MetricAnalyzerRecommendationService
from backend.app.memory.schemas import MemoryChatRequest
from backend.app.memory.chat_answer import chat_answer_lines
from backend.app.memory.similarity_service import match_strength
from backend.app.models.db import get_db
from backend.app.models.entities import FindingEntity, OperationalCaseEntity, NormalizedPoint
from backend.app.questions.composer import AnswerComposer
from backend.app.questions.router import QuestionRouter
from backend.app.models.api_schema import INVESTIGATION_STATUSES, OUTCOME_STATUSES, ROOT_CAUSE_STATUSES

router = APIRouter(prefix="/api/mcp", tags=["mcp"])

_recommendation_service = MetricAnalyzerRecommendationService()

_READ_ONLY_TOOLS = {
    "health",
    "services",
    "service_metrics",
    "findings",
    "finding",
    "cases",
    "case",
    "analysis_runs",
    "analysis_run",
    "similar_cases",
    "memory_status",
    "assistant_knowledge_status",
}

_TOOL_SCHEMAS: dict[str, dict[str, Any]] = {
    "health": {"type": "object", "properties": {}, "additionalProperties": False},
    "services": {"type": "object", "properties": {}, "additionalProperties": False},
    "service_metrics": {
        "type": "object",
        "properties": {"service": {"type": "string"}},
        "required": ["service"],
        "additionalProperties": False,
    },
    "findings": {
        "type": "object",
        "properties": {
            "service": {"type": "string"},
            "metric_name": {"type": "string"},
            "health_status": {"type": "string"},
            "category": {"type": "string"},
            "analysis_run_id": {"type": "string"},
        },
        "additionalProperties": False,
    },
    "finding": {
        "type": "object",
        "properties": {"finding_id": {"type": "integer"}},
        "required": ["finding_id"],
        "additionalProperties": False,
    },
    "cases": {
        "type": "object",
        "properties": {
            "service": {"type": "string"},
            "metric_name": {"type": "string"},
            "limit": {"type": "integer", "minimum": 1, "maximum": 200},
        },
        "additionalProperties": False,
    },
    "case": {
        "type": "object",
        "properties": {"case_id": {"type": "integer"}},
        "required": ["case_id"],
        "additionalProperties": False,
    },
    "analysis_runs": {"type": "object", "properties": {}, "additionalProperties": False},
    "analysis_run": {
        "type": "object",
        "properties": {"run_id": {"type": "string"}},
        "required": ["run_id"],
        "additionalProperties": False,
    },
    "similar_cases": {
        "type": "object",
        "properties": {
            "case_id": {"type": "integer"},
            "top_k": {"type": "integer", "minimum": 1, "maximum": 20},
            "minimum_score": {"type": "number", "minimum": 0.0, "maximum": 1.0},
            "same_service_only": {"type": "boolean"},
        },
        "required": ["case_id"],
        "additionalProperties": False,
    },
    "memory_status": {
        "type": "object",
        "properties": {"case_id": {"type": "integer"}},
        "required": ["case_id"],
        "additionalProperties": False,
    },
    "assistant_knowledge_status": {"type": "object", "properties": {}, "additionalProperties": False},
    "memory_chat": {
        "type": "object",
        "properties": {
            "conversation_id": {"type": "string"},
            "message": {"type": "string"},
            "case_id": {"type": "integer"},
            "top_k": {"type": "integer", "minimum": 1, "maximum": 10},
            "minimum_score": {"type": "number", "minimum": 0.0, "maximum": 1.0},
            "same_service_only": {"type": "boolean"},
        },
        "required": ["message"],
        "additionalProperties": False,
    },
    "assistant_chat": {
        "type": "object",
        "properties": {
            "conversation_id": {"type": "string"},
            "message": {"type": "string"},
            "case_id": {"type": "integer"},
        },
        "required": ["message"],
        "additionalProperties": False,
    },
    "create_case_from_finding": {
        "type": "object",
        "properties": {"finding_id": {"type": "integer"}},
        "required": ["finding_id"],
        "additionalProperties": False,
    },
    "index_case_memory": {
        "type": "object",
        "properties": {"case_id": {"type": "integer"}},
        "required": ["case_id"],
        "additionalProperties": False,
    },
    "update_investigation": {
        "type": "object",
        "properties": {
            "case_id": {"type": "integer"},
            "payload": {
                "type": "object",
                "properties": {
                    "investigation_status": {"type": "string", "enum": list(INVESTIGATION_STATUSES)},
                    "investigation_note": {"type": "string"},
                },
                "required": ["investigation_status"],
                "additionalProperties": False,
            },
        },
        "required": ["case_id", "payload"],
        "additionalProperties": False,
    },
    "update_rca": {
        "type": "object",
        "properties": {
            "case_id": {"type": "integer"},
            "payload": {
                "type": "object",
                "properties": {
                    "root_cause_status": {"type": "string", "enum": list(ROOT_CAUSE_STATUSES)},
                    "root_cause_summary": {"type": "string"},
                    "root_cause_confidence": {"type": "number", "minimum": 0, "maximum": 1},
                    "root_cause_verified": {"type": "boolean"},
                },
                "required": ["root_cause_status"],
                "additionalProperties": False,
            },
        },
        "required": ["case_id", "payload"],
        "additionalProperties": False,
    },
    "update_resolution": {
        "type": "object",
        "properties": {
            "case_id": {"type": "integer"},
            "payload": {
                "type": "object",
                "properties": {
                    "outcome_status": {"type": "string", "enum": list(OUTCOME_STATUSES)},
                    "outcome_summary": {"type": "string"},
                    "corrective_action": {"type": "string"},
                    "learning_outcome_status": {
                        "type": "string",
                        "enum": ["confirmed", "partially_confirmed", "rejected", "inconclusive"],
                    },
                    "root_cause_category": {"type": "string"},
                    "resolution_summary": {"type": "string"},
                    "resolved_by": {"type": "string"},
                },
                "required": ["outcome_status"],
                "additionalProperties": False,
            },
        },
        "required": ["case_id", "payload"],
        "additionalProperties": False,
    },
    "analyzer_recommendation": {
        "type": "object",
        "properties": {
            "service": {"type": "string"},
            "metric_name": {"type": "string"},
            "analysis_run_id": {"type": "string"},
        },
        "required": ["service", "metric_name"],
        "additionalProperties": False,
    },
    "question_answer": {
        "type": "object",
        "properties": {
            "question_id": {"type": "string"},
            "service": {"type": "string"},
            "metric_name": {"type": "string"},
            "analysis_run_id": {"type": "string"},
        },
        "required": ["question_id", "service", "metric_name", "analysis_run_id"],
        "additionalProperties": False,
    },
}


@router.get("/tools")
def list_tools() -> list[dict[str, Any]]:
    return [
        {
            "name": "health",
            "method": "GET",
            "path": "/api/health",
            "kind": "read",
            "description": "Check the backend and its database.",
            "inputSchema": _TOOL_SCHEMAS["health"],
        },
        {
            "name": "services",
            "method": "GET",
            "path": "/api/services",
            "kind": "read",
            "description": "List known services from normalized data.",
            "inputSchema": _TOOL_SCHEMAS["services"],
        },
        {
            "name": "service_metrics",
            "method": "GET",
            "path": "/api/services/{service}/metrics",
            "kind": "read",
            "description": "List metrics for a service.",
            "inputSchema": _TOOL_SCHEMAS["service_metrics"],
        },
        {
            "name": "findings",
            "method": "GET",
            "path": "/api/findings",
            "kind": "read",
            "description": "List operational findings with optional filters.",
            "inputSchema": _TOOL_SCHEMAS["findings"],
        },
        {
            "name": "finding",
            "method": "GET",
            "path": "/api/findings/{finding_id}",
            "kind": "read",
            "description": "Fetch a single finding by id.",
            "inputSchema": _TOOL_SCHEMAS["finding"],
        },
        {
            "name": "cases",
            "method": "GET",
            "path": "/api/cases",
            "kind": "read",
            "description": "List operational cases with optional filters.",
            "inputSchema": _TOOL_SCHEMAS["cases"],
        },
        {
            "name": "case",
            "method": "GET",
            "path": "/api/cases/{case_id}",
            "kind": "read",
            "description": "Fetch a single case by id.",
            "inputSchema": _TOOL_SCHEMAS["case"],
        },
        {
            "name": "analysis_runs",
            "method": "GET",
            "path": "/api/analysis-runs",
            "kind": "read",
            "description": "List analysis runs with routing metadata.",
            "inputSchema": _TOOL_SCHEMAS["analysis_runs"],
        },
        {
            "name": "analysis_run",
            "method": "GET",
            "path": "/api/analysis-runs/{run_id}",
            "kind": "read",
            "description": "Fetch a single analysis run by id.",
            "inputSchema": _TOOL_SCHEMAS["analysis_run"],
        },
        {
            "name": "similar_cases",
            "method": "GET",
            "path": "/api/cases/{case_id}/similar",
            "kind": "read",
            "description": "Find similar cases for a source case.",
            "inputSchema": _TOOL_SCHEMAS["similar_cases"],
        },
        {
            "name": "memory_status",
            "method": "GET",
            "path": "/api/cases/{case_id}/memory/status",
            "kind": "read",
            "description": "Inspect operational memory status for a case.",
            "inputSchema": _TOOL_SCHEMAS["memory_status"],
        },
        {
            "name": "assistant_knowledge_status",
            "method": "GET",
            "path": "/api/assistant/knowledge/status",
            "kind": "read",
            "description": "Inspect assistant knowledge bootstrap status.",
            "inputSchema": _TOOL_SCHEMAS["assistant_knowledge_status"],
        },
        {
            "name": "memory_chat",
            "method": "POST",
            "path": "/api/memory/chat",
            "kind": "action",
            "description": "Ask a retrieval-backed question over operational memory.",
            "inputSchema": _TOOL_SCHEMAS["memory_chat"],
        },
        {
            "name": "assistant_chat",
            "method": "POST",
            "path": "/api/assistant/chat",
            "kind": "action",
            "description": "Ask the unified assistant.",
            "inputSchema": _TOOL_SCHEMAS["assistant_chat"],
        },
        {
            "name": "create_case_from_finding",
            "method": "POST",
            "path": "/api/cases/findings/{finding_id}/create",
            "kind": "action",
            "description": "Promote a finding into a case.",
            "inputSchema": _TOOL_SCHEMAS["create_case_from_finding"],
        },
        {
            "name": "index_case_memory",
            "method": "POST",
            "path": "/api/cases/{case_id}/memory/index",
            "kind": "action",
            "description": "Index a case into operational memory.",
            "inputSchema": _TOOL_SCHEMAS["index_case_memory"],
        },
        {
            "name": "update_investigation",
            "method": "PATCH",
            "path": "/api/cases/{case_id}/investigation",
            "kind": "action",
            "description": "Update investigation state and notes.",
            "inputSchema": _TOOL_SCHEMAS["update_investigation"],
        },
        {
            "name": "update_rca",
            "method": "PATCH",
            "path": "/api/cases/{case_id}/rca",
            "kind": "action",
            "description": "Update root-cause analysis fields.",
            "inputSchema": _TOOL_SCHEMAS["update_rca"],
        },
        {
            "name": "update_resolution",
            "method": "PATCH",
            "path": "/api/cases/{case_id}/resolution",
            "kind": "action",
            "description": "Update resolution, outcome, and learning outcome data.",
            "inputSchema": _TOOL_SCHEMAS["update_resolution"],
        },
        {
            "name": "analyzer_recommendation",
            "method": "POST",
            "path": "/api/metric-analyzer-recommendations/evaluate",
            "kind": "action",
            "description": "Evaluate analyzer recommendations for a metric sample.",
            "inputSchema": _TOOL_SCHEMAS["analyzer_recommendation"],
        },
        {
            "name": "question_answer",
            "method": "POST",
            "path": "/api/questions/answer",
            "kind": "action",
            "description": "Answer a routed operational question.",
            "inputSchema": _TOOL_SCHEMAS["question_answer"],
        },
    ]


def list_read_only_tools() -> list[dict[str, Any]]:
    return [tool for tool in list_tools() if tool["name"] in _READ_ONLY_TOOLS]


@router.get("/services")
def list_services(db: Session = Depends(get_db)) -> list[str]:
    rows = db.execute(select(distinct(NormalizedPoint.service))).all()
    return [row[0] for row in rows if row[0]]


@router.get("/services/{service}/metrics")
def list_metrics(service: str, db: Session = Depends(get_db)) -> list[str]:
    rows = db.execute(
        select(distinct(NormalizedPoint.metric_name)).where(NormalizedPoint.service == service)
    ).all()
    return [row[0] for row in rows if row[0]]


@router.get("/findings")
def list_findings(
    service: str | None = None,
    metric_name: str | None = None,
    health_status: str | None = None,
    category: str | None = None,
    analysis_run_id: str | None = None,
    db: Session = Depends(get_db),
) -> list[Any]:
    query = select(FindingEntity)
    if service:
        query = query.where(FindingEntity.service == service)
    if metric_name:
        query = query.where(FindingEntity.metric_name == metric_name)
    if health_status:
        query = query.where(FindingEntity.health_status == health_status)
    if category:
        query = query.where(FindingEntity.category == category)
    if analysis_run_id:
        query = query.where(FindingEntity.analysis_run_id == analysis_run_id)
    rows = db.execute(query.order_by(FindingEntity.importance_score.desc())).scalars().all()
    return [_to_finding_out(row) for row in rows]


@router.get("/findings/{finding_id}")
def get_finding(finding_id: int, db: Session = Depends(get_db)) -> Any:
    row = db.execute(select(FindingEntity).where(FindingEntity.id == finding_id)).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="finding not found")
    return _to_finding_out(row)


@router.get("/cases")
def list_cases(service: str | None = None, metric_name: str | None = None, limit: int = 25, db: Session = Depends(get_db)) -> list[Any]:
    capped_limit = max(1, min(limit, 200))
    cases = db.execute(select(OperationalCaseEntity).order_by(OperationalCaseEntity.updated_at.desc()).limit(capped_limit)).scalars().all()
    filtered: list[OperationalCaseEntity] = []
    for case in cases:
        snapshot = case.finding_snapshot or {}
        if service and snapshot.get("service") != service:
            continue
        if metric_name and snapshot.get("metric_name") != metric_name:
            continue
        filtered.append(case)
    return [_to_case_out(case) for case in filtered]


@router.get("/cases/{case_id}")
def get_case(case_id: int, db: Session = Depends(get_db)) -> Any:
    case = db.execute(select(OperationalCaseEntity).where(OperationalCaseEntity.id == case_id)).scalar_one_or_none()
    if case is None:
        raise HTTPException(status_code=404, detail="case not found")
    return _to_case_out(case)


@router.get("/analysis-runs")
def list_analysis_runs(db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    engine = db.get_bind()
    columns = {column["name"] for column in inspect(engine).get_columns("analysis_runs")}
    select_columns = ["id", "source_type", "provider", "service", "metric_name", "start_time", "end_time", "sample_count", "status", "created_at"]
    for optional in ["file_name", "router_version", "feature_extractor_version", "analyzer_registry_version", "series_profile_json", "router_decisions_json", "executed_analyzers_json", "generated_findings_json"]:
        if optional in columns:
            select_columns.insert(2 if optional == "file_name" else len(select_columns), optional)
    rows = db.execute(text(f"SELECT {', '.join(select_columns)} FROM analysis_runs ORDER BY created_at DESC")).mappings().all()
    return [dict(row) for row in rows]


@router.get("/analysis-runs/{run_id}")
def get_analysis_run(run_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    engine = db.get_bind()
    columns = {column["name"] for column in inspect(engine).get_columns("analysis_runs")}
    select_columns = ["id", "source_type", "provider", "service", "metric_name", "start_time", "end_time", "sample_count", "status", "created_at"]
    for optional in ["file_name", "router_version", "feature_extractor_version", "analyzer_registry_version", "series_profile_json", "router_decisions_json", "executed_analyzers_json", "generated_findings_json"]:
        if optional in columns:
            select_columns.insert(2 if optional == "file_name" else len(select_columns), optional)
    row = db.execute(text(f"SELECT {', '.join(select_columns)} FROM analysis_runs WHERE id = :run_id"), {"run_id": run_id}).mappings().one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="analysis run not found")
    return dict(row)


@router.get("/cases/{case_id}/similar")
def find_similar_cases(
    case_id: int,
    db: Session = Depends(get_db),
    top_k: int | None = Query(default=None, ge=1, le=20),
    minimum_score: float | None = Query(default=None, ge=0.0, le=1.0),
    same_service_only: bool | None = None,
) -> Any:
    from backend.app.api import memory as memory_module

    service = memory_module._services["similarity_service"]
    config = memory_module._services["config"]
    if not config or not config.enabled:
        raise HTTPException(status_code=400, detail="Operational Memory is not enabled")
    if not service:
        raise memory_not_ready("Similarity service not initialized")
    try:
        return service.find_similar_cases(case_id=case_id, db=db, top_k=top_k, minimum_score=minimum_score, same_service_only=same_service_only)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise memory_error("Search failed", exc) from exc


@router.get("/cases/{case_id}/memory/status")
def get_case_memory_status(case_id: int, db: Session = Depends(get_db)) -> dict[str, Any]:
    case = db.execute(select(OperationalCaseEntity).where(OperationalCaseEntity.id == case_id)).scalar_one_or_none()
    if not case:
        raise HTTPException(status_code=404, detail="case not found")
    return {
        "case_id": case.id,
        "memory_status": case.memory_status,
        "memory_indexed_at": case.memory_indexed_at,
        "memory_content_version": case.memory_content_version,
        "memory_error": case.memory_error,
    }


@router.get("/assistant/knowledge/status")
def assistant_knowledge_status() -> dict[str, Any]:
    from backend.app.api import assistant as assistant_module

    bootstrap = assistant_module._services["knowledge_bootstrap"]
    if not bootstrap:
        raise HTTPException(status_code=503, detail="Assistant knowledge bootstrap is not initialized")
    return bootstrap.get_status().model_dump()


@router.post("/memory/chat")
def memory_chat(payload: MemoryChatRequest, db: Session = Depends(get_db)) -> Any:
    try:
        return _memory_chat(payload, db)
    except HTTPException:
        raise
    except Exception as exc:
        raise memory_error("Chat failed", exc) from exc


def _memory_chat(payload: MemoryChatRequest, db: Session) -> Any:
    from backend.app.api import memory as memory_module
    from backend.app.memory.document_builder import CaseDocumentBuilder
    from backend.app.memory.schemas import MemoryChatResponse, MemoryChatSource
    from backend.app.models.entities import OperationalCaseEntity

    config = memory_module._services["config"]
    service = memory_module._services["similarity_service"]
    embedder = memory_module._services["embedder"]
    if not config or not config.enabled:
        raise HTTPException(status_code=400, detail="Operational Memory is not enabled")
    if not service or not embedder:
        raise memory_not_ready("Memory services are not initialized")

    question = payload.message.strip()
    if not question:
        raise HTTPException(status_code=422, detail="Message cannot be empty")

    current_case = None
    if payload.case_id is not None:
        current_case = db.execute(select(OperationalCaseEntity).where(OperationalCaseEntity.id == payload.case_id)).scalar_one_or_none()
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
        search_results = [result for result in search_results if result["payload"].get("case_id") != current_case.id]

    filtered_results = search_results[: payload.top_k]
    source_case_ids = [result["payload"].get("case_id") for result in filtered_results if result["payload"].get("case_id")]
    matched_cases = db.execute(select(OperationalCaseEntity).where(OperationalCaseEntity.id.in_(source_case_ids))).scalars().all() if source_case_ids else []
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
                strength=match_strength(float(result["score"])),
                service=result["payload"].get("service"),
                metric_name=result["payload"].get("metric_name"),
                category=result["payload"].get("category"),
                case_status=matched_case.case_status,
                root_cause_summary=matched_case.root_cause_summary,
                outcome_summary=matched_case.outcome_summary,
            )
        )

    answer_lines = chat_answer_lines(sources)

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


@router.post("/assistant/chat")
def assistant_chat(payload: AssistantChatRequest, db: Session = Depends(get_db)) -> Any:
    from backend.app.api import assistant as assistant_module

    assistant = assistant_module._services["assistant"]
    if not assistant:
        raise HTTPException(status_code=503, detail="Assistant is not initialized")
    return assistant.chat(payload, db)


@router.post("/cases/findings/{finding_id}/create")
def create_case_from_finding(finding_id: int, db: Session = Depends(get_db)) -> dict[str, Any]:
    from backend.app.api.cases import create_case_from_finding as create_case

    return create_case(finding_id, db)


@router.post("/cases/{case_id}/memory/index")
def index_case_memory(case_id: int, db: Session = Depends(get_db)) -> Any:
    from backend.app.api import memory as memory_module

    config = memory_module._services["config"]
    indexer = memory_module._services["indexer"]
    if not config or not config.enabled:
        raise HTTPException(status_code=400, detail="Operational Memory is not enabled")
    if not indexer:
        raise memory_not_ready("Memory indexer not initialized")
    case = db.execute(select(OperationalCaseEntity).where(OperationalCaseEntity.id == case_id)).scalar_one_or_none()
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")
    return indexer.index_case(case, db)


@router.patch("/cases/{case_id}/investigation")
def update_investigation(case_id: int, payload: dict[str, Any], db: Session = Depends(get_db)) -> Any:
    from backend.app.api.cases import update_investigation as update_case_investigation
    from backend.app.models.api_schema import InvestigationUpdateRequest

    return update_case_investigation(case_id, InvestigationUpdateRequest(**payload), db)


@router.patch("/cases/{case_id}/rca")
def update_rca(case_id: int, payload: dict[str, Any], db: Session = Depends(get_db)) -> Any:
    from backend.app.api.cases import update_root_cause_analysis as update_case_rca
    from backend.app.models.api_schema import RCAUpdateRequest

    return update_case_rca(case_id, RCAUpdateRequest(**payload), db)


@router.patch("/cases/{case_id}/resolution")
def update_resolution(case_id: int, payload: dict[str, Any], db: Session = Depends(get_db)) -> Any:
    from backend.app.api.cases import update_resolution as update_case_resolution
    from backend.app.models.api_schema import ResolutionUpdateRequest

    return update_case_resolution(case_id, ResolutionUpdateRequest(**payload), db)


@router.post("/metric-analyzer-recommendations/evaluate")
def evaluate_metric_sample(payload: dict[str, Any], db: Session = Depends(get_db)) -> RecommendationResponseOut:
    service_name = str(payload.get("service", "")).strip()
    metric_name = str(payload.get("metric_name", "")).strip()
    analysis_run_id = payload.get("analysis_run_id")
    if analysis_run_id is not None:
        analysis_run_id = str(analysis_run_id).strip() or None
    if not service_name or not metric_name:
        raise HTTPException(status_code=400, detail="service and metric_name are required")
    sample = _recommendation_service.find_sample(db, service_name, metric_name, analysis_run_id)
    if not sample:
        raise HTTPException(status_code=404, detail="sample not found")
    try:
        profile, timeseries = _recommendation_service.profile_sample(db, service_name, metric_name, sample["analysis_run_id"])
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    analysis_config = _analyzer_config.get("analysis", {}) if isinstance(_analyzer_config, dict) else {}
    selection_mode = str(analysis_config.get("recommendation_selection_mode", "all"))
    selected_analyzers = list(analysis_config.get("selected_analyzers", []) or [])
    recommendations = [AnalyzerRecommendationOut(**item) for item in _recommendation_service.recommend(profile, selection_mode, selected_analyzers, timeseries)]
    return RecommendationResponseOut(
        sample=MetricSampleOut(**sample),
        profile=MetricProfileOut(**asdict(profile)),
        recommendations=recommendations,
    )


@router.post("/questions/answer")
def answer_question(payload: dict[str, Any], db: Session = Depends(get_db)) -> Any:
    routed = QuestionRouter(db).route(
        question_id=payload["question_id"],
        service=payload["service"],
        metric_name=payload["metric_name"],
        analysis_run_id=payload["analysis_run_id"],
    )
    signal_dicts = [
        {
            "id": sig.signal_id,
            "signal_type": sig.signal_type,
            "analyzer_id": sig.analyzer_id,
            "severity": sig.severity,
            "confidence": sig.confidence,
            "importance_score": sig.importance_score,
            "summary": sig.summary,
            "evidence": sig.evidence_json or {},
        }
        for sig in routed.signals
    ]
    return AnswerComposer().compose(payload["question_id"], signal_dicts)
