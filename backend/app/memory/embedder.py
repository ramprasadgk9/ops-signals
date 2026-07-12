"""Embedding service using sentence-transformers."""

from abc import ABC, abstractmethod

from sentence_transformers import SentenceTransformer


class Embedder(ABC):
    """Abstract interface for embedding generation."""

    @abstractmethod
    def encode(self, text: str) -> list[float]:
        """Encode text to vector embedding.

        Args:
            text: Text to embed

        Returns:
            List of floats representing the embedding
        """
        ...

    @property
    @abstractmethod
    def model_name(self) -> str:
        """Get the name of the embedding model."""
        ...

    @property
    @abstractmethod
    def dimension(self) -> int:
        """Get the dimension of embeddings produced by this model."""
        ...


class CaseEmbedder(Embedder):
    """Embedding service using Sentence Transformers."""

    _instance: "CaseEmbedder | None" = None

    def __new__(cls, model_name: str = "sentence-transformers/all-MiniLM-L6-v2"):
        """Singleton pattern to ensure model is loaded only once."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self, model_name: str = "sentence-transformers/all-MiniLM-L6-v2"):
        """Initialize embedder with Sentence Transformers model.

        Args:
            model_name: Name of the model to load from HuggingFace
        """
        if self._initialized:
            return

        try:
            self._model = SentenceTransformer(model_name)
            self._model_name = model_name
            self._initialized = True
        except Exception as e:
            raise RuntimeError(f"Failed to load embedding model {model_name}: {e}")

    def encode(self, text: str) -> list[float]:
        """Encode text to embedding vector.

        Args:
            text: Text to embed

        Returns:
            List of floats representing the 384-dimensional embedding
        """
        try:
            embedding = self._model.encode(text, normalize_embeddings=True)
            vector = embedding.tolist()
            
            # Verify dimension
            if len(vector) != self.dimension:
                raise ValueError(
                    f"Expected embedding dimension {self.dimension}, got {len(vector)}"
                )
            
            return vector
        except Exception as e:
            raise RuntimeError(f"Failed to encode text: {e}")

    @property
    def model_name(self) -> str:
        """Get model name."""
        return self._model_name

    @property
    def dimension(self) -> int:
        """Get embedding dimension."""
        return 384
