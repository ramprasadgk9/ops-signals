"""`ops-signals import-cases <folder>`: the folder form of the import wizard, for bulk imports and
mounted folders. Same parser, same idempotent writes, same batch record as the API."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from backend.app.case_import.parsers import ImportSettings, ImportSettingsError, parse_files
from backend.app.case_import.service import CaseImportService

_READABLE_SUFFIXES = {".md", ".markdown", ".csv", ".zip", ".yaml", ".yml"}


def add_parser(subparsers) -> None:
    parser = subparsers.add_parser("import-cases", help="Import past incidents from a folder as resolved cases")
    parser.add_argument("folder", help="Folder of .md / .csv / .zip exports (read recursively)")
    parser.add_argument("--dry-run", action="store_true", help="Show what would happen without writing")
    parser.add_argument("--profile", help="markdown, generic-csv, jira-csv or pagerduty-csv (default: detect)")
    parser.add_argument("--source", help="Source label stored on each case (default: from the profile)")
    parser.add_argument("--no-index", action="store_true", help="Write cases without indexing them into memory")
    parser.add_argument("--database-url", help="Database to import into (default: OPS_SIGNALS_DATABASE_URL)")


def run(args: argparse.Namespace) -> int:
    from backend.app.main import load_memory_config
    from backend.app.models.db import get_engine, get_session_local, init_engine
    from backend.app.models.entities import Base
    from backend.app.models.schema_compat import ensure_case_behavior_link_schema, ensure_case_import_schema

    folder = Path(args.folder)
    if not folder.is_dir():
        print(f"Not a folder: {folder}")
        return 2
    files = [
        (str(path.relative_to(folder)), path.read_bytes())
        for path in sorted(folder.rglob("*"))
        if path.is_file() and path.suffix.lower() in _READABLE_SUFFIXES and not path.name.startswith(".")
    ]
    try:
        upload = parse_files(files, ImportSettings(profile=args.profile, source=args.source))
    except ImportSettingsError as exc:
        print(f"Cannot import: {exc}")
        return 2

    init_engine(args.database_url)
    Base.metadata.create_all(bind=get_engine())
    ensure_case_behavior_link_schema(get_engine())
    ensure_case_import_schema(get_engine())

    with get_session_local()() as db:
        indexer, config = (None, None) if args.no_index or args.dry_run else _memory_indexer(load_memory_config())
        service = CaseImportService(db, indexer, config)
        plan = service.plan(upload)
        for warning in upload.warnings:
            print(f"warning: {warning}")
        for item in plan.items:
            if item.action == "skipped":
                print(f"skipped {item.record.ref}: {', '.join(item.record.problems)}")
        if args.dry_run:
            print(f"Dry run: {json.dumps(plan.counts)}")
            return 0
        result = service.apply(plan, source_files=[name for name, _ in files])
        print(f"Import {result.batch_id}: {json.dumps(result.counts)}, indexed {result.indexed}, index failures {result.index_failed}")
        if indexer is None:
            print("Memory is not enabled, so the cases are not indexed yet; similar-case search will not find them.")
    return 0


def _memory_indexer(config):
    if not (config and config.enabled):
        return None, None
    from qdrant_client import QdrantClient

    from backend.app.memory.embedder import CaseEmbedder
    from backend.app.memory.indexer import CaseMemoryIndexer
    from backend.app.memory.qdrant_initializer import QdrantInitializer
    from backend.app.memory.vector_store import QdrantVectorStore

    client = QdrantClient(url=config.vector_store.url, api_key=config.vector_store.api_key)
    QdrantInitializer.initialize(client)
    vector_store = QdrantVectorStore(client=client, collection_name=config.vector_store.collection_name)
    return CaseMemoryIndexer(vector_store, CaseEmbedder(model_name=config.embedding.model), config), config
