"""
src/rag/embeddings/base.py

FloatChat Base Embedding Provider Abstraction.
Defines the abstract interface that all dense vector embedding providers must implement.
Provides strict validation ensuring generated vectors are finite, non-empty,
and match the declared dimension.
"""

from abc import ABC, abstractmethod
import math
from typing import List

from src.rag.exceptions import EmbeddingGenerationError


class BaseEmbeddingProvider(ABC):
    """
    Abstract Base Class for FloatChat dense vector embedding providers.
    All embedding providers (Ollama, HuggingFace, Gemini, etc.) implement this contract.
    """

    @abstractmethod
    def embed_text(self, text: str) -> List[float]:
        """
        Computes a dense vector embedding for a single text passage or query.

        Args:
            text: Text string to embed.

        Returns:
            List of floats representing the embedding vector.

        Raises:
            EmbeddingGenerationError: If embedding generation fails.
        """
        pass

    @abstractmethod
    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        """
        Computes dense vector embeddings for a batch of text passages.

        Args:
            texts: List of text strings to embed.

        Returns:
            List of embedding vectors (one per text).

        Raises:
            EmbeddingGenerationError: If embedding generation fails.
        """
        pass

    @property
    @abstractmethod
    def dimension(self) -> int:
        """Declared vector dimension produced by this embedding provider."""
        pass

    @property
    @abstractmethod
    def model_name(self) -> str:
        """Model identifier name (e.g. 'nomic-embed-text', 'bge-small-en-v1.5')."""
        pass

    def validate_vector(self, vector: List[float], label: str = "Embedding") -> None:
        """
        Validates that an embedding vector is a non-empty, finite list of floats
        matching the declared provider dimension.

        Args:
            vector: The embedding vector to validate.
            label: Contextual label for error messages.

        Raises:
            EmbeddingGenerationError: If vector is malformed, non-numeric, non-finite,
                                      or has an unexpected dimension.
        """
        if not isinstance(vector, (list, tuple)):
            raise EmbeddingGenerationError(
                f"{label} must be a list or tuple of floats, got {type(vector).__name__}."
            )

        if len(vector) == 0:
            raise EmbeddingGenerationError(f"{label} vector cannot be empty.")

        if len(vector) != self.dimension:
            raise EmbeddingGenerationError(
                f"{label} dimension mismatch: expected {self.dimension}, got {len(vector)}."
            )

        for idx, val in enumerate(vector):
            if not isinstance(val, (int, float)):
                raise EmbeddingGenerationError(
                    f"{label} at index {idx} is non-numeric: {type(val).__name__}."
                )
            if math.isnan(val) or math.isinf(val):
                raise EmbeddingGenerationError(
                    f"{label} at index {idx} contains non-finite value: {val}."
                )
