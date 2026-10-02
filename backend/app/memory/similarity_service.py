"""Similarity search service for operational cases."""

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.config import MemoryConfig
from backend.app.memory.document_builder import CaseDocumentBuilder
from backend.app.memory.embedder import Embedder
from backend.app.memory.schemas import SimilarCaseMatch, SimilarCasesResponse
from backend.app.memory.vector_store import VectorStore
from backend.app.models.entities import OperationalCaseEntity

logger = logging.getLogger(__name__)


# Similarity tiers shown to people. Scores between a detected case and a written postmortem land
# around 0.4-0.6 even for the same problem (machine-written vs human-written text), so only showing
# matches above the old 0.70 cut-off hid every imported incident from a detected case.
STRONG_MATCH_SCORE = 0.70
POSSIBLE_MATCH_SCORE = 0.40


def match_strength(score: float) -> str:
    return "strong" if score >= STRONG_MATCH_SCORE else "possible"


def same_metric_or_imported(metric_name: str) -> dict:
    """Qdrant condition: a past case on the same metric, or an imported incident.

    Imported incidents (docs/importing-incident-history.md) come from postmortems and carry no
    metric, so a metric filter alone would hide them from every recall. They still go through the
    service filter and the score threshold like any other case."""
    return {
        "should": [
            {"key": "metric_name", "match": {"value": metric_name}},
            {"key": "origin", "match": {"value": "imported"}},
        ]
    }


class SimilarityService:
    """Find similar operational cases using vector search."""

    def __init__(
        self,
        vector_store: VectorStore,
        embedder: Embedder,
        config: MemoryConfig,
    ):
        """Initialize similarity service.

        Args:
            vector_store: VectorStore implementation
            embedder: Embedder implementation
            config: Memory configuration
        """
        self.vector_store = vector_store
        self.embedder = embedder
        self.config = config

    def find_similar_cases(
        self,
        case_id: int,
        db: Session,
        top_k: int | None = None,
        minimum_score: float | None = None,
        same_service_only: bool | None = None,
    ) -> SimilarCasesResponse:
        """Find similar operational cases.

        Flow:
        1. Load current case from PostgreSQL
        2. Build document for current case
        3. Generate embedding
        4. Build Qdrant filters
        5. Search Qdrant
        6. Exclude current case
        7. Load matching cases from PostgreSQL
        8. Preserve Qdrant ranking
        9. Return hydrated results

        Args:
            case_id: ID of the case to find similar cases for
            db: Database session
            top_k: Override configured top_k
            minimum_score: Override configured minimum_score
            same_service_only: Override configured same_service_only

        Returns:
            SimilarCasesResponse with ranked similar cases

        Raises:
            ValueError: If case not found
            RuntimeError: If search fails
        """
        # Step 1: Load current case
        current_case = db.execute(
            select(OperationalCaseEntity).where(OperationalCaseEntity.id == case_id)
        ).scalar_one_or_none()

        if not current_case:
            raise ValueError(f"Case {case_id} not found")

        try:
            # Step 2: Build document
            document = CaseDocumentBuilder.build(current_case)

            # Step 3: Generate embedding
            vector = self.embedder.encode(document)

            # Use configured defaults if not overridden
            search_top_k = top_k or self.config.search.top_k
            search_minimum_score = (
                minimum_score
                if minimum_score is not None
                else self.config.search.minimum_score
            )
            search_same_service = (
                same_service_only
                if same_service_only is not None
                else self.config.search.same_service_only
            )

            # Step 4: Build Qdrant filters
            filters = self._build_filters(
                current_case,
                search_same_service,
            )

            # Step 5: Search Qdrant
            logger.debug(f"Case {case_id}: Searching for similar cases (top_k={search_top_k})")
            search_results = self.vector_store.search(
                vector=vector,
                filters=filters,
                limit=search_top_k * 2,  # Fetch extra to account for exclusions
                score_threshold=search_minimum_score,
            )

            # Step 6: Exclude current case and limit results
            filtered_results = [
                result
                for result in search_results
                if result["payload"].get("case_id") != case_id
            ][:search_top_k]

            # Step 7: Load matching cases from PostgreSQL
            match_case_ids = [result["payload"]["case_id"] for result in filtered_results]
            if not match_case_ids:
                logger.info(f"Case {case_id}: No similar cases found")
                return SimilarCasesResponse(source_case_id=case_id, matches=[])

            # Retrieve full cases in one query
            matched_cases = db.execute(
                select(OperationalCaseEntity).where(
                    OperationalCaseEntity.id.in_(match_case_ids)
                )
            ).scalars().all()

            case_by_id = {case.id: case for case in matched_cases}

            # Step 8-9: Build response preserving Qdrant ranking
            matches: list[SimilarCaseMatch] = []
            for result in filtered_results:
                matched_case = case_by_id.get(result["payload"]["case_id"])
                if not matched_case:
                    continue

                match = SimilarCaseMatch(
                    case_id=matched_case.id,
                    similarity_score=result["score"],
                    title=matched_case.case_title,
                    service=result["payload"].get("service"),
                    metric_name=result["payload"].get("metric_name"),
                    category=result["payload"].get("category"),
                    origin="imported" if matched_case.is_imported else "detected",
                    strength=match_strength(result["score"]),
                    same_service=_same_service(result["payload"].get("service"), current_case),
                    source=matched_case.source,
                    source_id=matched_case.source_id,
                    case_status=matched_case.case_status,
                    investigation_status=matched_case.investigation_status,
                    rca_verified=matched_case.root_cause_verified,
                    root_cause_summary=matched_case.root_cause_summary,
                    corrective_action=matched_case.corrective_action,
                    outcome_status=matched_case.outcome_status,
                    outcome_summary=matched_case.outcome_summary,
                )
                matches.append(match)

            logger.info(f"Case {case_id}: Found {len(matches)} similar cases")

            return SimilarCasesResponse(
                source_case_id=case_id,
                similarity_type="finding_similarity",
                matches=matches,
            )

        except Exception as e:
            logger.error(f"Case {case_id}: Failed to search similar cases: {e}")
            raise RuntimeError(f"Failed to search similar cases: {e}")

    @staticmethod
    def _build_filters(
        case: OperationalCaseEntity,
        same_service_only: bool,
    ) -> dict | None:
        """Build Qdrant filter for case search.

        Filters:
        - Same metric_name, or an imported incident (which has no metric)
        - Same service (if configured)
        - Include open and resolved cases

        Args:
            case: The case to match against
            same_service_only: Whether to filter by service

        Returns:
            Qdrant filter dict or None
        """
        finding = case.finding_snapshot or {}
        metric_name = finding.get("metric_name")

        if not metric_name:
            return None

        # Build filters using Qdrant syntax
        filters = {"must": [same_metric_or_imported(metric_name)]}

        # Add service filter if configured
        if same_service_only and finding.get("service"):
            filters["must"].append({
                "key": "service",
                "match": {
                    "value": finding.get("service"),
                },
            })

        return filters


def _same_service(service: str | None, case: OperationalCaseEntity) -> bool:
    current = (case.finding_snapshot or {}).get("service")
    return bool(service and current and service.lower() == current.lower())
