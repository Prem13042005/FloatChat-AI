"""
src/rag/__init__.py

FloatChat Scientific RAG & Ingestion Package.
Exports document loading, chunking, embedding generation, storage,
and ingestion pipeline components for the Scientific Knowledge & Response Agent foundation.
"""

from src.rag.chunker import DocumentChunker
from src.rag.embeddings import (
    BaseEmbeddingProvider,
    MockEmbeddingProvider,
    OllamaEmbeddingProvider,
)
from src.rag.exceptions import (
    ChunkingError,
    DocumentLoadingError,
    EmbeddingGenerationError,
    IncompatibleVectorEnvironmentError,
    RAGError,
    RetrievalError,
    StorageError,
)
from src.rag.loader import DocumentLoader
from src.rag.models import Document, DocumentChunk, IngestionReport, RetrievalResult, RetrievedChunk
from src.rag.pipeline import DocumentIngestionPipeline
from src.rag.retriever import ScientificDocumentRetriever
from src.rag.storage import DocumentVectorStore

__all__ = [
    "Document",
    "DocumentChunk",
    "IngestionReport",
    "RetrievedChunk",
    "RetrievalResult",
    "DocumentLoader",
    "DocumentChunker",
    "BaseEmbeddingProvider",
    "OllamaEmbeddingProvider",
    "MockEmbeddingProvider",
    "DocumentVectorStore",
    "DocumentIngestionPipeline",
    "ScientificDocumentRetriever",
    "RAGError",
    "DocumentLoadingError",
    "ChunkingError",
    "EmbeddingGenerationError",
    "StorageError",
    "IncompatibleVectorEnvironmentError",
    "RetrievalError",
]

