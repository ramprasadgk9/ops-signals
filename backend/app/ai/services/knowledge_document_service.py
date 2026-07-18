"""Knowledge document generation helper."""

from __future__ import annotations


class KnowledgeDocumentService:
    def build_document(self, title: str, body: str, source_path: str) -> dict[str, str]:
        return {"title": title, "body": body, "source_path": source_path}
