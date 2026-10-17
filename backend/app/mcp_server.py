from __future__ import annotations

import json
import sys
from dataclasses import asdict
from typing import Any
from uuid import uuid4

from sqlalchemy import distinct, inspect, select, text

from backend.app.api.cases import _to_case_out
from backend.app.api.findings import _to_finding_out
from backend.app.api.mcp import list_tools as list_http_tools
from backend.app.api.mcp import list_read_only_tools as list_read_only_http_tools
from backend.app.api.mcp import _recommendation_service
from backend.app.api.services import database_reachable
from backend.app.assistant.schemas import AssistantChatRequest
from backend.app.memory.diversity import leaders_only
from backend.app.memory.document_builder import CaseDocumentBuilder
from backend.app.memory.recall_scoring import RecallBoost
from backend.app.memory.schemas import MemoryChatRequest
from backend.app.mcp_runtime import initialize_memory_services, load_memory_config
from backend.app.metric_analyzer_recommendations.api import _analyzer_config
from backend.app.metric_analyzer_recommendations.schemas import AnalyzerRecommendationOut, MetricProfileOut, MetricSampleOut, RecommendationResponseOut
from backend.app.metric_analyzer_recommendations.service import MetricAnalyzerRecommendationService
from backend.app.models.db import get_db, init_engine
from backend.app.models.entities import FindingEntity, OperationalCaseEntity, NormalizedPoint
from backend.app.questions.composer import AnswerComposer
from backend.app.questions.router import QuestionRouter
from backend.app.models.api_schema import InvestigationUpdateRequest, RCAUpdateRequest, ResolutionUpdateRequest
from backend.app.api.cases import update_investigation, update_root_cause_analysis, update_resolution, create_case_from_finding


_memory_config = None
_memory_services: dict[str, Any] = {
    "vector_store": None,
    "embedder": None,
    "indexer": None,
    "similarity_service": None,
    "assistant": None,
    "knowledge_bootstrap": None,
}


def _ensure_runtime() -> None:
    global _memory_config
    if _memory_config is not None:
        return
    init_engine()
    _memory_config = load_memory_config()


def _ensure_memory_services() -> None:
    if _memory_services["assistant"] is not None or not _memory_config or not _memory_config.enabled:
        return
    (
        _memory_services["vector_store"],
        _memory_services["embedder"],
        _memory_services["indexer"],
        _memory_services["similarity_service"],
        _memory_services["assistant"],
        _memory_services["knowledge_bootstrap"],
    ) = initialize_memory_services(_memory_config)


def _json_default(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if hasattr(value, "__dict__"):
        return asdict(value) if hasattr(value, "__dataclass_fields__") else value.__dict__
    return str(value)


def _result(payload: Any, *, is_error: bool = False) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "result" if not is_error else "error": payload,
    }


def _tools_list(read_only_only: bool) -> dict[str, Any]:
    tools = list_read_only_http_tools() if read_only_only else list_http_tools()
    return {
        "tools": [
            {
                "name": tool["name"],
                "description": tool["description"],
                "inputSchema": tool["inputSchema"],
            }
            for tool in tools
        ]
    }


def _call_tool(name: str, arguments: dict[str, Any]) -> Any:
    _ensure_runtime()
    db_gen = get_db()
    db = next(db_gen)
    try:
        if name == "health":
            return {"status": "ok", "database": "ok"} if database_reachable() else {"status": "degraded", "database": "unavailable"}
        if name == "services":
            rows = db.execute(select(distinct(NormalizedPoint.service))).all()
            return [row[0] for row in rows if row[0]]
        if name == "service_metrics":
            rows = db.execute(select(distinct(NormalizedPoint.metric_name)).where(NormalizedPoint.service == arguments["service"])).all()
            return [row[0] for row in rows if row[0]]
        if name == "findings":
            query = select(FindingEntity)
            for key, col in [("service", FindingEntity.service), ("metric_name", FindingEntity.metric_name), ("health_status", FindingEntity.health_status), ("category", FindingEntity.category), ("analysis_run_id", FindingEntity.analysis_run_id)]:
                if arguments.get(key):
                    query = query.where(col == arguments[key])
            rows = db.execute(query.order_by(FindingEntity.importance_score.desc())).scalars().all()
            return [_to_finding_out(row).model_dump() for row in rows]
        if name == "finding":
            row = db.execute(select(FindingEntity).where(FindingEntity.id == arguments["finding_id"])).scalar_one_or_none()
            if not row:
                raise ValueError("finding not found")
            return _to_finding_out(row).model_dump()
        if name == "cases":
            cases = db.execute(select(OperationalCaseEntity).order_by(OperationalCaseEntity.updated_at.desc()).limit(min(max(arguments.get("limit", 25), 1), 200))).scalars().all()
            return [_to_case_out(case).model_dump() for case in cases]
        if name == "case":
            case = db.execute(select(OperationalCaseEntity).where(OperationalCaseEntity.id == arguments["case_id"])).scalar_one_or_none()
            if not case:
                raise ValueError("case not found")
            return _to_case_out(case).model_dump()
        if name == "analysis_runs":
            engine = db.get_bind()
            cols = {column["name"] for column in inspect(engine).get_columns("analysis_runs")}
            select_cols = ["id", "source_type", "provider", "service", "metric_name", "start_time", "end_time", "sample_count", "status", "created_at"]
            for optional in ["file_name", "router_version", "feature_extractor_version", "analyzer_registry_version", "series_profile_json", "router_decisions_json", "executed_analyzers_json", "generated_findings_json"]:
                if optional in cols:
                    select_cols.insert(2 if optional == "file_name" else len(select_cols), optional)
            rows = db.execute(text(f"SELECT {', '.join(select_cols)} FROM analysis_runs ORDER BY created_at DESC")).mappings().all()
            return [dict(row) for row in rows]
        if name == "analysis_run":
            engine = db.get_bind()
            cols = {column["name"] for column in inspect(engine).get_columns("analysis_runs")}
            select_cols = ["id", "source_type", "provider", "service", "metric_name", "start_time", "end_time", "sample_count", "status", "created_at"]
            for optional in ["file_name", "router_version", "feature_extractor_version", "analyzer_registry_version", "series_profile_json", "router_decisions_json", "executed_analyzers_json", "generated_findings_json"]:
                if optional in cols:
                    select_cols.insert(2 if optional == "file_name" else len(select_cols), optional)
            row = db.execute(text(f"SELECT {', '.join(select_cols)} FROM analysis_runs WHERE id = :run_id"), {"run_id": arguments["run_id"]}).mappings().one_or_none()
            if not row:
                raise ValueError("analysis run not found")
            return dict(row)
        if name == "similar_cases":
            _ensure_memory_services()
            if not _memory_config or not _memory_config.enabled:
                raise ValueError("Operational Memory is not enabled")
            service = _memory_services["similarity_service"]
            if not service:
                raise ValueError("Similarity service not initialized")
            return service.find_similar_cases(
                case_id=arguments["case_id"],
                db=db,
                top_k=arguments.get("top_k"),
                minimum_score=arguments.get("minimum_score"),
                same_service_only=arguments.get("same_service_only"),
            ).model_dump()
        if name == "memory_status":
            case = db.execute(select(OperationalCaseEntity).where(OperationalCaseEntity.id == arguments["case_id"])).scalar_one_or_none()
            if not case:
                raise ValueError("case not found")
            return {
                "case_id": case.id,
                "memory_status": case.memory_status,
                "memory_indexed_at": case.memory_indexed_at,
                "memory_content_version": case.memory_content_version,
                "memory_error": case.memory_error,
            }
        if name == "memory_chat":
            _ensure_memory_services()
            service = _memory_services["similarity_service"]
            embedder = _memory_services["embedder"]
            if not _memory_config or not _memory_config.enabled:
                raise ValueError("Operational Memory is not enabled")
            if not service or not embedder:
                raise ValueError("Memory services are not initialized")
            payload = MemoryChatRequest(**arguments)
            question = payload.message.strip()
            current_case = None
            if payload.case_id is not None:
                current_case = db.execute(select(OperationalCaseEntity).where(OperationalCaseEntity.id == payload.case_id)).scalar_one_or_none()
                if not current_case:
                    raise ValueError("Case not found")
            query_text = question if not current_case else "\n".join(["Operational case context:", CaseDocumentBuilder.build(current_case), "", f"User question: {question}"])
            vector = embedder.encode(query_text)
            filters = service._build_filters(current_case, payload.same_service_only) if current_case else None
            boost = RecallBoost(service=(current_case.finding_snapshot or {}).get("service") if current_case else None)
            search_results = service.vector_store.search(vector=vector, filters=filters, limit=payload.top_k * 2, score_threshold=payload.minimum_score, text=query_text, boost=boost)
            if current_case:
                search_results = [result for result in search_results if result["payload"].get("case_id") != current_case.id]
            filtered_results = leaders_only(search_results)[: payload.top_k]
            source_case_ids = [result["payload"].get("case_id") for result in filtered_results if result["payload"].get("case_id")]
            matched_cases = db.execute(select(OperationalCaseEntity).where(OperationalCaseEntity.id.in_(source_case_ids))).scalars().all() if source_case_ids else []
            case_by_id = {case.id: case for case in matched_cases}
            sources = []
            for result in filtered_results:
                case_id = result["payload"].get("case_id")
                if not case_id or case_id not in case_by_id:
                    continue
                matched_case = case_by_id[case_id]
                sources.append({
                    "case_id": matched_case.id,
                    "title": matched_case.case_title,
                    "similarity_score": float(result["score"]),
                    "service": result["payload"].get("service"),
                    "metric_name": result["payload"].get("metric_name"),
                    "category": result["payload"].get("category"),
                    "case_status": matched_case.case_status,
                    "root_cause_summary": matched_case.root_cause_summary,
                    "outcome_summary": matched_case.outcome_summary,
                })
            return {"conversation_id": str(payload.conversation_id or uuid4()), "answer": "MCP server implemented; use the HTTP routes for full chat payloads.", "limitations": ["Use HTTP routes for now."], "suggested_questions": [], "sources": sources}
        if name == "assistant_chat":
            _ensure_memory_services()
            assistant = _memory_services["assistant"]
            if not assistant:
                raise ValueError("Assistant is not initialized")
            return assistant.chat(AssistantChatRequest(**arguments), db).model_dump()
        if name == "create_case_from_finding":
            return create_case_from_finding(arguments["finding_id"], db).model_dump()
        if name == "index_case_memory":
            _ensure_memory_services()
            indexer = _memory_services["indexer"]
            if not _memory_config or not _memory_config.enabled:
                raise ValueError("Operational Memory is not enabled")
            if not indexer:
                raise ValueError("Memory indexer not initialized")
            case = db.execute(select(OperationalCaseEntity).where(OperationalCaseEntity.id == arguments["case_id"])).scalar_one_or_none()
            if not case:
                raise ValueError("Case not found")
            return indexer.index_case(case, db).model_dump()
        if name == "update_investigation":
            return update_investigation(arguments["case_id"], InvestigationUpdateRequest(**arguments["payload"]), db).model_dump()
        if name == "update_rca":
            return update_root_cause_analysis(arguments["case_id"], RCAUpdateRequest(**arguments["payload"]), db).model_dump()
        if name == "update_resolution":
            return update_resolution(arguments["case_id"], ResolutionUpdateRequest(**arguments["payload"]), db).model_dump()
        if name == "analyzer_recommendation":
            service = MetricAnalyzerRecommendationService()
            payload = dict(arguments)
            service_name = str(payload.get("service", "")).strip()
            metric_name = str(payload.get("metric_name", "")).strip()
            analysis_run_id = payload.get("analysis_run_id")
            if analysis_run_id is not None:
                analysis_run_id = str(analysis_run_id).strip() or None
            sample = service.find_sample(db, service_name, metric_name, analysis_run_id)
            if not sample:
                raise ValueError("sample not found")
            profile, timeseries = service.profile_sample(db, service_name, metric_name, sample["analysis_run_id"])
            analysis_config = _analyzer_config.get("analysis", {}) if isinstance(_analyzer_config, dict) else {}
            selection_mode = str(analysis_config.get("recommendation_selection_mode", "all"))
            selected_analyzers = list(analysis_config.get("selected_analyzers", []) or [])
            recommendations = [AnalyzerRecommendationOut(**item) for item in service.recommend(profile, selection_mode, selected_analyzers, timeseries)]
            return RecommendationResponseOut(sample=MetricSampleOut(**sample), profile=MetricProfileOut(**asdict(profile)), recommendations=recommendations).model_dump()
        if name == "question_answer":
            routed = QuestionRouter(db).route(question_id=arguments["question_id"], service=arguments["service"], metric_name=arguments["metric_name"], analysis_run_id=arguments["analysis_run_id"])
            signal_dicts = [{"id": sig.signal_id, "signal_type": sig.signal_type, "analyzer_id": sig.analyzer_id, "severity": sig.severity, "confidence": sig.confidence, "importance_score": sig.importance_score, "summary": sig.summary, "evidence": sig.evidence_json or {}} for sig in routed.signals]
            return AnswerComposer().compose(arguments["question_id"], signal_dicts).model_dump()
        raise ValueError(f"Unknown tool: {name}")
    finally:
        db.close()
        db_gen.close()


def main(*, read_only_only: bool = True) -> None:
    _ensure_runtime()
    for line in sys.stdin:
        if not line.strip():
            continue
        message = json.loads(line)
        method = message.get("method")
        request_id = message.get("id")
        try:
            if method == "initialize":
                payload = {"protocolVersion": "2024-11-05", "serverInfo": {"name": "ops-signals", "version": "0.1.0"}, "capabilities": {"tools": {}}}
                print(json.dumps({"jsonrpc": "2.0", "id": request_id, "result": payload}, default=_json_default), flush=True)
            elif method == "tools/list":
                print(json.dumps({"jsonrpc": "2.0", "id": request_id, "result": _tools_list(read_only_only)}, default=_json_default), flush=True)
            elif method == "tools/call":
                params = message.get("params", {})
                if read_only_only:
                    allowed = {tool["name"] for tool in list_read_only_http_tools()}
                    if params["name"] not in allowed:
                        raise ValueError(f"Tool not enabled in read-only mode: {params['name']}")
                result = _call_tool(params["name"], params.get("arguments", {}))
                print(json.dumps({"jsonrpc": "2.0", "id": request_id, "result": {"content": [{"type": "text", "text": json.dumps(result, default=_json_default)}]}}, default=_json_default), flush=True)
            elif method == "ping":
                print(json.dumps({"jsonrpc": "2.0", "id": request_id, "result": {}}), flush=True)
            else:
                print(json.dumps({"jsonrpc": "2.0", "id": request_id, "error": {"code": -32601, "message": f"Unknown method: {method}"}}), flush=True)
        except Exception as exc:
            print(json.dumps({"jsonrpc": "2.0", "id": request_id, "error": {"code": -32000, "message": str(exc)}}), flush=True)


if __name__ == "__main__":
    main()
