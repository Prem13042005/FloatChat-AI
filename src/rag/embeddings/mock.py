"""
src/rag/embeddings/mock.py

FloatChat Mock Embedding Provider.
Deterministic offline embedding provider for unit testing without external services.
Supports arbitrary dimensions, deterministic vector generation from text hash,
and simulation of edge cases (NaN/Inf, dimension mismatch, malformed vectors).
"""

import hashlib
import math
from typing import List, Optional

from src.rag.embeddings.base import BaseEmbeddingProvider
from src.rag.exceptions import EmbeddingGenerationError


class MockEmbeddingProvider(BaseEmbeddingProvider):
    """
    Mock embedding provider for unit testing.
    Generates deterministic unit-normalized vectors derived from input string hashes.
    """

    def __init__(
        self,
        dimension: int = 768,
        model_name: str = "mock-embedding-v1",
        simulate_error: Optional[str] = None,
        simulate_malformed: Optional[str] = None,
    ):
        """
        Initializes the MockEmbeddingProvider.

        Args:
            dimension: Dimension of generated vectors (defaults to 768 to match nomic-embed-text/DB schema).
            model_name: Model identifier string.
            simulate_error: If provided, raises EmbeddingGenerationError with this message.
            simulate_malformed: If 'nan', inserts float('nan'); if 'inf', inserts float('inf');
                                if 'wrong_dim', generates vector of wrong dimension;
                                if 'non_numeric', inserts string value.
        """
        self._dimension = dimension
        self._model_name = model_name
        self.simulate_error = simulate_error
        self.simulate_malformed = simulate_malformed

    @property
    def dimension(self) -> int:
        return self._dimension

    @property
    def model_name(self) -> str:
        return self._model_name

    def embed_text(self, text: str) -> List[float]:
        """
        Generates a deterministic vector of length `self.dimension`.
        """
        if self.simulate_error:
            raise EmbeddingGenerationError(self.simulate_error)

        if not text or not text.strip():
            raise EmbeddingGenerationError("Cannot generate embedding for empty text.")

        if self.simulate_malformed == "wrong_dim":
            dim = self._dimension + 10
            vector = [0.1] * dim
            self.validate_vector(vector)  # will raise dimension mismatch
            return vector

        # Compute deterministic seed from text
        text_hash = hashlib.sha256(text.encode("utf-8")).digest()
        vector = []
        for i in range(self._dimension):
            byte_val = text_hash[i % len(text_hash)]
            # Map byte (0-255) to float (-1.0 to 1.0)
            val = (byte_val / 127.5) - 1.0
            vector.append(val)

        # Apply simulation flags if requested
        if self.simulate_malformed == "nan":
            vector[0] = float("nan")
        elif self.simulate_malformed == "inf":
            vector[0] = float("inf")
        elif self.simulate_malformed == "non_numeric":
            vector[0] = "corrupt_non_numeric"  # type: ignore

        # Validate vector before returning
        self.validate_vector(vector, label=f"Mock ({self._model_name})")

        # Normalize to unit length for realistic cosine distance
        norm = math.sqrt(sum(x * x for x in vector)) or 1.0
        return [round(x / norm, 6) for x in vector]

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        return [self.embed_text(t) for t in texts]
