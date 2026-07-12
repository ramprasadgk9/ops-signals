from __future__ import annotations

from typing import Sequence

from ops_signals.config import EmbeddingsConfig


class SummaryEmbedder:
    def __init__(self, config: EmbeddingsConfig) -> None:
        self.config = config
        self._model = None

    def enabled(self) -> bool:
        return self.config.enabled

    def embed(self, text: str) -> Sequence[float] | None:
        if not self.config.enabled:
            return None
        if self._model is None:
            try:
                from sentence_transformers import SentenceTransformer
            except ImportError as exc:
                raise RuntimeError("sentence-transformers is required when embeddings are enabled") from exc
            self._model = SentenceTransformer(self.config.model)
        vector = self._model.encode(text)
        return [float(value) for value in vector.tolist()]
