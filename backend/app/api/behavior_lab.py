from __future__ import annotations

from pathlib import Path

import yaml
from fastapi import APIRouter, Depends
from sqlalchemy import distinct, select
from sqlalchemy.orm import Session

from fastapi import HTTPException

from backend.app.behavior_intelligence.fact_catalog import FACT_DESCRIPTORS
from backend.app.behavior_intelligence.finding_builder import build_evaluation
from backend.app.behavior_intelligence.fact_extractor import input_facts
from backend.app.behavior_intelligence.models import BehaviorCondition, BehaviorDefinition, BehaviorInput, BehaviorOutput
from backend.app.behavior_intelligence.pattern_miner import mine_and_store
from backend.app.behavior_intelligence.schemas import (
    BehaviorEvaluationOut,
    BehaviorPatternSuggestionOut,
    DryRunRequest,
    FactDescriptorOut,
    PromoteSuggestionRequest,
    SaveDraftRequest,
    SaveDraftResult,
    ValidationResultOut,
    BehaviorDefinitionDraftIn,
)
from backend.app.behavior_intelligence.validator import BehaviorDefinitionValidator
from backend.app.models.db import get_db
from backend.app.models.entities import BehaviorPatternSuggestionEntity, NormalizedPoint, SignalEntity
from backend.app.security import require_file_writes

router = APIRouter(prefix="/api/behavior-definitions", tags=["behavior-definitions"])

PACKS_DIR = Path("config/behavior_definitions.d")


def _known_analyzer_ids() -> set[str]:
    # inputs[].analyzers references *runtime* analyzer ids (config/analyzers.yaml's
    # analysis.analyzers keys — anomaly_zscore, trend, baseline_shift, ...), which is a
    # different id space from the router's analyzer_registry.yaml (trend_regression, etc. — see
    # docs/analyzer-recommendation.md "Router-to-pipeline mapping"). Read the runtime config directly.
    path = Path("config/analyzers.yaml")
    if not path.exists():
        return set()
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        return set()
    return set((raw.get("analysis", {}) or {}).get("analyzers", {}) or {})


def _draft_to_definition(draft: BehaviorDefinitionDraftIn) -> BehaviorDefinition:
    return BehaviorDefinition(
        id=draft.id,
        enabled=draft.enabled,
        version=draft.version,
        title=draft.title,
        description=draft.description,
        scope=draft.scope,
        inputs=[BehaviorInput(alias=i.alias, metric_name=i.metric_name, analyzers=list(i.analyzers)) for i in draft.inputs],
        conditions={
            group: [BehaviorCondition(fact=c.fact, operator=c.operator, value=c.value) for c in conditions]
            for group, conditions in draft.conditions.items()
        },
        correlation=draft.correlation,
        output=BehaviorOutput(
            category=draft.output.category,
            severity=draft.output.severity,
            title=draft.output.title,
            summary=draft.output.summary,
            evidence=list(draft.output.evidence),
        ),
        source_file=None,
    )


@router.get("/facts", response_model=list[FactDescriptorOut])
def list_fact_catalog() -> list[FactDescriptorOut]:
    """Every fact a condition can reference (e.g. "<alias>.anomaly.present"), with a
    description and example value — the reference someone needs to write their own behavior
    definition without reading the analyzer source code first."""
    return [FactDescriptorOut(key=d.key, description=d.description, example=d.example) for d in FACT_DESCRIPTORS]


@router.get("/available-metrics")
def list_available_metrics(db: Session = Depends(get_db)) -> list[str]:
    """Distinct metric names seen anywhere in the system — what's actually available to build
    an input around, independent of any one service."""
    rows = db.execute(select(distinct(NormalizedPoint.metric_name))).all()
    return sorted(row[0] for row in rows if row[0])


@router.post("/validate", response_model=ValidationResultOut)
def validate_definition(draft: BehaviorDefinitionDraftIn) -> ValidationResultOut:
    definition = _draft_to_definition(draft)
    errors = BehaviorDefinitionValidator.validate(definition, known_analyzer_ids=_known_analyzer_ids())
    warnings = BehaviorDefinitionValidator.warnings(definition) if not errors else []
    return ValidationResultOut(valid=not errors, errors=errors, warnings=warnings)


@router.post("/dry-run", response_model=BehaviorEvaluationOut)
def dry_run_definition(payload: DryRunRequest, db: Session = Depends(get_db)) -> BehaviorEvaluationOut:
    """Runs a draft definition against real signals for one analysis_run_id, without saving the
    definition anywhere or persisting a finding — lets someone test a pattern before adding it to
    a pack file. Mirrors GET /api/behavior-evaluations/evaluate's matching logic, but for a
    definition that only exists in this request instead of one already loaded from disk."""
    definition = _draft_to_definition(draft=payload.definition)
    errors = BehaviorDefinitionValidator.validate(definition, known_analyzer_ids=_known_analyzer_ids())
    if errors:
        return BehaviorEvaluationOut(
            definition_id=definition.id,
            definition_version=definition.version,
            title=definition.title,
            description=f"Definition is invalid, not evaluated: {'; '.join(errors)}",
            matched=False,
            confidence=0.0,
        )

    query = select(SignalEntity).where(SignalEntity.analysis_run_id == payload.analysis_run_id)
    if payload.service:
        query = query.where(SignalEntity.service == payload.service)
    signals = db.execute(query).scalars().all()
    signal_dicts = [
        {
            "id": row.signal_id,
            "signal_type": row.signal_type,
            "analyzer_id": row.analyzer_id,
            "metric_name": row.metric_name,
            "service": row.service,
            "severity": row.severity,
            "confidence": row.confidence,
            "start_time": row.start_time,
            "end_time": row.end_time,
            "summary": row.summary,
            "evidence": row.evidence_json or {},
            "importance_score": row.importance_score,
            "analysis_run_id": row.analysis_run_id,
        }
        for row in signals
    ]

    matched_inputs: dict[str, dict] = {}
    for item in definition.inputs:
        facts_for_input = input_facts(item.metric_names, item.analyzers, signal_dicts)
        if facts_for_input is not None:
            matched_inputs[item.alias] = facts_for_input

    if len(matched_inputs) < len(definition.inputs):
        missing = [item.alias for item in definition.inputs if item.alias not in matched_inputs]
        return BehaviorEvaluationOut(
            definition_id=definition.id,
            definition_version=definition.version,
            title=definition.title,
            description=f"No signals found for input(s): {', '.join(missing)}. Nothing to evaluate.",
            matched=False,
            confidence=0.0,
            service=payload.service,
            analysis_run_id=payload.analysis_run_id,
        )

    facts = dict(matched_inputs)
    evaluation = build_evaluation(definition, facts, matched_inputs, payload.service, payload.analysis_run_id)
    return BehaviorEvaluationOut(
        definition_id=evaluation.definition_id,
        definition_version=evaluation.definition_version,
        title=evaluation.title,
        description=evaluation.description,
        matched=evaluation.matched,
        confidence=evaluation.confidence,
        service=evaluation.service,
        analysis_run_id=evaluation.analysis_run_id,
        facts=evaluation.facts,
        matched_conditions=evaluation.matched_conditions,
        evidence=evaluation.evidence,
        correlation=evaluation.correlation,
    )


@router.post("/suggestions/mine", response_model=list[BehaviorPatternSuggestionOut])
def mine_suggestions(db: Session = Depends(get_db)) -> list[BehaviorPatternSuggestionEntity]:
    """Scans recent signal history for metric pairs that keep showing activity close together in
    time, and stores each as a pending suggestion with a ready-to-review draft definition — the
    "let the system suggest combinations instead of guessing" feature. Simple co-occurrence
    counting, not ML; a starting point for a human to review and tune, not an automatic answer."""
    return mine_and_store(db)


@router.get("/suggestions", response_model=list[BehaviorPatternSuggestionOut])
def list_suggestions(status: str | None = "pending", db: Session = Depends(get_db)) -> list[BehaviorPatternSuggestionEntity]:
    query = select(BehaviorPatternSuggestionEntity)
    if status:
        query = query.where(BehaviorPatternSuggestionEntity.status == status)
    query = query.order_by(BehaviorPatternSuggestionEntity.correlation_strength.desc())
    return list(db.execute(query).scalars().all())


@router.post("/suggestions/{suggestion_id}/dismiss", response_model=BehaviorPatternSuggestionOut)
def dismiss_suggestion(suggestion_id: int, db: Session = Depends(get_db)) -> BehaviorPatternSuggestionEntity:
    record = db.get(BehaviorPatternSuggestionEntity, suggestion_id)
    if record is None:
        raise HTTPException(status_code=404, detail="suggestion not found")
    record.status = "dismissed"
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


@router.post("/suggestions/{suggestion_id}/promote", response_model=BehaviorPatternSuggestionOut, dependencies=[Depends(require_file_writes)])
def promote_suggestion(suggestion_id: int, payload: PromoteSuggestionRequest, db: Session = Depends(get_db)) -> BehaviorPatternSuggestionEntity:
    """Writes the suggestion's draft definition into a pack file under config/behavior_definitions.d/
    (created if it doesn't exist yet, appended to if it does) — same "review, don't auto-enable"
    posture as the draft itself (enabled: false), so promoting still requires a person to flip it
    on once they've looked at it, ideally via the Behavior Lab's dry-run first."""
    record = db.get(BehaviorPatternSuggestionEntity, suggestion_id)
    if record is None:
        raise HTTPException(status_code=404, detail="suggestion not found")

    PACKS_DIR.mkdir(parents=True, exist_ok=True)
    pack_path = PACKS_DIR / payload.pack_file
    existing_raw: dict = {}
    if pack_path.exists():
        existing_raw = yaml.safe_load(pack_path.read_text(encoding="utf-8")) or {}
    definitions = existing_raw.setdefault("behavior_definitions", {})
    draft = record.draft_definition_json
    definitions[draft["id"]] = {k: v for k, v in draft.items() if k != "id"}
    pack_path.write_text(yaml.dump(existing_raw, sort_keys=False), encoding="utf-8")

    record.status = "promoted"
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


@router.post("/save-to-pack", response_model=SaveDraftResult, dependencies=[Depends(require_file_writes)])
def save_draft_to_pack(payload: SaveDraftRequest) -> SaveDraftResult:
    """Freeform version of promote_suggestion — for a definition authored from scratch in the
    Behavior Lab rather than mined. Refuses to save an invalid definition (unlike promote, which
    trusts a suggestion's own auto-generated draft, a hand-written one hasn't been checked yet)."""
    definition = _draft_to_definition(payload.definition)
    errors = BehaviorDefinitionValidator.validate(definition, known_analyzer_ids=_known_analyzer_ids())
    if errors:
        return SaveDraftResult(
            saved=False,
            pack_file=payload.pack_file,
            validation=ValidationResultOut(valid=False, errors=errors, warnings=[]),
        )

    PACKS_DIR.mkdir(parents=True, exist_ok=True)
    pack_path = PACKS_DIR / payload.pack_file
    existing_raw: dict = {}
    if pack_path.exists():
        existing_raw = yaml.safe_load(pack_path.read_text(encoding="utf-8")) or {}
    definitions = existing_raw.setdefault("behavior_definitions", {})
    draft_dict = payload.definition.model_dump()
    definitions[draft_dict.pop("id")] = draft_dict
    pack_path.write_text(yaml.dump(existing_raw, sort_keys=False), encoding="utf-8")

    warnings = BehaviorDefinitionValidator.warnings(definition)
    return SaveDraftResult(saved=True, pack_file=payload.pack_file, validation=ValidationResultOut(valid=True, errors=[], warnings=warnings))
