"""
src/rag/exceptions.py

FloatChat Scientific RAG & Ingestion Exceptions.
Defines domain-specific exception types for document loading, chunking,
embedding generation, and vector database storage.
"""

from typing import Optional


class RAGError(Exception):
    """Base exception for all RAG and document ingestion errors."""
    pass


class DocumentLoadingError(RAGError):
    """Raised when loading or parsing a scientific document fails."""
    pass


class ChunkingError(RAGError):
    """Raised when splitting document text into bounded chunks fails."""
    pass


class EmbeddingGenerationError(RAGError):
    """Raised when generating dense vector embeddings fails or returns malformed vectors."""
    pass


class StorageError(RAGError):
    """Raised when storing chunks or embeddings in the database fails."""
    pass


class IncompatibleVectorEnvironmentError(StorageError):
    """Raised when the database lacks pgvector or has an incompatible vector dimension."""
    def __init__(self, message: str, expected_dim: Optional[int] = None, actual_dim: Optional[int] = None):
        super().__init__(message)
        self.expected_dim = expected_dim
        self.actual_dim = actual_dim


class RetrievalError(RAGError):
    """Raised when semantic document retrieval fails."""
    pass
