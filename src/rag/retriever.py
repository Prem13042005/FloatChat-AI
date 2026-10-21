"""
src/rag/retriever.py

FloatChat Scientific Document Semantic Retriever.
Provides pgvector-backed semantic retrieval of scientific documentation
(ARGO manuals, user guides, data quality reference sheets) matching user queries.
Enforces:
- Local Ollama nomic-embed-text query embedding generation (768 dimensions)
- Strict vector dimension validation (no truncation or padding)
- Cosine distance similarity search via pgvector
- Configurable top-k limiting and similarity threshold filtering
- Parameterized read-only SQL queries
- Graceful degradation on empty knowledge base, network, or environment failures
"""

import logging
from typing import List, Optional

from src.config import Config, get_config
from src.rag.embeddings.base import BaseEmbeddingProvider
from src.rag.embeddings.ollama import OllamaEmbeddingProvider
from src.rag.exceptions import (
    EmbeddingGenerationError,
    IncompatibleVectorEnvironmentError,
    RetrievalError,
    StorageError,
)
from src.rag.models import RetrievalResult, RetrievedChunk
from src.rag.storage import DocumentVectorStore

logger = logging.getLogger("floatchat.rag.retriever")


class ScientificDocumentRetriever:
    """
    Semantic retrieval service for FloatChat's scientific document knowledge base.
    """

    def __init__(
        self,
        config: Optional[Config] = None,
        embedding_provider: Optional[BaseEmbeddingProvider] = None,
        vector_store: Optional[DocumentVectorStore] = None,
    ):
        """
        Initializes the ScientificDocumentRetriever.

        Args:
            config: Optional Config instance.
            embedding_provider: Optional BaseEmbeddingProvider instance (defaults to Ollama nomic-embed-text).
            vector_store: Optional DocumentVectorStore instance.
        """
        self.config = config or get_config()
        self.vector_store = vector_store or DocumentVectorStore(config=self.config)

        if embedding_provider is not None:
            self.embedding_provider = embedding_provider
        else:
            # Default to configured Ollama provider with nomic-embed-text
            self.embedding_provider = OllamaEmbeddingProvider(
                base_url=self.config.ollama_base_url,
                model=self.config.embedding_model or "nomic-embed-text",
                dimension=self.config.expected_embedding_dimension or 768,
                timeout_seconds=self.config.ollama_timeout_seconds or 30.0,
            )

    def retrieve(
        self,
        query: str,
        top_k: Optional[int] = None,
        similarity_threshold: Optional[float] = None,
        raise_on_error: bool = False,
    ) -> RetrievalResult:
        """
        Executes semantic retrieval for a natural language query.

        Args:
            query: Natural language user question or scientific search terms.
            top_k: Maximum number of chunks to return (defaults to config.vector_top_k).
            similarity_threshold: Minimum cosine similarity score (defaults to config.vector_similarity_threshold).
            raise_on_error: If True, raises exceptions on provider/database errors instead of returning degraded status.

        Returns:
            RetrievalResult containing ranked list of RetrievedChunk objects.

        Raises:
            RetrievalError: If raise_on_error is True and retrieval fails.
            IncompatibleVectorEnvironmentError: If raise_on_error is True and vector dimension/pgvector mismatches.
        """
        actual_top_k = top_k if top_k is not None else self.config.vector_top_k
        actual_threshold = (
            similarity_threshold
            if similarity_threshold is not None
            else self.config.vector_similarity_threshold
        )

        # 1. Validate query string
        if not query or not query.strip():
            logger.debug("Retrieval received empty query string.")
            return RetrievalResult(
                query=query or "",
                chunks=[],
                top_k=actual_top_k,
                similarity_threshold=actual_threshold,
                total_found=0,
                status="empty",
                warning="Query string is empty.",
            )

        # 2. Generate dense query embedding vector
        try:
            query_vector = self.embedding_provider.embed_text(query.strip())
        except EmbeddingGenerationError as e:
            logger.warning("Embedding generation failed for query: %s", str(e))
            if raise_on_error:
                raise RetrievalError(f"Embedding generation failed: {str(e)}") from e
            return RetrievalResult(
                query=query,
                chunks=[],
                top_k=actual_top_k,
                similarity_threshold=actual_threshold,
                total_found=0,
                status="unavailable",
                warning=f"Embedding provider unavailable: {str(e)}",
            )
        except Exception as e:
            logger.error("Unexpected error during embedding generation: %s", str(e), exc_info=True)
            if raise_on_error:
                raise RetrievalError(f"Unexpected error during query embedding: {str(e)}") from e
            return RetrievalResult(
                query=query,
                chunks=[],
                top_k=actual_top_k,
                similarity_threshold=actual_threshold,
                total_found=0,
                status="error",
                warning=f"Query embedding generation failed: {str(e)}",
            )

        # 3. Strict dimension validation against configuration
        expected_dim = self.config.expected_embedding_dimension
        if len(query_vector) != expected_dim:
            err_msg = (
                f"Query vector dimension mismatch: Provider produced {len(query_vector)} dimensions, "
                f"but configuration requires {expected_dim}. Truncation or padding is strictly prohibited."
            )
            logger.error(err_msg)
            if raise_on_error:
                raise IncompatibleVectorEnvironmentError(
                    err_msg,
                    expected_dim=expected_dim,
                    actual_dim=len(query_vector),
                )
            return RetrievalResult(
                query=query,
                chunks=[],
                top_k=actual_top_k,
                similarity_threshold=actual_threshold,
                total_found=0,
                status="error",
                warning=err_msg,
            )

        # 4. Execute vector similarity search
        return self.retrieve_by_vector(
            query_vector=query_vector,
            query_text=query,
            top_k=actual_top_k,
            similarity_threshold=actual_threshold,
            raise_on_error=raise_on_error,
        )

    def retrieve_by_vector(
        self,
        query_vector: List[float],
        query_text: str = "",
        top_k: Optional[int] = None,
        similarity_threshold: Optional[float] = None,
        raise_on_error: bool = False,
    ) -> RetrievalResult:
        """
        Executes semantic similarity search using a pre-computed embedding vector.

        Args:
            query_vector: Dense embedding vector.
            query_text: Original query text for tracking.
            top_k: Maximum number of chunks to return.
            similarity_threshold: Minimum cosine similarity score.
            raise_on_error: If True, raises exceptions on errors.

        Returns:
            RetrievalResult containing ranked list of RetrievedChunk objects.
        """
        actual_top_k = top_k if top_k is not None else self.config.vector_top_k
        actual_threshold = (
            similarity_threshold
            if similarity_threshold is not None
            else self.config.vector_similarity_threshold
        )

        try:
            chunks = self.vector_store.similarity_search(
                query_vector=query_vector,
                top_k=actual_top_k,
                similarity_threshold=actual_threshold,
            )
            return RetrievalResult(
                query=query_text,
                chunks=chunks,
                top_k=actual_top_k,
                similarity_threshold=actual_threshold,
                total_found=len(chunks),
                status="success",
            )

        except IncompatibleVectorEnvironmentError as e:
            logger.warning("Vector database environment incompatible: %s", str(e))
            if raise_on_error:
                raise
            return RetrievalResult(
                query=query_text,
                chunks=[],
                top_k=actual_top_k,
                similarity_threshold=actual_threshold,
                total_found=0,
                status="unavailable",
                warning=str(e),
            )
        except StorageError as e:
            logger.error("Database storage error during retrieval: %s", str(e), exc_info=True)
            if raise_on_error:
                raise RetrievalError(f"Database retrieval failed: {str(e)}") from e
            return RetrievalResult(
                query=query_text,
                chunks=[],
                top_k=actual_top_k,
                similarity_threshold=actual_threshold,
                total_found=0,
                status="error",
                warning=f"Database search failed: {str(e)}",
            )
        except Exception as e:
            logger.error("Unexpected error during retrieval: %s", str(e), exc_info=True)
            if raise_on_error:
                raise RetrievalError(f"Unexpected retrieval failure: {str(e)}") from e
            return RetrievalResult(
                query=query_text,
                chunks=[],
                top_k=actual_top_k,
                similarity_threshold=actual_threshold,
                total_found=0,
                status="error",
                warning=f"Unexpected retrieval error: {str(e)}",
            )
