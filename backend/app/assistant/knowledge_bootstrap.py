"""Bootstrap application knowledge for the Operational Intelligence Assistant."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from uuid import UUID, NAMESPACE_URL, uuid5

from qdrant_client import QdrantClient
from qdrant_client.models import Distance, PointStruct, VectorParams

from backend.app.behavior_intelligence.loader import load_definitions
from backend.app.capabilities.builtins import BUILTIN_CAPABILITIES
from backend.app.models.entities import Base
from backend.app.memory.embedder import Embedder
from intelligence.analyzers import BaselineShiftAnalyzer, RupturesAnalyzer, TrendAnalyzer, ZScoreAnomalyAnalyzer


@dataclass(slots=True)
class ApplicationKnowledgeDocument:
    document_id: str
    document_type: str
    topic: str
    title: str
    content: str
    related_components: list[str] = field(default_factory=list)
    source_type: str = "generated"
    source_path: str = ""
    version: str = "current"
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(slots=True)
class KnowledgeVerificationResult:
    collection_exists: bool
    vector_count: int
    required_documents_present: bool
    missing_document_ids: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ApplicationKnowledgeStatus:
    collection_name: str
    collection_exists: bool
    vector_count: int
    required_documents_present: bool
    missing_document_ids: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ApplicationKnowledgeBootstrapResult:
    collection_name: str
    created_documents: int
    updated_documents: int
    verification: KnowledgeVerificationResult


class ApplicationKnowledgeBootstrapService:
    COLLECTION_NAME = "operational_intelligence_docs"
    VECTOR_SIZE = 384
    REQUIRED_DOCUMENT_IDS = {
        "application-overview",
        "analyzers-overview",
        "analyzer-types-overview",
        "signals-overview",
        "findings-overview",
        "behaviors-overview",
        "cases-overview",
        "architecture-overview",
        "data-flow-overview",
        "storage-overview",
        "vector-database-overview",
    }

    def __init__(self, client: QdrantClient, embedder: Embedder, repo_root: Path | None = None) -> None:
        self.client = client
        self.embedder = embedder
        self.repo_root = repo_root or Path.cwd()

    def bootstrap(self, force: bool = False) -> ApplicationKnowledgeBootstrapResult:
        self._ensure_collection()
        existing = self._existing_document_ids()
        documents = self._build_documents()
        created = 0
        updated = 0

        for doc in documents:
            point_id = self._point_id(doc.document_id)
            payload = {
                "document_id": doc.document_id,
                "document_type": doc.document_type,
                "topic": doc.topic,
                "title": doc.title,
                "related_components": doc.related_components,
                "source_type": doc.source_type,
                "source_path": doc.source_path,
                "version": doc.version,
                "summary": doc.content[:1200],
                **doc.metadata,
            }
            vector = self.embedder.encode(doc.content[:8000])
            self.client.upsert(
                collection_name=self.COLLECTION_NAME,
                points=[PointStruct(id=point_id, vector=vector, payload=payload)],
            )
            if doc.document_id in existing:
                updated += 1
            else:
                created += 1

        verification = self.verify_required_documents()
        return ApplicationKnowledgeBootstrapResult(
            collection_name=self.COLLECTION_NAME,
            created_documents=created,
            updated_documents=updated,
            verification=verification,
        )

    def get_status(self) -> ApplicationKnowledgeStatus:
        exists = self._collection_exists()
        vector_count = self._vector_count() if exists else 0
        verification = self.verify_required_documents() if exists else KnowledgeVerificationResult(False, 0, False, sorted(self.REQUIRED_DOCUMENT_IDS))
        return ApplicationKnowledgeStatus(
            collection_name=self.COLLECTION_NAME,
            collection_exists=exists,
            vector_count=vector_count,
            required_documents_present=verification.required_documents_present,
            missing_document_ids=verification.missing_document_ids,
        )

    def verify_required_documents(self) -> KnowledgeVerificationResult:
        exists = self._collection_exists()
        if not exists:
            return KnowledgeVerificationResult(False, 0, False, sorted(self.REQUIRED_DOCUMENT_IDS))
        ids = set(self._existing_document_ids())
        missing = sorted(self.REQUIRED_DOCUMENT_IDS - ids)
        return KnowledgeVerificationResult(True, self._vector_count(), not missing, missing)

    def _ensure_collection(self) -> None:
        if self._collection_exists():
            return
        self.client.create_collection(
            collection_name=self.COLLECTION_NAME,
            vectors_config=VectorParams(size=self.VECTOR_SIZE, distance=Distance.COSINE),
        )
        for field in ["document_id", "document_type", "topic", "source_type", "version"]:
            try:
                self.client.create_payload_index(
                    collection_name=self.COLLECTION_NAME,
                    field_name=field,
                    field_schema="keyword",
                )
            except Exception:
                pass

    def _collection_exists(self) -> bool:
        collections = self.client.get_collections()
        return any(collection.name == self.COLLECTION_NAME for collection in collections.collections)

    def _vector_count(self) -> int:
        try:
            return int(self.client.count(collection_name=self.COLLECTION_NAME, exact=True).count)
        except Exception:
            return 0

    def _existing_document_ids(self) -> list[str]:
        try:
            records, _ = self.client.scroll(
                collection_name=self.COLLECTION_NAME,
                with_payload=True,
                with_vectors=False,
                limit=1000,
            )
            return [str(point.payload.get("document_id")) for point in records if point.payload and point.payload.get("document_id")]
        except Exception:
            return []

    def _point_id(self, document_id: str) -> str:
        namespace = UUID("6ba7b811-9dad-11d1-80b4-00c04fd430c8")
        return str(uuid5(namespace, f"ops-intelligence:assistant-doc:{document_id}"))

    def _build_documents(self) -> list[ApplicationKnowledgeDocument]:
        documents = [
            self._application_overview(),
            self._analyzers_overview(),
            self._analyzer_types_overview(),
            self._signals_overview(),
            self._findings_overview(),
            self._behaviors_overview(),
            self._cases_overview(),
            self._architecture_overview(),
            self._data_flow_overview(),
            self._storage_overview(),
            self._vector_database_overview(),
        ]
        documents.extend(self._analyzer_documents())
        documents.extend(self._repo_docs())
        return documents

    def _repo_docs(self) -> list[ApplicationKnowledgeDocument]:
        docs: list[ApplicationKnowledgeDocument] = []
        for path in [self.repo_root / "README.md", *sorted((self.repo_root / "docs").glob("*.md"))]:
            if not path.exists():
                continue
            text = path.read_text(encoding="utf-8")
            doc_id = f"repo-{path.stem}"
            docs.append(
                ApplicationKnowledgeDocument(
                    document_id=doc_id,
                    document_type="documentation",
                    topic=path.stem.replace("-", "_"),
                    title=path.stem.replace("-", " ").title(),
                    content=text,
                    related_components=["documentation"],
                    source_type="repo",
                    source_path=str(path.relative_to(self.repo_root)),
                )
            )
        return docs

    def _application_overview(self) -> ApplicationKnowledgeDocument:
        content = (
            "Ops Signals is a vendor-neutral Operational Intelligence framework. "
            "It transforms normalized time-series data into signals, findings, behavior findings, cases, and searchable operational memory. "
            "The application is designed to be explainable, deterministic, and self-hosted.\n\n"
            "Example: a metric like checkout-api's cpu_usage is normalized, analyzed for a baseline shift, "
            "turned into a Finding ('CPU usage baseline shifted'), and can be promoted into a Case where "
            "someone records the root cause and resolution - which then becomes searchable operational memory "
            "for the next time a similar issue happens."
        )
        return ApplicationKnowledgeDocument(
            document_id="application-overview",
            document_type="overview",
            topic="application",
            title="Application Overview",
            content=content,
            related_components=["analyzers", "signals", "findings", "behaviors", "cases", "memory"],
            source_path="generated://application-overview",
        )

    def _analyzers_overview(self) -> ApplicationKnowledgeDocument:
        analyzer_names = ", ".join(analyzer.analyzer_id for analyzer in self._registered_analyzers())
        content = (
            "Analyzers inspect normalized metric time-series data and produce lower-level operational signals. "
            "Their outputs feed findings and behavior definitions. "
            f"Registered analyzers currently include: {analyzer_names}.\n\n"
            "Example: the ruptures analyzer scans a metric's time series for a persistent change point - "
            "e.g. checkout-api cpu_usage sitting near 42% for hours, then jumping to a new baseline near 79% "
            "and staying there. It emits a baseline_shift signal with the change point, the percent change, "
            "and a confidence score, which downstream findings and behaviors can then use as evidence."
        )
        return ApplicationKnowledgeDocument(
            document_id="analyzers-overview",
            document_type="concept",
            topic="analyzers",
            title="What Are Analyzers?",
            content=content,
            related_components=["analyzer registry", "signals", "findings", "behaviors"],
            source_path="generated://concepts/analyzers-overview",
        )

    def _analyzer_types_overview(self) -> ApplicationKnowledgeDocument:
        analyzers = self._registered_analyzers()
        lines = [
            "Analyzer types in the application include baseline change detection, persistent change-point detection, trend analysis, and anomaly detection.",
        ]
        for analyzer in analyzers:
            lines.append(f"- {analyzer.analyzer_id}: {analyzer.capability().description}")
        return ApplicationKnowledgeDocument(
            document_id="analyzer-types-overview",
            document_type="overview",
            topic="analyzer_types",
            title="Analyzer Types Overview",
            content="\n".join(lines),
            related_components=["analyzers", "capabilities"],
            source_path="generated://analyzer-types-overview",
        )

    def _signals_overview(self) -> ApplicationKnowledgeDocument:
        content = (
            "Signals are analyzer outputs stored as operational evidence. "
            "They include analyzer ID, metric name, service metadata, severity, confidence, summary, evidence payloads, and importance scores. "
            "Signals are inputs to findings and behavior evaluation.\n\n"
            "Example: one baseline_shift signal on its own is just one analyzer's opinion about one metric. "
            "A Finding is what groups one or more signals (say, a baseline_shift on cpu_usage plus a related "
            "anomaly on request_latency) into a single higher-level, investigatable item with its own title "
            "and importance score."
        )
        return ApplicationKnowledgeDocument(
            document_id="signals-overview",
            document_type="overview",
            topic="signals",
            title="Signals Overview",
            content=content,
            related_components=["signals", "analyzers", "findings"],
            source_path="generated://signals-overview",
        )

    def _findings_overview(self) -> ApplicationKnowledgeDocument:
        content = (
            "Findings are aggregated operational interpretations that group signals into higher-level insights. "
            "They include title, summary, category, health status, importance score, and supporting signal IDs.\n\n"
            "Example: a Finding titled 'CPU usage baseline shifted' on checkout-api, category behavior_change, "
            "health_status critical, importance_score 0.94 - built from the baseline_shift signal that detected "
            "the change point. From the Findings page, that item can be promoted into a Case for investigation."
        )
        return ApplicationKnowledgeDocument(
            document_id="findings-overview",
            document_type="overview",
            topic="findings",
            title="Findings Overview",
            content=content,
            related_components=["findings", "signals", "cases"],
            source_path="generated://findings-overview",
        )

    def _behaviors_overview(self) -> ApplicationKnowledgeDocument:
        behavior_path = self.repo_root / "config" / "behavior_definitions.d"
        behavior_titles = [f"{definition.id}: {definition.title}" for definition in load_definitions(behavior_path)]
        content = (
            "Behavior definitions combine evidence from multiple analyzers and metrics to explain higher-level operational conditions. "
            "They evaluate conditions, correlation windows, and output categories. "
            + ("Current behaviors include: " + "; ".join(behavior_titles) if behavior_titles else "")
            + "\n\nExample: a 'cascading failure' behavior might require a latency anomaly AND an error-rate "
            "anomaly on the same service within a 10-minute correlation window before it fires - so one noisy "
            "metric alone won't trigger it, but a real incident with multiple corroborating signals will."
        )
        return ApplicationKnowledgeDocument(
            document_id="behaviors-overview",
            document_type="overview",
            topic="behaviors",
            title="Behaviors Overview",
            content=content,
            related_components=["behavior definitions", "findings", "signals"],
            source_path=str(behavior_path) if behavior_path.exists() else "generated://behaviors-overview",
        )

    def _cases_overview(self) -> ApplicationKnowledgeDocument:
        content = (
            "Operational cases preserve investigation context, root-cause analysis, corrective action, and outcomes. "
            "Cases are the long-lived operational record and can be indexed into memory for similarity search.\n\n"
            "Example: promoting the 'CPU usage baseline shifted' finding creates a case where an engineer records "
            "the root cause ('deploy at 14:02 raised worker pool size'), the corrective action taken, and the "
            "outcome. Once indexed, the next similar cpu_usage regression can find this case as a match and "
            "reuse the same fix instead of starting from scratch."
        )
        return ApplicationKnowledgeDocument(
            document_id="cases-overview",
            document_type="overview",
            topic="cases",
            title="Cases Overview",
            content=content,
            related_components=["cases", "memory", "RCA", "outcomes"],
            source_path="generated://cases-overview",
        )

    def _architecture_overview(self) -> ApplicationKnowledgeDocument:
        content = (
            "The architecture flows from canonical time-series inputs to normalization, PostgreSQL, analyzer registry, "
            "signals, findings, cases, behavior intelligence, embeddings, Qdrant, and the React UI.\n\n"
            "Example, end to end: a Prometheus metric or CSV row is normalized into a canonical point -> "
            "stored in PostgreSQL -> handed to every analyzer registered for its profile (e.g. ruptures, stumpy) -> "
            "each analyzer that finds something emits a Signal -> signals aggregate into a Finding -> a Finding "
            "can be promoted into a Case -> a resolved Case gets embedded and stored in Qdrant so it's retrievable "
            "the next time someone asks the assistant 'have we seen this before?' in the React UI."
        )
        return ApplicationKnowledgeDocument(
            document_id="architecture-overview",
            document_type="overview",
            topic="architecture",
            title="Architecture Overview",
            content=content,
            related_components=["architecture", "postgresql", "qdrant", "ui"],
            source_path="generated://architecture-overview",
        )

    def _data_flow_overview(self) -> ApplicationKnowledgeDocument:
        content = (
            "Data flows from CSV ingestion or provider-specific inputs through validation and normalization into the analysis pipeline. "
            "Analyzers emit signals, signals aggregate into findings, findings can promote to cases, and cases can be indexed for retrieval.\n\n"
            "Example: an autonomous monitoring run pulls a metric from Prometheus, validates it (rejecting rows "
            "with gaps or negative values where that's not expected), normalizes it into the shared schema, then "
            "hands it to the analyzer registry - the same pipeline a CSV upload or a manual analysis run goes "
            "through."
        )
        return ApplicationKnowledgeDocument(
            document_id="data-flow-overview",
            document_type="overview",
            topic="data_flow",
            title="Data Flow Overview",
            content=content,
            related_components=["ingestion", "normalization", "signals", "findings", "cases", "memory"],
            source_path="generated://data-flow-overview",
        )

    def _storage_overview(self) -> ApplicationKnowledgeDocument:
        content = (
            "PostgreSQL is the system of record for normalized points, signals, findings, cases, capabilities, and question answers. "
            "Qdrant is the retrieval index for case and documentation embeddings.\n\n"
            "Example: a case's root-cause text and status live in PostgreSQL and are always authoritative. A "
            "copy of that same case, converted into an embedding vector, also lives in Qdrant purely so it can "
            "be found by semantic similarity - if the Qdrant copy were lost, it could be rebuilt entirely from "
            "PostgreSQL by re-indexing; the reverse is not true."
        )
        return ApplicationKnowledgeDocument(
            document_id="storage-overview",
            document_type="overview",
            topic="storage",
            title="Storage Overview",
            content=content,
            related_components=["postgresql", "qdrant", "storage"],
            source_path="generated://storage-overview",
        )

    def _vector_database_overview(self) -> ApplicationKnowledgeDocument:
        content = (
            "Qdrant stores embeddings plus metadata for semantic retrieval. "
            "The assistant uses separate collections for operational cases and application knowledge so historical evidence and documentation stay distinct.\n\n"
            "Example: asking 'have we seen this before?' searches the operational_cases collection (real past "
            "incidents); asking 'how does Behavior Intelligence work?' searches the operational_intelligence_docs "
            "collection (generated concept docs and repo documentation) instead - same underlying vector search, "
            "different collection depending on what kind of question it is."
        )
        return ApplicationKnowledgeDocument(
            document_id="vector-database-overview",
            document_type="overview",
            topic="vector_database",
            title="Vector Database Overview",
            content=content,
            related_components=["qdrant", "retrieval", "memory"],
            source_path="generated://vector-database-overview",
        )

    def _analyzer_documents(self) -> list[ApplicationKnowledgeDocument]:
        docs: list[ApplicationKnowledgeDocument] = []
        for analyzer in self._registered_analyzers():
            capability = analyzer.capability()
            title = f"{capability.title} Analyzer"
            if analyzer.analyzer_id == "ruptures":
                purpose = "Detect persistent structural changes in time-series behavior."
                detects = "Baseline shifts, mean changes, variance changes, and change points."
                questions = [
                    "When did normal behavior change?",
                    "Did a deployment create a permanent shift?",
                    "Did metric variance change?",
                ]
                limitations = [
                    "Needs enough history to compare regimes.",
                    "Best when there are at least two meaningful segments.",
                ]
                preprocessing = ["Use normalized, regularly sampled metric data when possible."]
                required_history = "Enough history to compare pre- and post-change segments."
                required_sample = "At least two segments of meaningful history."
            elif analyzer.analyzer_id == "trend":
                purpose = "Detect sustained directional movement over time."
                detects = "Increasing or decreasing movements across the analysis window."
                questions = [
                    "Is the metric trending upward?",
                    "Is the behavior steadily degrading?",
                    "Did the service start moving in a new direction?",
                ]
                limitations = ["Requires at least three points and benefits from a stable baseline."]
                preprocessing = ["Use a numeric metric with a sensible baseline."]
                required_history = "At least a few points across the same analysis window."
                required_sample = "A time series long enough to fit a slope."
            elif analyzer.analyzer_id == "anomaly_zscore":
                purpose = "Detect unusual values and anomalous windows relative to the local mean."
                detects = "Statistical spikes and unusual windows with significant z-scores."
                questions = [
                    "Are there unusual spikes?",
                    "Did the metric exceed a normal range?",
                    "Did a short anomaly window occur?",
                ]
                limitations = ["Works best when the series has variance and enough points to estimate a standard deviation."]
                preprocessing = ["Avoid flat series unless you expect strong spikes."]
                required_history = "Enough points to estimate a meaningful mean and standard deviation."
                required_sample = "At least three points, preferably more."
            else:
                purpose = "Detect sustained changes in the normal operating level."
                detects = "Baseline shifts between the first and second half of the window."
                questions = [
                    "Did the baseline change?",
                    "Did the service move to a new operating level?",
                    "Is the new level materially different?",
                ]
                limitations = ["Needs a numeric series with enough points to compare halves."]
                preprocessing = ["Prefer stable samples with at least one sustained window."]
                required_history = "At least four points."
                required_sample = "A window that can be split into two halves."
            content = "\n".join(
                [
                    f"Analyzer name: {title}",
                    f"Analyzer ID: {analyzer.analyzer_id}",
                    f"Purpose: {purpose}",
                    f"What it detects: {detects}",
                    "Operational questions:",
                    *[f"- {question}" for question in questions],
                    f"Supported metric types: gauge, counter, latency, percentage, and provider-normalized numeric series.",
                    f"Required sample size: {required_sample}",
                    f"Required history: {required_history}",
                    "Parameters:",
                    f"- {capability.description}",
                    "Inputs: normalized metric time-series data with service and metric metadata.",
                    "Outputs: lower-level operational signals with severity, confidence, summary, and evidence.",
                    "Strengths: explainable, deterministic, and aligned with metric behavior.",
                    "Limitations:",
                    *[f"- {item}" for item in limitations],
                    "Preprocessing requirements:",
                    *[f"- {item}" for item in preprocessing],
                    "Current implementation status: implemented and enabled in the current analyzer registry when configured.",
                ]
            )
            docs.append(
                ApplicationKnowledgeDocument(
                    document_id=f"analyzer-{analyzer.analyzer_id}",
                    document_type="analyzer_documentation",
                    topic=analyzer.analyzer_id,
                    title=title,
                    content=content,
                    related_components=["analyzers", "signals", "capabilities"],
                    source_path=f"generated://analyzers/{analyzer.analyzer_id}",
                    metadata={
                        "analyzer_id": analyzer.analyzer_id,
                        "display_name": capability.title,
                        "supported_question_ids": capability.supported_question_ids,
                    },
                )
            )
        return docs

    def _registered_analyzers(self):
        return [
            BaselineShiftAnalyzer(threshold_percent=25),
            RupturesAnalyzer(min_segment_size=5, change_threshold=1.5),
            ZScoreAnomalyAnalyzer(zscore_threshold=3.0, grouping_gap="15m"),
            TrendAnalyzer(min_slope_percent=10),
        ]

