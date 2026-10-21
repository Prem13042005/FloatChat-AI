"""
src/rag/embeddings/__init__.py

FloatChat Embedding System Package.
Exports BaseEmbeddingProvider, OllamaEmbeddingProvider, and MockEmbeddingProvider.
"""

from src.rag.embeddings.base import BaseEmbeddingProvider
from src.rag.embeddings.mock import MockEmbeddingProvider
from src.rag.embeddings.ollama import OllamaEmbeddingProvider

__all__ = [
    "BaseEmbeddingProvider",
    "OllamaEmbeddingProvider",
    "MockEmbeddingProvider",
]
