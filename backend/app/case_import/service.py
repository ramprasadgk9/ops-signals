"""Writes parsed incident records as resolved, imported operational cases.

Idempotent by design: each record is keyed by (source, source_id) - the source's own ID, or a
fingerprint when it has none - under a unique index. A re-upload of the same record is a no-op; a
changed record updates its existing case in place and re-indexes it; nothing is ever duplicated.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.case_import.parsers import IncidentRecord, ParsedUpload
from backend.app.config import MemoryConfig
from backend.app.memory.indexer import CaseMemoryIndexer
from backend.app.models.entities import CaseImportBatchEntity, OperationalCaseEntity

logger = logging.getLogger(__name__)

# Notes the importer wrote carry this marker, so a re-import replaces them and leaves notes people
# added in Ops Signals alone.
IMPORT_NOTE_SOURCE = "import"


@dataclass
class PlannedRecord:
    record: IncidentRecord
    action: str  # new, updated, unchanged, skipped, duplicate
    case_id: int | None = None


@dataclass
class ImportPlan:
    upload: ParsedUpload
    items: list[PlannedRecord] = field(default_factory=list)

    @property
    def counts(self) -> dict[str, int]:
        counts = {"new": 0, "updated": 0, "unchanged": 0, "skipped": 0, "duplicate_rows": 0}
        for item in self.items:
            counts["duplicate_rows" if item.action == "duplicate" else item.action] += 1
        return counts


@dataclass
class ImportResult:
    batch_id: str
    plan: ImportPlan
    indexed: int = 0
    index_failed: int = 0

    @property
    def counts(self) -> dict[str, int]:
        return self.plan.counts


class CaseImportService:
    def __init__(
        self,
        db: Session,
        indexer: CaseMemoryIndexer | None = None,
        memory_config: MemoryConfig | None = None,
    ) -> None:
        self.db = db
        self.indexer = indexer
        self.memory_config = memory_config

    def plan(self, upload: ParsedUpload) -> ImportPlan:
        """Decides what each record would do, without writing anything."""
        plan = ImportPlan(upload=upload)
        seen: set[tuple[str, str]] = set()
        for record in upload.records:
            if record.problems:
                plan.items.append(PlannedRecord(record, "skipped"))
                continue
            key = (record.source, record.identity_id)
            if key in seen:
                plan.items.append(PlannedRecord(record, "duplicate"))
                continue
            seen.add(key)
            existing = self._find(record)
            if existing is None:
                plan.items.append(PlannedRecord(record, "new"))
            elif existing.content_hash == record.content_hash:
                plan.items.append(PlannedRecord(record, "unchanged", existing.id))
            else:
                plan.items.append(PlannedRecord(record, "updated", existing.id))
        return plan

    def apply(self, plan: ImportPlan, source_files: list[str]) -> ImportResult:
        """Writes the plan. Each record commits on its own, so the unique (source, source_id) index
        can settle a race with a concurrent import of the same record: a rejected insert is retried
        as an update of the row the other import wrote."""
        batch = CaseImportBatchEntity(
            id=uuid4().hex,
            sources=sorted({item.record.source for item in plan.items}),
            file_profiles=plan.upload.file_profiles or {name: "" for name in source_files},
            counts={},
            status="running",
            created_at=datetime.utcnow(),
        )
        self.db.add(batch)
        self.db.commit()

        changed: list[OperationalCaseEntity] = []
        for item in plan.items:
            if item.action not in {"new", "updated"}:
                continue
            case = self._write(item, batch.id)
            if case is not None:
                changed.append(case)

        result = ImportResult(batch_id=batch.id, plan=plan)
        for case in changed:
            self._index(case, result)

        batch.counts = plan.counts
        batch.indexed = result.indexed
        batch.status = "completed"
        self.db.commit()
        return result

    def undo(self, batch_id: str) -> int | None:
        """Deletes the cases a batch created (not ones it only updated) and their memory entries.
        Returns how many were deleted, or None when the batch does not exist."""
        batch = self.db.get(CaseImportBatchEntity, batch_id)
        if batch is None:
            return None
        cases = self.db.execute(
            select(OperationalCaseEntity).where(OperationalCaseEntity.import_batch_id == batch_id)
        ).scalars().all()
        for case in cases:
            if self.indexer is not None and case.memory_status != "not_indexed":
                self.indexer.delete_memory(case, self.db)
            self.db.delete(case)
        batch.status = "undone"
        batch.undone_at = datetime.utcnow()
        self.db.commit()
        return len(cases)

    def list_batches(self, limit: int = 50) -> list[CaseImportBatchEntity]:
        return list(
            self.db.execute(
                select(CaseImportBatchEntity).order_by(CaseImportBatchEntity.created_at.desc()).limit(limit)
            ).scalars()
        )

    @staticmethod
    def build_case(record: IncidentRecord, batch_id: str) -> OperationalCaseEntity:
        case = OperationalCaseEntity(
            source=record.source,
            source_id=record.identity_id,
            import_batch_id=batch_id,
            analysis_run_id=f"import:{batch_id}",
            investigation_notes=[],
            memory_status="not_indexed",
        )
        CaseImportService._apply_record(case, record)
        return case

    @staticmethod
    def _apply_record(case: OperationalCaseEntity, record: IncidentRecord) -> None:
        started_at = _naive_utc(record.started_at)
        case.case_title = record.title
        case.finding_snapshot = {
            "source_type": "imported",
            "source": record.source,
            "source_id": record.identity_id,
            "service": record.service,
            "services": record.services,
            "metric_name": None,
            "title": record.title,
            "summary": record.symptom,
            "category": "imported_incident",
            "health_status": record.severity or None,
            "importance_score": 0.0,
            "tags": record.tags,
            "started_at": started_at.isoformat() if started_at else None,
        }
        case.case_status = "resolved"
        case.investigation_status = "completed"
        local_notes = [note for note in (case.investigation_notes or []) if note.get("source") != IMPORT_NOTE_SOURCE]
        imported_notes = [
            {"timestamp": started_at.replace(tzinfo=timezone.utc).isoformat() if started_at else None, "note": note, "source": IMPORT_NOTE_SOURCE}
            for note in record.notes
        ]
        case.investigation_notes = imported_notes + local_notes
        case.root_cause_status = "confirmed"
        case.root_cause_summary = record.root_cause
        case.root_cause_verified = True
        case.corrective_action = record.corrective_action or None
        case.outcome_status = "resolved"
        case.outcome_summary = record.outcome or None
        case.source_url = record.source_url or None
        case.content_hash = record.content_hash
        case.created_at = started_at or datetime.utcnow()
        case.resolved_at = _naive_utc(record.resolved_at) or started_at
        case.updated_at = datetime.utcnow()

    def _find(self, record: IncidentRecord) -> OperationalCaseEntity | None:
        return self.db.execute(
            select(OperationalCaseEntity).where(
                OperationalCaseEntity.source == record.source,
                OperationalCaseEntity.source_id == record.identity_id,
            )
        ).scalar_one_or_none()

    def _write(self, item: PlannedRecord, batch_id: str) -> OperationalCaseEntity | None:
        record = item.record
        if item.action == "new":
            case = self.build_case(record, batch_id)
            self.db.add(case)
            try:
                self.db.commit()
                item.case_id = case.id
                return case
            except IntegrityError:
                self.db.rollback()
                logger.info("Import of %s/%s raced another import; updating instead", record.source, record.identity_id)

        existing = self._find(record)
        if existing is None:
            # The row this plan expected was deleted since planning; nothing to update.
            item.action = "skipped"
            return None
        item.case_id = existing.id
        if existing.content_hash == record.content_hash:
            item.action = "unchanged"
            return None
        self._apply_record(existing, record)
        self.db.commit()
        item.action = "updated"
        return existing

    def _index(self, case: OperationalCaseEntity, result: ImportResult) -> None:
        config = self.memory_config
        if not (config and config.enabled and self.indexer):
            if case.memory_status == "indexed":
                case.memory_status = "stale"
                self.db.commit()
            return
        try:
            self.indexer.index_case(case, self.db)
            result.indexed += 1
        except Exception as exc:
            result.index_failed += 1
            logger.warning("Memory indexing failed for imported case %s: %s", case.id, exc)


def _naive_utc(value: datetime | None) -> datetime | None:
    # Case timestamps are stored as naive UTC everywhere else (datetime.utcnow()).
    return value.replace(tzinfo=None) if value else None
