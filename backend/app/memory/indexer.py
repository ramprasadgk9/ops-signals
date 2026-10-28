"""Operational case memory indexer orchestrating document building and embedding."""

import logging
from datetime import datetime
from uuid import UUID, uuid5, NAMESPACE_URL

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.config import MemoryConfig
from backend.app.memory.document_builder import CaseDocumentBuilder
from backend.app.memory.embedder import Embedder
from backend.app.memory.recall_scoring import service_key
from backend.app.memory.schemas import MemoryIndexResponse
from backend.app.memory.vector_names import RESOLUTION_VECTOR, SYMPTOM_VECTOR
from backend.app.memory.vector_store import VectorStore
from backend.app.models.entities import OperationalCaseEntity
from backend.app.services.case_status import derive_case_status

logger = logging.getLogger(__name__)


class CaseMemoryIndexer:
    """Index operational cases into vector store."""

    def __init__(
        self,
        vector_store: VectorStore,
        embedder: Embedder,
        config: MemoryConfig,
    ):
        """Initialize case memory indexer.

        Args:
            vector_store: VectorStore implementation
            embedder: Embedder implementation
            config: Memory configuration
        """
        self.vector_store = vector_store
        self.embedder = embedder
        self.config = config

    def index_case(
        self,
        case: OperationalCaseEntity,
        db: Session,
    ) -> MemoryIndexResponse:
        """Index an operational case into the vector store.

        Flow:
        1. Update memory_status to indexing
        2. Build case document
        3. Generate embedding
        4. Build Qdrant payload
        5. Upsert into vector store
        6. Update memory_status to indexed
        7. Set memory_indexed_at and content_version
        8. Clear memory_error

        Args:
            case: The operational case to index
            db: Database session

        Returns:
            MemoryIndexResponse with indexing status

        Raises:
            RuntimeError: If indexing fails (preserves case, sets error status)
        """
        try:
            # Step 1: Update status to indexing
            case.memory_status = "indexing"
            db.commit()
            logger.info(f"Case {case.id}: Starting memory indexing")

            # Step 2: Build document
            document = CaseDocumentBuilder.build(case)
            logger.debug(f"Case {case.id}: Built document ({len(document)} chars)")

            # Step 3: Generate embedding
            vector = self.embedder.encode(document)
            logger.debug(f"Case {case.id}: Generated embedding (dim={len(vector)})")

            # Step 4: Build Qdrant payload
            payload = self._build_payload(case, vector)
            logger.debug(f"Case {case.id}: Built payload with {len(payload)} fields")

            # Step 5: Upsert into vector store
            point_id = self._generate_point_id(case.id)
            self.vector_store.upsert(point_id, vector, payload, text=document, vectors=self._view_vectors(case))
            logger.info(f"Case {case.id}: Upserted to Qdrant (point_id={point_id})")

            # Step 6-8: Update case metadata
            case.memory_status = "indexed"
            case.memory_opted_out = False
            case.memory_indexed_at = datetime.utcnow()
            case.memory_content_version = CaseDocumentBuilder.get_content_version()
            case.memory_error = None
            db.commit()

            logger.info(f"Case {case.id}: Memory indexing complete")

            return MemoryIndexResponse(
                case_id=case.id,
                memory_status="indexed",
                collection=self.config.vector_store.collection_name,
                embedding_model=self.embedder.model_name,
                content_version=case.memory_content_version,
                indexed_at=case.memory_indexed_at,
            )

        except Exception as e:
            logger.error(f"Case {case.id}: Failed to index memory: {e}")
            
            # Preserve the case, set error status
            try:
                case.memory_status = "failed"
                case.memory_error = str(e)[:255]  # Truncate error to 255 chars
                db.commit()
            except Exception as db_error:
                logger.error(f"Case {case.id}: Failed to update error status: {db_error}")

            raise RuntimeError(f"Failed to index case {case.id}: {e}")

    def _view_vectors(self, case: OperationalCaseEntity) -> dict[str, list[float] | None]:
        """The symptom and resolution vectors (vector_names); resolution only once there is one."""
        resolution = CaseDocumentBuilder.build_resolution(case)
        return {
            SYMPTOM_VECTOR: self.embedder.encode(CaseDocumentBuilder.build_symptom(case)),
            RESOLUTION_VECTOR: self.embedder.encode(resolution) if resolution else None,
        }

    def backfill_vectors(self, db: Session) -> int:
        """Add the symptom, resolution and keyword vectors to points indexed before they existed
        (or copied over by QdrantInitializer's migration), with the payload fields the ranking
        formula reads. The full-document vector is kept, so each case costs two embeddings, not
        three. It does nothing once every point has a symptom vector, so it runs at every startup.

        A point whose case is gone from Postgres (the record, ADR-004) is deleted: it can't be
        backfilled, and while any point lacks a symptom vector every symptom search falls back to
        the full-document vector (VectorStore._is_complete), so its scores stop meaning the same
        thing. Nothing is deleted while Postgres holds no cases at all, so a backend pointed at an
        empty or wrong database can't wipe the index.

        Returns:
            Number of points backfilled
        """
        filled = removed = 0
        has_cases = db.execute(select(OperationalCaseEntity.id).limit(1)).first() is not None
        while True:
            points = self.vector_store.points_missing(SYMPTOM_VECTOR)
            case_ids = [point["payload"].get("case_id") for point in points if point["payload"].get("case_id")]
            if not case_ids:
                break
            cases = {
                case.id: case
                for case in db.execute(
                    select(OperationalCaseEntity).where(OperationalCaseEntity.id.in_(case_ids))
                ).scalars()
            }
            progressed = False
            for point in points:
                case = cases.get(point["payload"].get("case_id"))
                if case is None:
                    if has_cases:
                        try:
                            self.vector_store.delete(point["point_id"])
                            removed += 1
                            progressed = True
                        except Exception as e:
                            logger.warning(f"Failed to remove memory point {point['point_id']} of deleted case {point['payload'].get('case_id')}: {e}")
                    continue
                try:
                    self.vector_store.set_vectors(
                        point["point_id"],
                        self._view_vectors(case),
                        text=CaseDocumentBuilder.build(case),
                        payload={"service_key": service_key((case.finding_snapshot or {}).get("service"))},
                    )
                    filled += 1
                    progressed = True
                except Exception as e:
                    logger.warning(f"Case {case.id}: Failed to backfill vectors: {e}")
            # Points that keep failing stay as they are; stop rather than re-reading the same page
            # forever.
            if not progressed:
                break
        if filled:
            logger.info(f"Backfilled symptom, resolution and keyword vectors for {filled} indexed cases")
        if removed:
            logger.info(f"Removed {removed} memory points whose case no longer exists")
        return filled

    def mark_stale(self, case: OperationalCaseEntity, db: Session) -> None:
        """Mark case memory as stale after case updates.

        Args:
            case: The case to mark stale
            db: Database session
        """
        if case.memory_status == "indexed":
            case.memory_status = "stale"
            db.commit()
            logger.info(f"Case {case.id}: Marked memory as stale")

    def delete_memory(
        self,
        case: OperationalCaseEntity,
        db: Session,
    ) -> None:
        """Delete case from memory index.

        Args:
            case: The case to delete from memory
            db: Database session
        """
        try:
            point_id = self._generate_point_id(case.id)
            self.vector_store.delete(point_id)
            logger.info(f"Case {case.id}: Deleted from Qdrant")
        except Exception as e:
            logger.warning(f"Case {case.id}: Failed to delete from Qdrant: {e}")

        # Always update DB status regardless of Qdrant success. Opted out: catch-up indexing
        # (memory/catch_up.py) must not add back a case the user removed.
        case.memory_status = "not_indexed"
        case.memory_opted_out = True
        case.memory_indexed_at = None
        case.memory_error = None
        db.commit()

    @staticmethod
    def _generate_point_id(case_id: int) -> str:
        """Generate deterministic Qdrant point ID.

        Uses UUID5 with a namespace to ensure the same case always gets
        the same point ID, enabling idempotent re-indexing.

        Args:
            case_id: The case ID

        Returns:
            Deterministic point ID string
        """
        namespace = UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")  # NAMESPACE_DNS
        point_uuid = uuid5(namespace, f"ops-intelligence:operational-case:{case_id}")
        return str(point_uuid)

    @staticmethod
    def _build_payload(case: OperationalCaseEntity, vector: list[float]) -> dict:
        """Build Qdrant payload from case.

        Only stores retrieval metadata, not the full mutable case.

        Args:
            case: The operational case
            vector: The embedding vector

        Returns:
            Dictionary with payload fields for Qdrant
        """
        finding = case.finding_snapshot or {}

        payload = {
            "case_id": case.id,
            "finding_id": case.finding_id,
            "analysis_run_id": case.analysis_run_id,
            "service": finding.get("service"),
            "service_key": service_key(finding.get("service")),
            "metric_name": finding.get("metric_name"),
            "provider": finding.get("provider", "generic"),
            "category": finding.get("category"),
            "severity": finding.get("health_status"),
            "importance_score": finding.get("importance_score", 0.0),
            "case_status": case.case_status,
            "investigation_status": derive_case_status(case)[1],
            "rca_status": case.root_cause_status,
            "rca_verified": case.root_cause_verified,
            "outcome_status": case.outcome_status,
            "title": case.case_title,
            "origin": "imported" if finding.get("source_type") == "imported" else "detected",
            "source": case.source or "detected",
            "embedding_model": "sentence-transformers/all-MiniLM-L6-v2",
            "content_version": CaseDocumentBuilder.get_content_version(),
            "created_at": case.created_at.isoformat() if case.created_at else None,
            "updated_at": case.updated_at.isoformat() if case.updated_at else None,
        }
        # The recency bonus treats a missing created_at as current, but a null one fails the query.
        if payload["created_at"] is None:
            del payload["created_at"]
        return payload
