"""
src/rag/storage.py

FloatChat Scientific Document Vector Store.
Manages persistent storage of document chunks and embeddings in PostgreSQL (argo_doc_embeddings).
Enforces:
- Strict validation of pgvector extension availability
- Strict embedding dimension verification against column schema (vector(768))
- Parameterized database operations
- Deterministic duplicate prevention using metadata chunk hashes
- Safe transaction handling and connection cleanup
"""

import json
from typing import Any, Callable, Dict, List, Optional
import psycopg2
from psycopg2 import extensions

from src.config import Config, get_config
from src.database.connection import get_db_connection
from src.rag.exceptions import IncompatibleVectorEnvironmentError, StorageError
from src.rag.models import DocumentChunk, IngestionReport, RetrievedChunk


class DocumentVectorStore:
    """
    Database persistence service for scientific document chunks and vector embeddings.
    """

    def __init__(
        self,
        config: Optional[Config] = None,
        connection_factory: Optional[Callable[[Config], extensions.connection]] = None,
    ):
        """
        Initializes the DocumentVectorStore.

        Args:
            config: Optional Config instance.
            connection_factory: Optional callable returning a psycopg2 connection.
        """
        self.config = config or get_config()
        self.connection_factory = connection_factory or get_db_connection

    def check_database_environment(
        self,
        conn: Optional[extensions.connection] = None,
    ) -> Dict[str, Any]:
        """
        Inspects the target PostgreSQL database to determine pgvector extension status,
        table existence, embedding column existence, and declared vector dimension.

        Returns:
            Dictionary with environment capabilities.
        """
        should_close = False
        if conn is None:
            conn = self.connection_factory(self.config)
            should_close = True

        cur = conn.cursor()
        try:
            # 1. Check if pgvector extension is installed
            cur.execute("SELECT 1 FROM pg_extension WHERE extname = 'vector';")
            pgvector_installed = cur.fetchone() is not None

            # 2. Check if argo_doc_embeddings table exists
            cur.execute("""
                SELECT 1 FROM information_schema.tables 
                WHERE table_schema = 'public' AND table_name = 'argo_doc_embeddings';
            """)
            table_exists = cur.fetchone() is not None

            # 3. Check if embedding column exists
            cur.execute("""
                SELECT column_name, udt_name 
                FROM information_schema.columns 
                WHERE table_name = 'argo_doc_embeddings' AND column_name = 'embedding';
            """)
            col_info = cur.fetchone()
            column_exists = col_info is not None

            # 4. Determine vector dimension from PostgreSQL catalog if column exists
            column_dimension: Optional[int] = None
            if column_exists:
                try:
                    cur.execute("""
                        SELECT atttypmod 
                        FROM pg_attribute 
                        WHERE attrelid = 'argo_doc_embeddings'::regclass AND attname = 'embedding';
                    """)
                    row = cur.fetchone()
                    if row and row[0] > 0:
                        column_dimension = row[0]
                except Exception:
                    pass

            return {
                "pgvector_extension_available": pgvector_installed,
                "table_exists": table_exists,
                "embedding_column_exists": column_exists,
                "expected_column_dimension": column_dimension or self.config.expected_embedding_dimension,
            }
        finally:
            cur.close()
            if should_close:
                conn.close()

    def store_chunks(
        self,
        chunks: List[DocumentChunk],
        conn: Optional[extensions.connection] = None,
    ) -> IngestionReport:
        """
        Stores a batch of DocumentChunk objects into argo_doc_embeddings with parameterized SQL.
        Verifies vector compatibility and prevents duplicate chunk insertions.

        Args:
            chunks: List of DocumentChunk objects to store.
            conn: Optional existing connection. If None, acquires one via connection_factory.

        Returns:
            IngestionReport with storage statistics and error details.

        Raises:
            IncompatibleVectorEnvironmentError: If pgvector is unavailable or dimensions mismatch.
            StorageError: If database persistence fails.
        """
        report = IngestionReport(chunks_created=len(chunks))
        if not chunks:
            return report

        should_close = False
        if conn is None:
            try:
                conn = self.connection_factory(self.config)
                should_close = True
            except Exception as e:
                report.errors.append(f"Failed to connect to database: {str(e)}")
                return report

        cur = None
        try:
            # Step 1: Verify database vector capabilities
            env = self.check_database_environment(conn)
            report.db_pgvector_available = env["pgvector_extension_available"]

            has_embeddings = any(c.embedding is not None for c in chunks)

            if has_embeddings:
                if not env["pgvector_extension_available"] or not env["embedding_column_exists"]:
                    raise IncompatibleVectorEnvironmentError(
                        "Storage rejected: pgvector extension or embedding column is missing in the target database. "
                        "Cannot persist vector embeddings on this host environment."
                    )

                # Verify dimensions
                first_emb = next(c.embedding for c in chunks if c.embedding is not None)
                model_dim = len(first_emb)
                report.vector_dimension = model_dim
                expected_dim = env["expected_column_dimension"]

                if expected_dim is not None and model_dim != expected_dim:
                    raise IncompatibleVectorEnvironmentError(
                        f"Storage rejected: Vector dimension mismatch. Model produced dimension {model_dim}, "
                        f"but database column requires vector({expected_dim}). "
                        f"Truncation or padding is strictly prohibited.",
                        expected_dim=expected_dim,
                        actual_dim=model_dim,
                    )

            cur = conn.cursor()

            # Step 2: Parameterized insertion with duplicate prevention
            for chunk in chunks:
                chunk_hash = chunk.metadata.get("chunk_hash")

                # Idempotency check: check if chunk with identical document_title and chunk_hash already exists
                if chunk_hash:
                    cur.execute(
                        """
                        SELECT 1 FROM argo_doc_embeddings 
                        WHERE document_title = %s AND metadata->>'chunk_hash' = %s 
                        LIMIT 1;
                        """,
                        (chunk.document_title, str(chunk_hash)),
                    )
                    if cur.fetchone():
                        report.skipped_duplicates += 1
                        continue

                # Format vector representation for pgvector if embedding is present
                vector_val = None
                if chunk.embedding is not None:
                    vector_val = f"[{','.join(str(x) for x in chunk.embedding)}]"

                # Store metadata as serialized JSONB
                meta_json = json.dumps(chunk.metadata)

                if env["embedding_column_exists"] and vector_val is not None:
                    cur.execute(
                        """
                        INSERT INTO argo_doc_embeddings 
                            (document_title, section_title, chunk_content, metadata, embedding)
                        VALUES (%s, %s, %s, %s, %s::vector);
                        """,
                        (chunk.document_title, chunk.section_title, chunk.chunk_content, meta_json, vector_val),
                    )
                else:
                    cur.execute(
                        """
                        INSERT INTO argo_doc_embeddings 
                            (document_title, section_title, chunk_content, metadata)
                        VALUES (%s, %s, %s, %s);
                        """,
                        (chunk.document_title, chunk.section_title, chunk.chunk_content, meta_json),
                    )

                report.chunks_stored += 1

            conn.commit()
            return report

        except IncompatibleVectorEnvironmentError as e:
            try:
                conn.rollback()
            except Exception:
                pass
            report.errors.append(str(e))
            raise
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            report.errors.append(f"Database insertion failed: {str(e)}")
            raise StorageError(f"Failed to persist document chunks: {str(e)}") from e
        finally:
            if cur is not None:
                try:
                    cur.close()
                except Exception:
                    pass
            if should_close:
                try:
                    conn.close()
                except Exception:
                    pass

    def similarity_search(
        self,
        query_vector: List[float],
        top_k: int = 4,
        similarity_threshold: float = 0.70,
        conn: Optional[extensions.connection] = None,
    ) -> List[RetrievedChunk]:
        """
        Executes a read-only pgvector cosine similarity search against argo_doc_embeddings.

        Args:
            query_vector: Dense embedding vector for the query (length must match expected dimension).
            top_k: Maximum number of chunks to return (clamped between 1 and 50).
            similarity_threshold: Minimum cosine similarity score (0.0 to 1.0).
            conn: Optional existing connection. If None, acquires one via connection_factory.

        Returns:
            List of RetrievedChunk instances ranked by similarity descending.

        Raises:
            IncompatibleVectorEnvironmentError: If pgvector is unavailable or vector dimension mismatches.
            StorageError: If database query fails.
        """
        if not query_vector:
            return []

        # Validate top_k and threshold bounds
        top_k = max(1, min(int(top_k), 50))
        similarity_threshold = max(0.0, min(float(similarity_threshold), 1.0))

        should_close = False
        if conn is None:
            try:
                conn = self.connection_factory(self.config)
                should_close = True
            except Exception as e:
                raise StorageError(f"Failed to connect to database for similarity search: {str(e)}") from e

        cur = None
        try:
            # Step 1: Verify database vector capabilities
            env = self.check_database_environment(conn)
            if not env["pgvector_extension_available"] or not env["embedding_column_exists"]:
                raise IncompatibleVectorEnvironmentError(
                    "Search rejected: pgvector extension or embedding column is missing in the target database."
                )

            # Step 2: Strict dimension verification (never truncate, pad, or alter)
            model_dim = len(query_vector)
            expected_dim = env["expected_column_dimension"]
            if expected_dim is not None and model_dim != expected_dim:
                raise IncompatibleVectorEnvironmentError(
                    f"Search rejected: Query vector dimension mismatch. Query vector has dimension {model_dim}, "
                    f"but database column requires vector({expected_dim}). "
                    f"Truncation or padding is strictly prohibited.",
                    expected_dim=expected_dim,
                    actual_dim=model_dim,
                )

            # Step 3: Parameterized pgvector cosine similarity search
            vector_str = f"[{','.join(str(x) for x in query_vector)}]"
            query = """
                SELECT 
                    chunk_id,
                    document_title,
                    section_title,
                    chunk_content,
                    metadata,
                    ROUND((1 - (embedding <=> %(vector)s::vector))::numeric, 6) AS similarity_score,
                    ROUND((embedding <=> %(vector)s::vector)::numeric, 6) AS distance
                FROM argo_doc_embeddings
                WHERE embedding IS NOT NULL
                  AND (1 - (embedding <=> %(vector)s::vector)) >= %(threshold)s
                ORDER BY (embedding <=> %(vector)s::vector) ASC
                LIMIT %(limit)s;
            """
            params = {
                "vector": vector_str,
                "threshold": similarity_threshold,
                "limit": top_k,
            }

            cur = conn.cursor()
            cur.execute(query, params)
            rows = cur.fetchall()

            results: List[RetrievedChunk] = []
            for row in rows:
                chunk_id, doc_title, sec_title, content, raw_meta, sim_score, dist = row
                
                # Parse metadata safely if stored as JSON string
                if isinstance(raw_meta, str):
                    try:
                        meta = json.loads(raw_meta)
                    except Exception:
                        meta = {}
                elif isinstance(raw_meta, dict):
                    meta = raw_meta
                else:
                    meta = {}

                results.append(
                    RetrievedChunk(
                        chunk_id=chunk_id,
                        document_title=doc_title,
                        section_title=sec_title,
                        chunk_content=content,
                        similarity_score=float(sim_score),
                        distance=float(dist) if dist is not None else None,
                        metadata=meta,
                    )
                )

            return results

        except IncompatibleVectorEnvironmentError:
            raise
        except Exception as e:
            raise StorageError(f"Database error during similarity search: {str(e)}") from e
        finally:
            if cur is not None:
                try:
                    cur.close()
                except Exception:
                    pass
            if should_close:
                try:
                    conn.close()
                except Exception:
                    pass

