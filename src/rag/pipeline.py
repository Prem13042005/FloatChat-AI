"""
src/rag/pipeline.py

FloatChat Scientific Document Ingestion Pipeline.
Coordinates loading, text normalization, passage chunking, embedding generation,
and database persistence.
"""

from pathlib import Path
from typing import List, Optional, Union

from src.config import Config, get_config
from src.rag.chunker import DocumentChunker
from src.rag.embeddings.base import BaseEmbeddingProvider
from src.rag.embeddings.ollama import OllamaEmbeddingProvider
from src.rag.loader import DocumentLoader
from src.rag.models import Document, DocumentChunk, IngestionReport
from src.rag.storage import DocumentVectorStore


class DocumentIngestionPipeline:
    """
    End-to-end ingestion coordinator for scientific ARGO documentation.
    """

    def __init__(
        self,
        loader: Optional[DocumentLoader] = None,
        chunker: Optional[DocumentChunker] = None,
        embedding_provider: Optional[BaseEmbeddingProvider] = None,
        storage: Optional[DocumentVectorStore] = None,
        config: Optional[Config] = None,
    ):
        """
        Initializes the DocumentIngestionPipeline.

        Args:
            loader: Optional DocumentLoader instance.
            chunker: Optional DocumentChunker instance.
            embedding_provider: Optional BaseEmbeddingProvider instance (defaults to Ollama nomic-embed-text).
            storage: Optional DocumentVectorStore instance.
            config: Optional Config instance.
        """
        self.config = config or get_config()
        self.loader = loader or DocumentLoader()
        self.chunker = chunker or DocumentChunker()
        self.storage = storage or DocumentVectorStore(config=self.config)

        if embedding_provider is not None:
            self.embedding_provider = embedding_provider
        else:
            self.embedding_provider = OllamaEmbeddingProvider(
                base_url=self.config.ollama_base_url,
                model=self.config.embedding_model or "nomic-embed-text",
                dimension=self.config.expected_embedding_dimension or 768,
                timeout_seconds=self.config.ollama_timeout_seconds or 30.0,
            )

    def process_document(
        self,
        document: Document,
        generate_embeddings: bool = True,
        store_in_db: bool = False,
    ) -> tuple[List[DocumentChunk], IngestionReport]:
        """
        Chunks a loaded Document, optionally computes embeddings, and optionally persists to DB.

        Args:
            document: Document object.
            generate_embeddings: If True and provider available, computes vector embeddings.
            store_in_db: If True, writes chunks into database via DocumentVectorStore.

        Returns:
            Tuple of (List[DocumentChunk], IngestionReport).
        """
        report = IngestionReport(documents_loaded=1)

        # 1. Split into chunks
        chunks = self.chunker.chunk_document(document)
        report.chunks_created = len(chunks)

        if not chunks:
            return chunks, report

        # 2. Generate embeddings if requested
        if generate_embeddings and self.embedding_provider is not None:
            report.vector_dimension = self.embedding_provider.dimension
            texts = [c.chunk_content for c in chunks]
            try:
                embeddings = self.embedding_provider.embed_documents(texts)
                for chunk, emb in zip(chunks, embeddings):
                    chunk.embedding = emb
                report.embeddings_generated = len(embeddings)
            except Exception as e:
                report.errors.append(f"Embedding generation failed: {str(e)}")
                return chunks, report

        # 3. Store in database if requested
        if store_in_db and self.storage is not None:
            try:
                storage_report = self.storage.store_chunks(chunks)
                report.chunks_stored = storage_report.chunks_stored
                report.skipped_duplicates = storage_report.skipped_duplicates
                report.db_pgvector_available = storage_report.db_pgvector_available
                report.errors.extend(storage_report.errors)
                report.warnings.extend(storage_report.warnings)
            except Exception as e:
                report.errors.append(f"Storage failed: {str(e)}")

        return chunks, report

    def process_file(
        self,
        file_path: Union[str, Path],
        generate_embeddings: bool = True,
        store_in_db: bool = False,
    ) -> tuple[List[DocumentChunk], IngestionReport]:
        """
        Loads, chunks, and processes a single document file from disk.
        """
        try:
            doc = self.loader.load_file(file_path)
            return self.process_document(
                doc,
                generate_embeddings=generate_embeddings,
                store_in_db=store_in_db,
            )
        except Exception as e:
            report = IngestionReport(documents_loaded=0)
            report.errors.append(f"Failed to process file {file_path}: {str(e)}")
            return [], report

    def process_directory(
        self,
        dir_path: Union[str, Path],
        generate_embeddings: bool = True,
        store_in_db: bool = False,
        recursive: bool = False,
    ) -> tuple[List[DocumentChunk], IngestionReport]:
        """
        Batch processes all supported documents in a directory.
        """
        try:
            docs = self.loader.load_directory(dir_path, recursive=recursive)
        except Exception as e:
            report = IngestionReport(documents_loaded=0)
            report.errors.append(f"Directory loading failed for {dir_path}: {str(e)}")
            return [], report

        all_chunks: List[DocumentChunk] = []
        combined_report = IngestionReport(documents_loaded=len(docs))

        for doc in docs:
            chunks, rep = self.process_document(
                doc,
                generate_embeddings=generate_embeddings,
                store_in_db=store_in_db,
            )
            all_chunks.extend(chunks)
            combined_report.chunks_created += rep.chunks_created
            combined_report.embeddings_generated += rep.embeddings_generated
            combined_report.chunks_stored += rep.chunks_stored
            combined_report.skipped_duplicates += rep.skipped_duplicates
            combined_report.errors.extend(rep.errors)
            combined_report.warnings.extend(rep.warnings)
            if rep.db_pgvector_available:
                combined_report.db_pgvector_available = True
            if rep.vector_dimension:
                combined_report.vector_dimension = rep.vector_dimension

        return all_chunks, combined_report

    def ingest_file(
        self,
        file_path: Union[str, Path],
    ) -> tuple[List[DocumentChunk], IngestionReport]:
        """
        End-to-end convenience method: loads, chunks, generates embeddings, and persists to DB.
        """
        return self.process_file(file_path, generate_embeddings=True, store_in_db=True)

    def ingest_directory(
        self,
        dir_path: Union[str, Path],
        recursive: bool = False,
    ) -> tuple[List[DocumentChunk], IngestionReport]:
        """
        End-to-end convenience method: batch ingests all documents in a directory into DB.
        """
        return self.process_directory(dir_path, generate_embeddings=True, store_in_db=True, recursive=recursive)

