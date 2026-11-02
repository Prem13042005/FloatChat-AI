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
import logging
import time
from typing import Any, Callable, Dict, List, Optional
import psycopg2
from psycopg2 import extensions

from src.config import Config, get_config
from src.database.connection import get_db_connection
from src.rag.exceptions import IncompatibleVectorEnvironmentError, StorageError
from src.rag.models import DocumentChunk, IngestionReport, RetrievedChunk

logger = logging.getLogger("floatchat.rag.storage")


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
        self._environment_cache: Dict[str, Dict[str, Any]] = {}

    def _get_db_identity(self, conn: Optional[extensions.connection] = None) -> str:
        """
        Derives a unique string identity for the target database connection.
        Used to prevent stale cache reuse across different database instances or configurations.
        """
        if conn is not None and hasattr(conn, "get_dsn_parameters"):
            try:
                params = conn.get_dsn_parameters()
                if isinstance(params, dict) and params:
                    host = params.get("host", self.config.postgres_host)
                    port = params.get("port", self.config.postgres_port)
                    dbname = params.get("dbname", self.config.postgres_db)
                    user = params.get("user", self.config.postgres_user)
                    return f"{user}@{host}:{port}/{dbname}"
            except Exception:
                pass
        return f"{self.config.postgres_user}@{self.config.postgres_host}:{self.config.postgres_port}/{self.config.postgres_db}"

    def clear_environment_cache(self) -> None:
        """Clears all cached database vector environment capabilities."""
        self._environment_cache.clear()

    def check_database_environment(
        self,
        conn: Optional[extensions.connection] = None,
        force_refresh: bool = False,
    ) -> Dict[str, Any]:
        """
        Inspects the target PostgreSQL database to determine pgvector extension status,
        table existence, embedding column existence, and declared vector dimension.
        Caches successful checks by database connection identity.

        Args:
            conn: Optional active database connection.
            force_refresh: If True, bypasses cache and re-queries catalogs.

        Returns:
            Dictionary with environment capabilities.
        """
        db_key = self._get_db_identity(conn)
        if not force_refresh and db_key in self._environment_cache:
            return dict(self._environment_cache[db_key])

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

            capabilities = {
                "pgvector_extension_available": pgvector_installed,
                "table_exists": table_exists,
                "embedding_column_exists": column_exists,
                "expected_column_dimension": column_dimension or self.config.expected_embedding_dimension,
            }
            # Cache only successfully verified capability results
            self._environment_cache[db_key] = dict(capabilities)
            return capabilities
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
            # Step 1: Verify database vector capabilities (fresh verification for batch ingestion)
            env = self.check_database_environment(conn, force_refresh=True)
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
            # Enforce non-autocommit for strict read-only transaction scope
            conn.autocommit = False
            try:
                conn.set_session(readonly=True)
            except Exception:
                pass

            cur = conn.cursor()

            # Apply read-only statement timeout of 5000ms inside the active transaction
            cur.execute("SET LOCAL statement_timeout = 5000;")

            # Step 1: Verify database vector capabilities (uses cached capability checks)
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
                    ROUND((1 - (embedding <=> %(vector)s::vector))::numeric, 6) AS similarity_score
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

            t0 = time.perf_counter()
            cur.execute(query, params)
            rows = cur.fetchall()
            search_duration_ms = round((time.perf_counter() - t0) * 1000.0, 2)

            results: List[RetrievedChunk] = []
            for row in rows:
                if len(row) >= 7:
                    chunk_id, doc_title, sec_title, content, raw_meta, sim_score, raw_dist = row[:7]
                    sim_val = float(sim_score)
                    dist_val = float(raw_dist) if raw_dist is not None else round(1.0 - sim_val, 6)
                else:
                    chunk_id, doc_title, sec_title, content, raw_meta, sim_score = row[:6]
                    sim_val = float(sim_score)
                    dist_val = round(1.0 - sim_val, 6)
                
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
                        similarity_score=sim_val,
                        distance=dist_val,
                        metadata=meta,
                    )
                )

            # Commit the read-only transaction cleanly
            conn.commit()

            logger.info(
                "Vector similarity search completed in %.2fms [top_k=%d, threshold=%.2f, found=%d]",
                search_duration_ms,
                top_k,
                similarity_threshold,
                len(results),
            )
            return results

        except IncompatibleVectorEnvironmentError:
            try:
                conn.rollback()
            except Exception:
                pass
            raise
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
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

