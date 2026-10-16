"""Import past incidents as resolved cases (docs/importing-incident-history.md)."""

from __future__ import annotations

import json
import threading
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.app.api.ingestion import MAX_UPLOAD_BYTES
from backend.app.api.memory import get_memory_config, get_memory_indexer
from backend.app.case_import.parsers import (
    FIELDS,
    PROFILES,
    REQUIRED_FIELDS,
    ImportSettings,
    ImportSettingsError,
    parse_files,
)
from backend.app.case_import.service import CaseImportService, ImportPlan
from backend.app.config import MemoryConfig
from backend.app.memory.indexer import CaseMemoryIndexer
from backend.app.models.db import get_db

router = APIRouter(prefix="/api/case-imports", tags=["case-imports"])

IMPORT_RUN_LOCK = threading.Lock()

TEMPLATES_DIR = Path(__file__).resolve().parents[1] / "case_import" / "templates"


class ImportProfileOut(BaseModel):
    id: str
    label: str
    kind: str
    default_source: str
    checklist: list[str]


class ImportProfilesOut(BaseModel):
    profiles: list[ImportProfileOut]
    fields: list[str]
    required_fields: list[str]
    templates: list[str]


class ImportRecordOut(BaseModel):
    ref: str
    source: str
    source_id: str | None
    title: str
    service: str
    started_at: datetime | None
    action: str
    problems: list[str]
    redactions: int
    case_id: int | None


class ImportPreviewOut(BaseModel):
    file_profiles: dict[str, str]
    warnings: list[str]
    counts: dict[str, int]
    redactions: int
    records: list[ImportRecordOut]


class ImportResultOut(ImportPreviewOut):
    batch_id: str
    indexed: int
    index_failed: int


class ImportBatchOut(BaseModel):
    id: str
    sources: list[str]
    file_profiles: dict[str, str]
    counts: dict[str, int]
    indexed: int
    status: str
    created_at: datetime
    undone_at: datetime | None


class ImportUndoOut(BaseModel):
    batch_id: str
    deleted_cases: int


@router.get("/profiles", response_model=ImportProfilesOut)
def list_profiles() -> ImportProfilesOut:
    return ImportProfilesOut(
        profiles=[
            ImportProfileOut(
                id=profile.id,
                label=profile.label,
                kind=profile.kind,
                default_source=profile.default_source,
                checklist=list(profile.checklist),
            )
            for profile in PROFILES.values()
        ],
        fields=list(FIELDS),
        required_fields=list(REQUIRED_FIELDS),
        templates=sorted(path.name for path in TEMPLATES_DIR.iterdir() if path.is_file()),
    )


@router.get("/templates/{name}")
def download_template(name: str) -> FileResponse:
    templates = {path.name: path for path in TEMPLATES_DIR.iterdir() if path.is_file()}
    if name not in templates:
        raise HTTPException(status_code=404, detail="template not found")
    return FileResponse(templates[name], filename=name)


@router.post("/preview", response_model=ImportPreviewOut)
async def preview_import(
    files: list[UploadFile] = File(...),
    settings: str | None = Form(None),
    db: Session = Depends(get_db),
) -> ImportPreviewOut:
    upload = await _parse_upload(files, settings)
    plan = await run_in_threadpool(CaseImportService(db).plan, upload)
    return _preview_out(plan)


@router.post("", response_model=ImportResultOut)
async def run_import(
    files: list[UploadFile] = File(...),
    settings: str | None = Form(None),
    db: Session = Depends(get_db),
    indexer: CaseMemoryIndexer | None = Depends(get_memory_indexer),
    config: MemoryConfig | None = Depends(get_memory_config),
) -> ImportResultOut:
    upload = await _parse_upload(files, settings)
    service = CaseImportService(db, indexer, config)
    source_files = [file.filename or "" for file in files]

    def plan_and_apply():
        # One import at a time, as before: two at once could each plan the same record as new.
        with IMPORT_RUN_LOCK:
            return service.apply(service.plan(upload), source_files=source_files)

    # Planning, one database write per case and memory indexing block: run them off the event loop.
    result = await run_in_threadpool(plan_and_apply)
    return ImportResultOut(
        **_preview_out(result.plan).model_dump(),
        batch_id=result.batch_id,
        indexed=result.indexed,
        index_failed=result.index_failed,
    )


@router.get("", response_model=list[ImportBatchOut])
def list_imports(db: Session = Depends(get_db)) -> list[ImportBatchOut]:
    return [ImportBatchOut.model_validate(batch, from_attributes=True) for batch in CaseImportService(db).list_batches()]


@router.delete("/{batch_id}", response_model=ImportUndoOut)
def undo_import(
    batch_id: str,
    db: Session = Depends(get_db),
    indexer: CaseMemoryIndexer | None = Depends(get_memory_indexer),
) -> ImportUndoOut:
    deleted = CaseImportService(db, indexer).undo(batch_id)
    if deleted is None:
        raise HTTPException(status_code=404, detail="import not found")
    return ImportUndoOut(batch_id=batch_id, deleted_cases=deleted)


async def _parse_upload(files: list[UploadFile], settings_json: str | None):
    total = 0
    contents: list[tuple[str, bytes]] = []
    for file in files:
        data = await file.read()
        total += len(data)
        if total > MAX_UPLOAD_BYTES:
            raise HTTPException(
                status_code=413,
                detail=f"upload exceeds {MAX_UPLOAD_BYTES} bytes (set OPS_SIGNALS_MAX_UPLOAD_BYTES to change)",
            )
        contents.append((file.filename or "upload", data))
    return await run_in_threadpool(_parse_contents, contents, settings_json)


def _parse_contents(contents: list[tuple[str, bytes]], settings_json: str | None):
    try:
        settings = ImportSettings.from_dict(json.loads(settings_json) if settings_json else {})
        return parse_files(contents, settings)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail=f"settings is not valid JSON: {exc.msg}") from exc
    except ImportSettingsError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _preview_out(plan: ImportPlan) -> ImportPreviewOut:
    return ImportPreviewOut(
        file_profiles=plan.upload.file_profiles,
        warnings=plan.upload.warnings,
        counts=plan.counts,
        redactions=sum(item.record.redactions for item in plan.items),
        records=[
            ImportRecordOut(
                ref=item.record.ref,
                source=item.record.source,
                source_id=item.record.identity_id,
                title=item.record.title,
                service=item.record.service,
                started_at=item.record.started_at,
                action=item.action,
                problems=item.record.problems,
                redactions=item.record.redactions,
                case_id=item.case_id,
            )
            for item in plan.items
        ],
    )
