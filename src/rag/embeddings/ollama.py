"""
src/rag/embeddings/ollama.py

FloatChat Ollama Embedding Provider.
Generates local dense vector embeddings using Ollama's local embedding endpoint.
Defaults to nomic-embed-text (dimension: 768).
"""

import json
from typing import List, Optional
import urllib.request
import urllib.error

from src.rag.embeddings.base import BaseEmbeddingProvider
from src.rag.exceptions import EmbeddingGenerationError

DEFAULT_OLLAMA_EMBEDDING_MODEL = "nomic-embed-text"
DEFAULT_OLLAMA_DIMENSION = 768


class OllamaEmbeddingProvider(BaseEmbeddingProvider):
    """
    Local embedding provider connecting to Ollama's /api/embeddings endpoint.
    """

    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        model: str = DEFAULT_OLLAMA_EMBEDDING_MODEL,
        dimension: int = DEFAULT_OLLAMA_DIMENSION,
        timeout_seconds: float = 30.0,
    ):
        """
        Initializes the OllamaEmbeddingProvider.

        Args:
            base_url: Ollama daemon URL.
            model: Embedding model name (e.g. 'nomic-embed-text').
            dimension: Expected embedding dimension (768 for nomic-embed-text).
            timeout_seconds: Network request timeout in seconds.
        """
        self.base_url = base_url.rstrip("/")
        self._model = model
        self._dimension = dimension
        self.timeout_seconds = timeout_seconds

    @property
    def dimension(self) -> int:
        return self._dimension

    @property
    def model_name(self) -> str:
        return self._model

    def embed_text(self, text: str) -> List[float]:
        """
        Generates an embedding vector for a single string using Ollama.
        """
        if not text or not text.strip():
            raise EmbeddingGenerationError("Cannot generate embedding for empty text.")

        endpoint = f"{self.base_url}/api/embeddings"
        payload = {
            "model": self._model,
            "prompt": text.strip(),
        }

        try:
            req = urllib.request.Request(
                endpoint,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=self.timeout_seconds) as response:
                status_code = response.getcode()
                if status_code != 200:
                    raise EmbeddingGenerationError(
                        f"Ollama embedding request failed with HTTP {status_code}."
                    )
                resp_data = json.loads(response.read().decode("utf-8"))

            raw_embedding = resp_data.get("embedding")
            if raw_embedding is None:
                raise EmbeddingGenerationError(
                    f"Ollama response missing 'embedding' field: {resp_data}"
                )

            # Validate vector structure and dimension
            self.validate_vector(raw_embedding, label=f"Ollama ({self._model})")
            return [float(x) for x in raw_embedding]

        except urllib.error.URLError as e:
            raise EmbeddingGenerationError(
                f"Failed to connect to Ollama embedding service at {self.base_url}: {e.reason}"
            ) from e
        except EmbeddingGenerationError:
            raise
        except Exception as e:
            raise EmbeddingGenerationError(
                f"Unexpected error during Ollama embedding generation: {str(e)}"
            ) from e

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        """
        Generates embeddings for a batch of text passages.
        """
        if not texts:
            return []

        embeddings: List[List[float]] = []
        for idx, text in enumerate(texts):
            try:
                emb = self.embed_text(text)
                embeddings.append(emb)
            except Exception as e:
                raise EmbeddingGenerationError(
                    f"Failed to generate embedding for document batch item {idx}: {str(e)}"
                ) from e

        return embeddings
