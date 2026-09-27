"""Bootstrap application knowledge for the Operational Intelligence Assistant."""

from __future__ import annotations

import hashlib
import inspect
import logging
import re
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, NAMESPACE_URL, uuid5

from qdrant_client import QdrantClient
from qdrant_client.models import Distance, FieldCondition, Filter, MatchValue, PointStruct, VectorParams

from backend.app.behavior_intelligence.loader import load_definitions
from backend.app.capabilities.builtins import BUILTIN_CAPABILITIES
from backend.app.models.entities import Base
from backend.app.assistant.markdown_sections import split_sections
from backend.app.memory.embedder import Embedder
from intelligence.analyzer_registry import AnalyzerRegistration, AnalyzerRegistrationError, instantiate, load_registrations
from intelligence.analyzers.base import Analyzer

logger = logging.getLogger(__name__)

# The embedding model (all-MiniLM-L6-v2) reads at most 256 tokens and silently ignores the rest,
# so anything past roughly the first 1,000 characters of a chunk is invisible to search. Chunks
# stay under that, heading path included.
CHUNK_CHARS = 900
# Part of every document's content hash. Bump it when chunking or the stored payload changes, so
# the next bootstrap re-embeds every document instead of skipping the ones whose text is unchanged.
INDEX_VERSION = 3
# Longest section kept whole alongside its windows for quoting.
SECTION_TEXT_CHARS = 8000


@dataclass(slots=True)
class KnowledgeChunk:
    # "Security model > Turning on authentication", without the document's own title.
    section: str
    anchor: str
    text: str
    # The whole section when `text` is one window of it, for picking the passage to quote: the
    # window that matched can end on "like this:" with its code block in the next window.
    section_text: str = ""

    def embedding_text(self, title: str) -> str:
        heading = " > ".join(part for part in (title, self.section) if part)
        return f"{heading}\n{self.text}" if heading else self.text


def _markdown_title(content: str) -> str | None:
    """The document's first "# " heading - its real title ("Security model"), which reads better
    in a citation than one derived from the file name ("Security Model")."""
    for section in split_sections(content)[:2]:
        if section.level == 1:
            return section.heading
    return None


def _windows(text: str, size: int) -> list[str]:
    """`text` in pieces of at most `size` characters, split on blank lines where possible so a
    paragraph, list or code block stays whole."""
    pieces: list[str] = []
    current = ""
    for paragraph in re.split(r"\n\s*\n", text):
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        candidate = f"{current}\n\n{paragraph}" if current else paragraph
        if len(candidate) <= size:
            current = candidate
            continue
        if current:
            pieces.append(current)
        while len(paragraph) > size:
            cut = paragraph.rfind("\n", 0, size)
            cut = cut if cut > size // 2 else size
            pieces.append(paragraph[:cut].rstrip())
            paragraph = paragraph[cut:].lstrip()
        current = paragraph
    if current:
        pieces.append(current)
    return pieces


def _chunk_document(content: str, title: str) -> list[KnowledgeChunk]:
    """One chunk per Markdown section, so a search hit can be cited to the section that holds the
    answer. A section too long to embed is windowed, every window keeping its section's heading. A
    document short enough to embed whole (an ADR, a generated concept doc) stays one chunk."""
    if len(content) + len(title) < CHUNK_CHARS:
        return [KnowledgeChunk(section="", anchor="", text=content.strip())]
    chunks: list[KnowledgeChunk] = []
    for section in split_sections(content):
        path = section.heading_path
        # The document's own "# Title" is already the chunk's title, not a section of it.
        if path and section.level == 1:
            path = path[1:]
        elif len(path) > 1 and path[0] == title:
            path = path[1:]
        breadcrumb = " > ".join(path)
        body = section.text
        if section.level:
            body = body.split("\n", 1)[1].strip() if "\n" in body else ""
        if not body:
            continue
        budget = max(CHUNK_CHARS - len(title) - len(breadcrumb) - 4, CHUNK_CHARS // 2)
        windows = _windows(body, budget)
        section_text = body[:SECTION_TEXT_CHARS] if len(windows) > 1 else ""
        for window in windows:
            chunks.append(KnowledgeChunk(section=breadcrumb, anchor=section.anchor, text=window, section_text=section_text))
    return chunks or [KnowledgeChunk(section="", anchor="", text=content.strip())]


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
class _IndexedDocument:
    source_path: str
    content_hash: str


@dataclass(slots=True)
class KnowledgeVerificationResult:
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
    # Source paths ("docs/security-model.md", "generated://analyzers/trend") by what happened.
    added: list[str] = field(default_factory=list)
    changed: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    unchanged_documents: int = 0
    chunks_embedded: int = 0
    forced: bool = False
    started_at: str = ""
    duration_ms: int = 0


@dataclass(slots=True)
class KnowledgeChanges:
    """Docs that differ from the index right now - what a reindex would do - found by content
    hash, without embedding anything."""

    added: list[str] = field(default_factory=list)
    changed: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ApplicationKnowledgeStatus:
    collection_name: str
    collection_exists: bool
    vector_count: int
    required_documents_present: bool
    missing_document_ids: list[str] = field(default_factory=list)
    # The most recent bootstrap in this process (startup or a reindex request); None before one.
    last_bootstrap: ApplicationKnowledgeBootstrapResult | None = None
    # Documents currently indexed, and docs that changed since (None when it couldn't be checked).
    document_count: int = 0
    pending_changes: KnowledgeChanges | None = None
    # Whether this server may write files - the Docs check page saves golden questions only then.
    docs_authoring_enabled: bool = False


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
        # Startup and a reindex request can overlap; two runs interleaving deletes and upserts of
        # the same document would leave it half-indexed.
        self._lock = threading.Lock()
        self.last_result: ApplicationKnowledgeBootstrapResult | None = None

    def bootstrap(self, force: bool = False) -> ApplicationKnowledgeBootstrapResult:
        """Brings the index in line with the current docs: embeds added and changed documents,
        deletes removed ones, and skips documents whose content hash is unchanged. `force`
        re-embeds every document."""
        with self._lock:
            started = time.monotonic()
            started_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
            result = self._bootstrap(force)
            result.forced = force
            result.started_at = started_at
            result.duration_ms = int((time.monotonic() - started) * 1000)
            self.last_result = result
            logger.info(
                "Knowledge index: %d added, %d changed, %d removed, %d unchanged, %d chunks embedded in %d ms%s",
                len(result.added), len(result.changed), len(result.removed), result.unchanged_documents,
                result.chunks_embedded, result.duration_ms, " (forced)" if force else "",
            )
            return result

    def _bootstrap(self, force: bool) -> ApplicationKnowledgeBootstrapResult:
        self._ensure_collection()
        existing = self._existing_documents()
        documents = self._build_documents()
        added: list[str] = []
        changed: list[str] = []
        removed: list[str] = []
        unchanged = 0
        chunks_embedded = 0

        # A document that's no longer produced at all - moved to docs/archive/, renamed, deleted -
        # would otherwise stay indexed forever: this loop only ever upserts what _build_documents()
        # currently returns, it never previously deleted anything. Confirmed live, not
        # hypothetical: docs/release-review.md kept scoring as a top search result after being
        # moved into the excluded archive/ directory, because its old points were simply never
        # removed.
        current_ids = {doc.document_id for doc in documents}
        for removed_id in sorted(set(existing) - current_ids):
            self._delete_document(removed_id)
            removed.append(existing[removed_id].source_path or removed_id)

        for doc in documents:
            content_hash = self._content_hash(doc)
            previous = existing.get(doc.document_id)
            if previous and previous.content_hash == content_hash and not force:
                unchanged += 1
                continue
            chunks = _chunk_document(doc.content, doc.title)
            # Replace the document's points wholesale: its chunk count changes whenever a section
            # is added or removed, and a leftover chunk would keep answering with deleted text.
            if previous:
                self._delete_document(doc.document_id)
            vectors = self._encode_all([chunk.embedding_text(doc.title) for chunk in chunks])
            points = []
            for index, (chunk, vector) in enumerate(zip(chunks, vectors)):
                reference = f"{doc.source_path}#{chunk.anchor}" if chunk.anchor else doc.source_path
                payload = {
                    "document_id": doc.document_id,
                    "chunk_index": index,
                    "chunk_count": len(chunks),
                    "document_type": doc.document_type,
                    "topic": doc.topic,
                    "title": doc.title,
                    "section": chunk.section,
                    "anchor": chunk.anchor,
                    "reference": reference,
                    "related_components": doc.related_components,
                    "source_type": doc.source_type,
                    "source_path": doc.source_path,
                    "version": doc.version,
                    "summary": chunk.text,
                    "section_text": chunk.section_text,
                    "content_hash": content_hash,
                    **doc.metadata,
                }
                points.append(PointStruct(id=self._point_id(f"{doc.document_id}:chunk:{index}"), vector=vector, payload=payload))
            self.client.upsert(collection_name=self.COLLECTION_NAME, points=points)
            chunks_embedded += len(points)
            (changed if previous else added).append(doc.source_path or doc.document_id)

        return ApplicationKnowledgeBootstrapResult(
            collection_name=self.COLLECTION_NAME,
            created_documents=len(added),
            updated_documents=len(changed),
            verification=self.verify_required_documents(),
            added=added,
            changed=changed,
            removed=removed,
            unchanged_documents=unchanged,
            chunks_embedded=chunks_embedded,
        )

    def _content_hash(self, doc: ApplicationKnowledgeDocument) -> str:
        """Changes whenever anything that goes into a document's points would: its text and
        metadata, how documents are chunked (INDEX_VERSION), or the embedding model."""
        model = getattr(self.embedder, "model_name", "")
        parts = [str(INDEX_VERSION), model, doc.title, doc.source_path, doc.document_type, doc.topic, doc.version, repr(sorted(doc.metadata.items())), repr(doc.related_components), doc.content]
        return hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()

    def get_status(self) -> ApplicationKnowledgeStatus:
        exists = self._collection_exists()
        vector_count = self._vector_count() if exists else 0
        verification = self.verify_required_documents() if exists else KnowledgeVerificationResult(False, 0, False, sorted(self.REQUIRED_DOCUMENT_IDS))
        existing = self._existing_documents() if exists else {}
        try:
            pending = self._diff(existing, self._build_documents())
        except Exception as exc:
            logger.warning("Could not check docs for changes since the last reindex: %s", exc)
            pending = None
        return ApplicationKnowledgeStatus(
            collection_name=self.COLLECTION_NAME,
            collection_exists=exists,
            vector_count=vector_count,
            required_documents_present=verification.required_documents_present,
            missing_document_ids=verification.missing_document_ids,
            last_bootstrap=self.last_result,
            document_count=len(existing),
            pending_changes=pending,
        )

    def pending_changes(self) -> KnowledgeChanges:
        """What a reindex would do right now, without doing it (about 20 ms: reads and hashes the
        docs, embeds nothing)."""
        return self._diff(self._existing_documents() if self._collection_exists() else {}, self._build_documents())

    def _diff(self, existing: dict[str, "_IndexedDocument"], documents: list[ApplicationKnowledgeDocument]) -> KnowledgeChanges:
        changes = KnowledgeChanges()
        current = {doc.document_id for doc in documents}
        for doc in documents:
            previous = existing.get(doc.document_id)
            if previous is None:
                changes.added.append(doc.source_path or doc.document_id)
            elif previous.content_hash != self._content_hash(doc):
                changes.changed.append(doc.source_path or doc.document_id)
        changes.removed = sorted(existing[document_id].source_path or document_id for document_id in set(existing) - current)
        return changes

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
        return sorted(self._existing_documents())

    def _existing_documents(self) -> dict[str, "_IndexedDocument"]:
        """Every indexed document id with its source path and content hash. Paged: with one point
        per section the collection holds well over one scroll page, and an id missed here is never
        purged when its document goes away."""
        documents: dict[str, _IndexedDocument] = {}
        offset = None
        try:
            while True:
                records, offset = self.client.scroll(
                    collection_name=self.COLLECTION_NAME,
                    with_payload=["document_id", "source_path", "content_hash"],
                    with_vectors=False,
                    limit=1000,
                    offset=offset,
                )
                for point in records:
                    payload = point.payload or {}
                    document_id = payload.get("document_id")
                    if not document_id:
                        continue
                    known = documents.get(str(document_id))
                    content_hash = payload.get("content_hash") or ""
                    # A document whose chunks disagree (a run interrupted halfway) counts as changed.
                    if known and known.content_hash != content_hash:
                        content_hash = ""
                    documents[str(document_id)] = _IndexedDocument(source_path=payload.get("source_path") or "", content_hash=content_hash)
                if offset is None:
                    return documents
        except Exception:
            return documents

    def _delete_document(self, document_id: str) -> None:
        self.client.delete(
            collection_name=self.COLLECTION_NAME,
            points_selector=Filter(must=[FieldCondition(key="document_id", match=MatchValue(value=document_id))]),
        )

    def _encode_all(self, texts: list[str]) -> list[list[float]]:
        encode_batch = getattr(self.embedder, "encode_batch", None)
        if encode_batch is not None:
            return encode_batch(texts)
        return [self.embedder.encode(text) for text in texts]

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
        docs_dir = self.repo_root / "docs"
        # Recursive, not docs_dir.glob("*.md") - a flat glob silently skipped docs/adr/*.md
        # entirely for as long as this method existed. "archive" is excluded so dated,
        # point-in-time review docs don't compete with living documentation in search results.
        nested_docs = sorted(
            path for path in docs_dir.rglob("*.md")
            if "archive" not in path.relative_to(docs_dir).parts
        )
        for path in [self.repo_root / "README.md", *nested_docs]:
            if not path.exists():
                continue
            text = path.read_text(encoding="utf-8")
            relative = path.relative_to(self.repo_root)
            # From the relative path, not the file stem: README.md and docs/README.md both have the
            # stem "README", so a stem id made the second overwrite the first and the project
            # README was never searchable at all.
            doc_id = f"repo-{relative.with_suffix('').as_posix()}"
            docs.append(
                ApplicationKnowledgeDocument(
                    document_id=doc_id,
                    document_type="documentation",
                    topic=path.stem.replace("-", "_"),
                    title=_markdown_title(text) or path.stem.replace("-", " ").title(),
                    content=text,
                    related_components=["documentation"],
                    source_type="repo",
                    source_path=relative.as_posix(),
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

    def analyzer_catalog(self) -> list[tuple[str, str, str]]:
        """(analyzer id, display name, what it finds) for every registered analyzer, in registry
        order - the answer to "which analyzers are there?", and the "What Are Analyzers?" list."""
        return [
            (str(doc.metadata["analyzer_id"]), str(doc.metadata["display_name"]), str(doc.metadata["purpose"]))
            for doc in self._analyzer_documents()
        ]

    def _analyzers_overview(self) -> ApplicationKnowledgeDocument:
        catalog = self.analyzer_catalog()
        lines = "\n".join(f"- {analyzer_id} ({name}): {purpose}" for analyzer_id, name, purpose in catalog)
        content = (
            "Analyzers inspect normalized metric time-series data and produce lower-level operational signals. "
            "Their outputs feed findings and behavior definitions. "
            f"There are {len(catalog)} registered analyzers, and what each one finds:\n{lines}\n\n"
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
        for registration, analyzer in self._analyzer_registrations():
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
            elif analyzer.analyzer_id == "baseline_shift":
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
            else:
                # Any other registered analyzer - including ones added through the Add Analyzer
                # wizard - is described from what it declares about itself, never from another
                # analyzer's hand-written text.
                purpose = capability.description
                detects = _own_docstring(analyzer) or capability.description
                # Capability question ids are catalog-wide ("What changed yesterday?", "Is the service
                # healthy?"), not this analyzer's own questions; listing them made every such page
                # match generic questions. Only hand-written analyzers above carry their own.
                questions = []
                limitations = ["See the analyzer's own documentation and registry settings for its thresholds."]
                preprocessing = ["Use normalized metric data; empty time buckets stay as gaps rather than being filled."]
                min_samples = registration.router.eligibility_rules.get("min_samples")
                required_sample = f"At least {min_samples} valid samples." if min_samples else "Enough samples for the analyzer's own checks."
                required_history = required_sample
            # Only what is specific to this analyzer. Lines that read the same on every analyzer page
            # ("Supported metric types: ...", "Current implementation status: ...") made the pages look
            # alike to search and were quoted as if they answered a question.
            content = "\n".join(
                [
                    f"Analyzer name: {title}",
                    f"Analyzer ID: {analyzer.analyzer_id}",
                    f"Purpose: {purpose}",
                    *([f"What it detects: {detects}"] if detects != purpose else []),
                    *(["Operational questions:", *[f"- {question}" for question in questions]] if questions else []),
                    f"Required sample size: {required_sample}",
                    *([f"Required history: {required_history}"] if required_history != required_sample else []),
                    "Limitations:",
                    *[f"- {item}" for item in limitations],
                    "Preprocessing requirements:",
                    *[f"- {item}" for item in preprocessing],
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
                        "purpose": purpose,
                        "supported_question_ids": capability.supported_question_ids,
                    },
                )
            )
        return docs

    def _registered_analyzers(self) -> list[Analyzer]:
        return [analyzer for _, analyzer in self._analyzer_registrations()]

    def _analyzer_registrations(self) -> list[tuple[AnalyzerRegistration, Analyzer]]:
        """Every enabled analyzer in config/analyzer_registry.d/ - the same registry the pipeline
        runs from - so the assistant knows about each analyzer that can actually run, including
        ones added through the Add Analyzer wizard. This used to be a fixed list of four."""
        pairs: list[tuple[AnalyzerRegistration, Analyzer]] = []
        for registration in load_registrations(self.repo_root / "config" / "analyzer_registry.d"):
            if not registration.enabled:
                continue
            try:
                pairs.append((registration, instantiate(registration)))
            except AnalyzerRegistrationError as exc:
                logger.warning("Skipping analyzer %s in assistant knowledge: %s", registration.analyzer_id, exc)
        return pairs


def _own_docstring(analyzer: Analyzer) -> str:
    """The analyzer class's own docstring, not one inherited from a base class."""
    doc = type(analyzer).__dict__.get("__doc__")
    return " ".join(inspect.cleandoc(doc).split()) if doc else ""