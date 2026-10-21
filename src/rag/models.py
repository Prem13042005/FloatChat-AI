"""
src/rag/models.py

FloatChat Scientific RAG Ingestion Data Models.
Defines strongly-typed Pydantic schemas representing raw loaded scientific documents,
bounded text chunks, and ingestion pipeline execution reports.
"""

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class Document(BaseModel):
    """
    Represents an authoritative scientific document loaded from disk.
    """
    content: str = Field(description="Raw text content of the document.")
    source_path: str = Field(description="Absolute or relative file path to the source document.")
    document_title: str = Field(description="Extracted or normalized document title.")
    file_type: str = Field(description="File format identifier ('markdown', 'pdf', 'text').")
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Source document metadata (e.g. page_count, file_size_bytes, modified_time)."
    )


class DocumentChunk(BaseModel):
    """
    Represents a bounded, semantically coherent text passage ready for embedding and retrieval.
    """
    chunk_id: str = Field(description="Deterministic, unique chunk identifier.")
    document_title: str = Field(description="Title of the parent document for citation provenance.")
    section_title: Optional[str] = Field(
        default=None,
        description="Section header or chapter title containing this chunk."
    )
    chunk_index: int = Field(description="0-indexed sequence position within the document.")
    page_number: Optional[int] = Field(
        default=None,
        description="1-indexed source document page number (when available from PDF)."
    )
    chunk_content: str = Field(description="Extracted and cleaned passage text.")
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Enriched chunk metadata (e.g. source_path, chunk_hash, char_count, topic_tags)."
    )
    embedding: Optional[List[float]] = Field(
        default=None,
        description="Generated numeric dense vector representation."
    )


class IngestionReport(BaseModel):
    """
    Summary report of document ingestion and vector storage pipeline execution.
    """
    documents_loaded: int = Field(default=0, description="Number of source documents successfully parsed.")
    chunks_created: int = Field(default=0, description="Total number of text chunks produced.")
    embeddings_generated: int = Field(default=0, description="Number of chunk embedding vectors computed.")
    chunks_stored: int = Field(default=0, description="Number of chunks successfully persisted in database.")
    skipped_duplicates: int = Field(default=0, description="Number of duplicate chunks skipped idempotently.")
    db_pgvector_available: bool = Field(default=False, description="True if database environment has pgvector active.")
    vector_dimension: Optional[int] = Field(default=None, description="Dimension of generated embeddings.")
    errors: List[str] = Field(default_factory=list, description="List of encountered errors during ingestion.")
    warnings: List[str] = Field(default_factory=list, description="List of warnings or configuration notices.")

    @property
    def is_success(self) -> bool:
        """Returns True if at least one chunk was created with zero fatal errors."""
        return len(self.errors) == 0 and self.chunks_created > 0


class RetrievedChunk(BaseModel):
    """
    Represents an individual document chunk retrieved via semantic similarity search.
    """
    chunk_id: Optional[int] = Field(default=None, description="Database chunk primary key ID.")
    document_title: str = Field(description="Parent document title for citation provenance.")
    section_title: Optional[str] = Field(default=None, description="Section or chapter header.")
    chunk_content: str = Field(description="Extracted passage text.")
    similarity_score: float = Field(description="Computed cosine similarity (0.0 to 1.0, higher is better).")
    distance: Optional[float] = Field(default=None, description="Raw pgvector cosine distance (0.0 to 2.0).")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Chunk metadata dictionary.")


class RetrievalResult(BaseModel):
    """
    Encapsulates the complete result of a semantic document retrieval operation.
    """
    query: str = Field(description="Original user search query.")
    chunks: List[RetrievedChunk] = Field(default_factory=list, description="Ranked list of relevant chunks.")
    top_k: int = Field(default=4, description="Maximum number of chunks requested.")
    similarity_threshold: float = Field(default=0.70, description="Minimum cosine similarity threshold.")
    total_found: int = Field(default=0, description="Total chunks found meeting threshold criteria.")
    status: str = Field(default="success", description="Status code ('success', 'empty', 'unavailable', 'error').")
    warning: Optional[str] = Field(default=None, description="Warning or degradation notice, if any.")

    @property
    def has_results(self) -> bool:
        """Returns True if at least one relevant chunk was retrieved."""
        return len(self.chunks) > 0
