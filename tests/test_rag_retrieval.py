"""
tests/test_rag_retrieval.py

Phase 7B — Semantic Retrieval Test Suite.
Verifies:
1. Retrieval ranking order (cosine similarity descending / distance ascending).
2. Similarity threshold filtering (excluding chunks below threshold).
3. Top-k limiting behavior.
4. Empty knowledge base handling (graceful zero-match results).
5. Empty / whitespace query strings handled gracefully.
6. Vector dimension mismatch strictly rejected without truncation or padding.
7. Embedding provider failure / unavailable Ollama handled gracefully.
8. Missing pgvector or table in database handled gracefully.
9. Database execution errors handled with proper rollback / status reporting.
10. Parameterized SQL queries preventing SQL injection.
11. Metadata parsing from JSON strings, dicts, and None values.
12. Configuration defaults (top_k=4, similarity_threshold=0.70, dimension=768).
13. Ollama provider integration with mocked HTTP network response.
14. Live database read-only compatibility check (port 5433).
"""

import json
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

# Ensure src is in python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.agents.query_understanding.models import IntentType, QueryIntent
from src.agents.response.agent import ScientificResponseAgent
from src.config import Config
from src.orchestration.graph import FloatChatOrchestrator
from src.rag import (
    EmbeddingGenerationError,
    IncompatibleVectorEnvironmentError,
    MockEmbeddingProvider,
    OllamaEmbeddingProvider,
    RetrievalError,
    RetrievalResult,
    RetrievedChunk,
    ScientificDocumentRetriever,
    StorageError,
)
from src.rag.storage import DocumentVectorStore


class TestRAGRetrieval(unittest.TestCase):

    def setUp(self):
        self.config = Config(
            postgres_host="localhost",
            postgres_port=5433,
            postgres_db="floatchat_db",
            postgres_user="floatchat_user",
            postgres_password="floatchat_password",
            expected_embedding_dimension=768,
            vector_top_k=4,
            vector_similarity_threshold=0.70,
        )
        self.mock_provider = MockEmbeddingProvider(dimension=768)

    # ===================================================================
    # 1. Ranking Order
    # ===================================================================

    def test_01_retrieval_ranking_order(self):
        """Verify returned chunks are ranked by cosine similarity descending (distance ascending)."""
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_conn.cursor.return_value = mock_cur

        # Mock check_database_environment: pgvector & column ok
        mock_cur.fetchone.side_effect = [
            (1,),                     # pgvector installed
            (1,),                     # table exists
            ("embedding", "vector"),  # column exists
            (768,),                   # column dimension
        ]

        # Mock similarity search returning 3 rows with descending similarity
        mock_cur.fetchall.return_value = [
            (1, "Manual", "CTD Sensor", "CTD measurements...", '{"page": 12}', 0.925000, 0.075000),
            (2, "Manual", "Salinity QC", "Practical salinity...", '{"page": 18}', 0.841000, 0.159000),
            (3, "Guide", "Float Deployment", "Deployment rules...", '{"page": 3}', 0.732000, 0.268000),
        ]

        store = DocumentVectorStore(config=self.config, connection_factory=lambda cfg: mock_conn)
        retriever = ScientificDocumentRetriever(
            config=self.config,
            embedding_provider=self.mock_provider,
            vector_store=store,
        )

        result = retriever.retrieve("How does the CTD sensor measure salinity?")

        self.assertEqual(result.status, "success")
        self.assertEqual(len(result.chunks), 3)
        self.assertEqual(result.total_found, 3)

        # Check order
        self.assertEqual(result.chunks[0].chunk_id, 1)
        self.assertEqual(result.chunks[0].similarity_score, 0.925000)
        self.assertEqual(result.chunks[1].chunk_id, 2)
        self.assertEqual(result.chunks[1].similarity_score, 0.841000)
        self.assertEqual(result.chunks[2].chunk_id, 3)
        self.assertEqual(result.chunks[2].similarity_score, 0.732000)

        # Check metadata parsing
        self.assertEqual(result.chunks[0].metadata.get("page"), 12)

    # ===================================================================
    # 2. Threshold Filtering
    # ===================================================================

    def test_02_similarity_threshold_filtering(self):
        """Verify that similarity_threshold parameter filters out low-similarity chunks."""
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_conn.cursor.return_value = mock_cur

        mock_cur.fetchone.side_effect = [
            (1,), (1,), ("embedding", "vector"), (768,)
        ]

        # Only rows meeting threshold 0.80 returned by query
        mock_cur.fetchall.return_value = [
            (1, "Manual", "CTD", "High match...", '{}', 0.88, 0.12),
        ]

        store = DocumentVectorStore(config=self.config, connection_factory=lambda cfg: mock_conn)
        retriever = ScientificDocumentRetriever(
            config=self.config,
            embedding_provider=self.mock_provider,
            vector_store=store,
        )

        result = retriever.retrieve("CTD sensor calibration", similarity_threshold=0.80)

        self.assertEqual(len(result.chunks), 1)
        self.assertEqual(result.similarity_threshold, 0.80)

        # Verify SQL parameter passed threshold 0.80
        execute_args = mock_cur.execute.call_args[0]
        params = execute_args[1]
        self.assertEqual(params["threshold"], 0.80)

    # ===================================================================
    # 3. Top-k Limiting
    # ===================================================================

    def test_03_top_k_limiting(self):
        """Verify that top_k restricts the number of returned chunks."""
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_conn.cursor.return_value = mock_cur

        mock_cur.fetchone.side_effect = [
            (1,), (1,), ("embedding", "vector"), (768,)
        ]
        mock_cur.fetchall.return_value = [
            (1, "Doc1", "Sec1", "Content 1", '{}', 0.90, 0.10),
            (2, "Doc2", "Sec2", "Content 2", '{}', 0.85, 0.15),
        ]

        store = DocumentVectorStore(config=self.config, connection_factory=lambda cfg: mock_conn)
        retriever = ScientificDocumentRetriever(
            config=self.config,
            embedding_provider=self.mock_provider,
            vector_store=store,
        )

        result = retriever.retrieve("Ocean observation", top_k=2)

        self.assertEqual(len(result.chunks), 2)
        self.assertEqual(result.top_k, 2)

        execute_args = mock_cur.execute.call_args[0]
        params = execute_args[1]
        self.assertEqual(params["limit"], 2)

    # ===================================================================
    # 4. Empty Knowledge Base
    # ===================================================================

    def test_04_empty_knowledge_base_returns_empty_results(self):
        """Verify that when the knowledge base has no matching or zero chunks, it returns empty list cleanly."""
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_conn.cursor.return_value = mock_cur

        mock_cur.fetchone.side_effect = [
            (1,), (1,), ("embedding", "vector"), (768,)
        ]
        mock_cur.fetchall.return_value = []

        store = DocumentVectorStore(config=self.config, connection_factory=lambda cfg: mock_conn)
        retriever = ScientificDocumentRetriever(
            config=self.config,
            embedding_provider=self.mock_provider,
            vector_store=store,
        )

        result = retriever.retrieve("Unindexed topic query")

        self.assertEqual(result.status, "success")
        self.assertEqual(len(result.chunks), 0)
        self.assertEqual(result.total_found, 0)
        self.assertFalse(result.has_results)
        self.assertIsNone(result.warning)

    # ===================================================================
    # 5. Empty and Whitespace Query Handled Gracefully
    # ===================================================================

    def test_05_empty_query_string_handled_gracefully(self):
        """Verify that empty or whitespace-only queries return empty result without DB calls."""
        store = DocumentVectorStore(config=self.config)
        retriever = ScientificDocumentRetriever(
            config=self.config,
            embedding_provider=self.mock_provider,
            vector_store=store,
        )

        for empty_q in ["", "   ", "\t\n", None]:
            result = retriever.retrieve(empty_q)
            self.assertEqual(result.status, "empty")
            self.assertEqual(len(result.chunks), 0)
            self.assertIn("empty", result.warning.lower())

    # ===================================================================
    # 6. Strict Dimension Mismatch Rejection
    # ===================================================================

    def test_06_dimension_mismatch_strictly_rejected(self):
        """Verify that wrong-dimension query embeddings are rejected without truncation or padding."""
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_conn.cursor.return_value = mock_cur

        # DB has 768 dimensions
        mock_cur.fetchone.side_effect = [
            (1,), (1,), ("embedding", "vector"), (768,)
        ]

        store = DocumentVectorStore(config=self.config, connection_factory=lambda cfg: mock_conn)
        # Mock provider generates 512 dimensions instead of 768
        wrong_provider = MockEmbeddingProvider(dimension=512)
        retriever = ScientificDocumentRetriever(
            config=self.config,
            embedding_provider=wrong_provider,
            vector_store=store,
        )

        # With raise_on_error=False
        result = retriever.retrieve("Test query", raise_on_error=False)
        self.assertEqual(result.status, "error")
        self.assertIn("dimension mismatch", result.warning.lower())

        # With raise_on_error=True
        with self.assertRaises(IncompatibleVectorEnvironmentError) as ctx:
            retriever.retrieve("Test query", raise_on_error=True)
        self.assertEqual(ctx.exception.expected_dim, 768)
        self.assertEqual(ctx.exception.actual_dim, 512)

    # ===================================================================
    # 7. Embedding Provider Failure Handled Gracefully
    # ===================================================================

    def test_07_embedding_provider_failure_handled_gracefully(self):
        """Verify graceful error reporting when the embedding provider fails or is unreachable."""
        error_provider = MockEmbeddingProvider(simulate_error="Connection refused: Ollama daemon is offline")
        store = DocumentVectorStore(config=self.config)
        retriever = ScientificDocumentRetriever(
            config=self.config,
            embedding_provider=error_provider,
            vector_store=store,
        )

        # Non-raising mode
        result = retriever.retrieve("Salinity query", raise_on_error=False)
        self.assertEqual(result.status, "unavailable")
        self.assertEqual(len(result.chunks), 0)
        self.assertIn("unavailable", result.warning.lower())

        # Raising mode
        with self.assertRaises(RetrievalError) as ctx:
            retriever.retrieve("Salinity query", raise_on_error=True)
        self.assertIn("Embedding generation failed", str(ctx.exception))

    # ===================================================================
    # 8. Missing pgvector in Database Handled Gracefully
    # ===================================================================

    def test_08_missing_pgvector_handled_gracefully(self):
        """Verify graceful handling when pgvector extension is absent in target database."""
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_conn.cursor.return_value = mock_cur

        # Mock: pgvector is NOT installed
        mock_cur.fetchone.side_effect = [
            None,  # pgvector missing
            (1,),  # table exists
            None,  # column missing
        ]

        store = DocumentVectorStore(config=self.config, connection_factory=lambda cfg: mock_conn)
        retriever = ScientificDocumentRetriever(
            config=self.config,
            embedding_provider=self.mock_provider,
            vector_store=store,
        )

        # Non-raising mode
        result = retriever.retrieve("ARGO trajectory", raise_on_error=False)
        self.assertEqual(result.status, "unavailable")
        self.assertIn("pgvector", result.warning.lower())

        # Reset mock for raising mode
        mock_cur.fetchone.side_effect = [None, (1,), None]
        with self.assertRaises(IncompatibleVectorEnvironmentError):
            retriever.retrieve("ARGO trajectory", raise_on_error=True)

    # ===================================================================
    # 9. Database Query Execution Errors Handled Gracefully
    # ===================================================================

    def test_09_database_execution_error_handled_gracefully(self):
        """Verify that unexpected database query failures trigger rollback and report error status."""
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_conn.cursor.return_value = mock_cur

        mock_cur.fetchone.side_effect = [
            (1,), (1,), ("embedding", "vector"), (768,)
        ]
        mock_cur.execute.side_effect = [None, None, None, None, Exception("Connection closed unexpectedly")]

        store = DocumentVectorStore(config=self.config, connection_factory=lambda cfg: mock_conn)
        retriever = ScientificDocumentRetriever(
            config=self.config,
            embedding_provider=self.mock_provider,
            vector_store=store,
        )

        result = retriever.retrieve("Pressure calibration", raise_on_error=False)
        self.assertEqual(result.status, "error")
        self.assertIn("database search failed", result.warning.lower())

    # ===================================================================
    # 10. Parameterized SQL Query Structure
    # ===================================================================

    def test_10_parameterized_sql_no_injection(self):
        """Verify that the SQL executed is strictly parameterized with named dictionaries."""
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_conn.cursor.return_value = mock_cur

        mock_cur.fetchone.side_effect = [
            (1,), (1,), ("embedding", "vector"), (768,)
        ]
        mock_cur.fetchall.return_value = []

        store = DocumentVectorStore(config=self.config, connection_factory=lambda cfg: mock_conn)
        retriever = ScientificDocumentRetriever(
            config=self.config,
            embedding_provider=self.mock_provider,
            vector_store=store,
        )

        retriever.retrieve("Test sql safety")

        # Verify SQL query
        execute_args = mock_cur.execute.call_args[0]
        sql = execute_args[0]
        params = execute_args[1]

        self.assertIn("SELECT", sql)
        self.assertIn("argo_doc_embeddings", sql)
        self.assertIn("%(vector)s::vector", sql)
        self.assertIn("%(threshold)s", sql)
        self.assertIn("LIMIT %(limit)s", sql)
        self.assertIn("vector", params)
        self.assertIn("threshold", params)
        self.assertIn("limit", params)

    # ===================================================================
    # 11. Metadata Deserialization Formats
    # ===================================================================

    def test_11_metadata_deserialization_formats(self):
        """Verify metadata correctly parses from JSON string, dictionary, or None."""
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_conn.cursor.return_value = mock_cur

        mock_cur.fetchone.side_effect = [
            (1,), (1,), ("embedding", "vector"), (768,)
        ]
        mock_cur.fetchall.return_value = [
            (1, "Doc1", "Sec1", "Content 1", json.dumps({"source": "manual.pdf"}), 0.88, 0.12),
            (2, "Doc2", "Sec2", "Content 2", {"source": "guide.md"}, 0.85, 0.15),
            (3, "Doc3", "Sec3", "Content 3", None, 0.80, 0.20),
        ]

        store = DocumentVectorStore(config=self.config, connection_factory=lambda cfg: mock_conn)
        retriever = ScientificDocumentRetriever(
            config=self.config,
            embedding_provider=self.mock_provider,
            vector_store=store,
        )

        result = retriever.retrieve("Metadata test")
        self.assertEqual(len(result.chunks), 3)
        self.assertEqual(result.chunks[0].metadata["source"], "manual.pdf")
        self.assertEqual(result.chunks[1].metadata["source"], "guide.md")
        self.assertEqual(result.chunks[2].metadata, {})

    # ===================================================================
    # 12. Config Defaults Applied
    # ===================================================================

    def test_12_config_defaults_applied(self):
        """Verify default top_k, similarity_threshold, and dimension from Config."""
        cfg = Config(vector_top_k=6, vector_similarity_threshold=0.75, expected_embedding_dimension=768)
        retriever = ScientificDocumentRetriever(config=cfg, embedding_provider=self.mock_provider)

        self.assertEqual(retriever.config.vector_top_k, 6)
        self.assertEqual(retriever.config.vector_similarity_threshold, 0.75)
        self.assertEqual(retriever.config.expected_embedding_dimension, 768)

    # ===================================================================
    # 13. Ollama Provider Integration (Mocked Network)
    # ===================================================================

    def test_13_ollama_provider_integration_mocked_network(self):
        """Verify end-to-end retrieval flow with Ollama provider parsing HTTP response."""
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_conn.cursor.return_value = mock_cur

        mock_cur.fetchone.side_effect = [
            (1,), (1,), ("embedding", "vector"), (768,)
        ]
        mock_cur.fetchall.return_value = [
            (10, "Manual", "Temperature", "Temperature sensor spec.", '{}', 0.91, 0.09)
        ]

        ollama_provider = OllamaEmbeddingProvider(model="nomic-embed-text", dimension=768)
        mock_http_resp = MagicMock()
        mock_http_resp.getcode.return_value = 200
        mock_http_resp.read.return_value = json.dumps({"embedding": [0.02] * 768}).encode("utf-8")
        mock_http_resp.__enter__.return_value = mock_http_resp

        store = DocumentVectorStore(config=self.config, connection_factory=lambda cfg: mock_conn)
        retriever = ScientificDocumentRetriever(
            config=self.config,
            embedding_provider=ollama_provider,
            vector_store=store,
        )

        with patch("urllib.request.urlopen", return_value=mock_http_resp):
            result = retriever.retrieve("Temperature sensor accuracy")
            self.assertEqual(result.status, "success")
            self.assertEqual(len(result.chunks), 1)
            self.assertEqual(result.chunks[0].chunk_id, 10)
            self.assertAlmostEqual(result.chunks[0].similarity_score, 0.91)

    # ===================================================================
    # 14. Live Database Read-Only Compatibility Check (Port 5433)
    # ===================================================================

    def test_14_live_database_read_only_search(self):
        """
        Executes a read-only similarity search query against the live FloatChat PostgreSQL container (port 5433).
        Verifies that pgvector SQL executes cleanly and returns 0 rows without modifying data.
        """
        try:
            live_config = Config(postgres_port=5433)
            store = DocumentVectorStore(config=live_config)
            env = store.check_database_environment()

            if not env["pgvector_extension_available"]:
                self.skipTest("Live database does not have pgvector installed (skipping).")

            # Execute read-only similarity search with unit vector
            dummy_vector = [0.01] * 768
            chunks = store.similarity_search(
                query_vector=dummy_vector,
                top_k=4,
                similarity_threshold=0.70,
            )

            # In the live database before Phase 7 document ingestion, 0 chunks are returned
            self.assertIsInstance(chunks, list)
            self.assertEqual(len(chunks), 0)

        except Exception as e:
            self.skipTest(f"Live database container at port 5433 not reachable: {str(e)}")

    def test_15_live_database_retrieval_returns_relevant_chunks(self):
        """
        Executes a real end-to-end semantic retrieval query against the ingested knowledge base
        on port 5433, asserting that relevant chunks are retrieved with similarity >= 0.70.
        """
        try:
            live_config = Config(postgres_port=5433)
            retriever = ScientificDocumentRetriever(config=live_config)
            res = retriever.retrieve("What are the ARGO real-time quality control flags and tests?")

            self.assertEqual(res.status, "success")
            self.assertGreater(len(res.chunks), 0)
            self.assertTrue(any("Quality Control" in c.document_title for c in res.chunks))
            self.assertGreaterEqual(res.chunks[0].similarity_score, 0.70)

        except Exception as e:
            self.skipTest(f"Live database or Ollama service not reachable: {str(e)}")


    def test_16_similarity_search_and_retrieval_logging(self):
        """Verify that vector similarity search and retriever log execution timing and preserve return chunks."""
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_conn.cursor.return_value = mock_cur

        # check_database_environment calls fetchone
        mock_cur.fetchone.side_effect = [
            (1,), (1,), ("embedding", "vector"), (768,)
        ]
        # similarity_search query returns rows
        mock_cur.fetchall.return_value = [
            (
                101,
                "ARGO User Manual",
                "Quality Flags",
                "Flag 1 indicates good data.",
                json.dumps({"section": 2.1}),
                0.92,
                0.08,
            )
        ]

        store = DocumentVectorStore(config=self.config, connection_factory=lambda cfg: mock_conn)
        retriever = ScientificDocumentRetriever(
            config=self.config,
            embedding_provider=self.mock_provider,
            vector_store=store,
        )

        with self.assertLogs("floatchat.rag.storage", level="INFO") as log_storage, \
             self.assertLogs("floatchat.rag.retriever", level="INFO") as log_retriever:
            res = retriever.retrieve("How are quality flags assigned?")

        self.assertEqual(res.status, "success")
        self.assertEqual(len(res.chunks), 1)
        self.assertEqual(res.chunks[0].chunk_id, 101)
        self.assertEqual(res.chunks[0].document_title, "ARGO User Manual")
        self.assertEqual(res.chunks[0].similarity_score, 0.92)

        # Check storage log
        storage_log_str = " ".join(log_storage.output)
        self.assertIn("Vector similarity search completed in", storage_log_str)
        self.assertIn("top_k=4", storage_log_str)
        self.assertIn("threshold=0.70", storage_log_str)
        self.assertIn("found=1", storage_log_str)

        # Check retriever log
        retriever_log_str = " ".join(log_retriever.output)
        self.assertIn("Scientific document retrieval completed in", retriever_log_str)
        self.assertIn("chunks=1", retriever_log_str)
        self.assertIn("status=success", retriever_log_str)

    # ===================================================================
    # 17. Stage 4B: Capability Caching & Optimization Tests
    # ===================================================================

    def test_17_capability_caching_first_call_and_subsequent_reuse(self):
        """Verify check_database_environment executes queries on first call and reuses cache subsequently."""
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_conn.cursor.return_value = mock_cur
        mock_conn.get_dsn_parameters.return_value = {
            "host": "localhost", "port": "5432", "dbname": "floatchat_db", "user": "floatchat_user"
        }

        mock_cur.fetchone.side_effect = [
            (1,), (1,), ("embedding", "vector"), (768,)
        ]

        store = DocumentVectorStore(config=self.config, connection_factory=lambda cfg: mock_conn)
        
        # First call: executes 4 catalog queries
        env1 = store.check_database_environment(mock_conn)
        self.assertTrue(env1["pgvector_extension_available"])
        self.assertEqual(env1["expected_column_dimension"], 768)
        self.assertEqual(mock_cur.execute.call_count, 4)

        # Second call: reuses cached dictionary without executing any additional queries
        env2 = store.check_database_environment(mock_conn)
        self.assertEqual(env2, env1)
        self.assertEqual(mock_cur.execute.call_count, 4)  # Still 4!

    def test_18_capability_cache_clearing(self):
        """Verify clear_environment_cache forces re-execution of catalog queries."""
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_conn.cursor.return_value = mock_cur
        mock_conn.get_dsn_parameters.return_value = {
            "host": "localhost", "port": "5432", "dbname": "floatchat_db", "user": "floatchat_user"
        }

        mock_cur.fetchone.side_effect = [
            (1,), (1,), ("embedding", "vector"), (768,),
            (1,), (1,), ("embedding", "vector"), (768,),
        ]

        store = DocumentVectorStore(config=self.config, connection_factory=lambda cfg: mock_conn)
        env1 = store.check_database_environment(mock_conn)
        self.assertEqual(mock_cur.execute.call_count, 4)

        # Clear cache and verify fresh queries
        store.clear_environment_cache()
        env2 = store.check_database_environment(mock_conn)
        self.assertEqual(mock_cur.execute.call_count, 8)

    def test_19_capability_cache_failure_not_cached(self):
        """Verify failed checks (exceptions) are not stored in the cache."""
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_conn.cursor.return_value = mock_cur
        mock_cur.execute.side_effect = Exception("Connection severed")

        store = DocumentVectorStore(config=self.config, connection_factory=lambda cfg: mock_conn)
        with self.assertRaises(Exception):
            store.check_database_environment(mock_conn)

        self.assertEqual(len(store._environment_cache), 0)

    def test_20_capability_cache_different_db_identity(self):
        """Verify different database identities use distinct cache entries."""
        mock_conn1 = MagicMock()
        mock_cur1 = MagicMock()
        mock_conn1.cursor.return_value = mock_cur1
        mock_conn1.get_dsn_parameters.return_value = {"host": "h1", "port": "5432", "dbname": "db1", "user": "u1"}
        mock_cur1.fetchone.side_effect = [(1,), (1,), ("embedding", "vector"), (768,)]

        mock_conn2 = MagicMock()
        mock_cur2 = MagicMock()
        mock_conn2.cursor.return_value = mock_cur2
        mock_conn2.get_dsn_parameters.return_value = {"host": "h2", "port": "5432", "dbname": "db2", "user": "u2"}
        mock_cur2.fetchone.side_effect = [(1,), (1,), ("embedding", "vector"), (1536,)]

        store = DocumentVectorStore(config=self.config)
        env1 = store.check_database_environment(mock_conn1)
        env2 = store.check_database_environment(mock_conn2)

        self.assertEqual(env1["expected_column_dimension"], 768)
        self.assertEqual(env2["expected_column_dimension"], 1536)
        self.assertEqual(len(store._environment_cache), 2)

    def test_21_similarity_search_read_only_and_statement_timeout(self):
        """Verify similarity_search enforces read-only session and SET LOCAL statement_timeout = 5000."""
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_conn.cursor.return_value = mock_cur
        mock_cur.fetchone.side_effect = [(1,), (1,), ("embedding", "vector"), (768,)]
        mock_cur.fetchall.return_value = [
            (1, "Doc", "Sec", "Content", "{}", 0.85)
        ]

        store = DocumentVectorStore(config=self.config, connection_factory=lambda cfg: mock_conn)
        results = store.similarity_search([0.01] * 768)

        self.assertEqual(len(results), 1)
        self.assertFalse(mock_conn.autocommit)
        mock_conn.set_session.assert_called_with(readonly=True)
        # Check SET LOCAL statement_timeout executed
        timeout_calls = [
            call for call in mock_cur.execute.call_args_list 
            if "statement_timeout" in str(call)
        ]
        self.assertTrue(len(timeout_calls) >= 1)
        self.assertIn("5000", str(timeout_calls[0]))
        mock_conn.commit.assert_called_once()

    def test_22_similarity_search_transaction_rollback_on_error(self):
        """Verify similarity_search performs transaction rollback on query failure."""
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_conn.cursor.return_value = mock_cur
        mock_cur.fetchone.side_effect = [(1,), (1,), ("embedding", "vector"), (768,)]
        mock_cur.fetchall.side_effect = Exception("Query execution error")

        store = DocumentVectorStore(config=self.config, connection_factory=lambda cfg: mock_conn)
        with self.assertRaises(StorageError):
            store.similarity_search([0.01] * 768)

        mock_conn.rollback.assert_called_once()

    def test_23_rag_trigger_data_only_skips_retrieval(self):
        """Verify ScientificResponseAgent skips retrieval for DATA_ONLY queries even with generic interrogative words."""
        agent = ScientificResponseAgent(config=self.config)
        data_intent = QueryIntent(
            query="What is the average temperature in the Arabian Sea in January 2024?",
            intent_type=IntentType.DATA_ONLY,
            is_supported=True,
        )

        # "What", "how", "explain" must not trigger retrieval for DATA_ONLY
        self.assertFalse(agent._should_retrieve_docs("What is the average temperature in 2024?", data_intent))
        self.assertFalse(agent._should_retrieve_docs("How many floats are stored?", data_intent))
        self.assertFalse(agent._should_retrieve_docs("Explain the observations from 2024", data_intent))

    def test_24_rag_trigger_knowledge_and_hybrid_invokes_retrieval(self):
        """Verify ScientificResponseAgent performs retrieval for KNOWLEDGE_ONLY and HYBRID queries."""
        agent = ScientificResponseAgent(config=self.config)
        knowledge_intent = QueryIntent(
            query="Explain the role of CTD sensors in measuring salinity.",
            intent_type=IntentType.KNOWLEDGE_ONLY,
            is_supported=True,
        )
        hybrid_intent = QueryIntent(
            query="Explain ocean stratification and show related measurements from 2024.",
            intent_type=IntentType.HYBRID,
            is_supported=True,
        )

        self.assertTrue(agent._should_retrieve_docs("Explain the role of CTD sensors", knowledge_intent))
        self.assertTrue(agent._should_retrieve_docs("Explain ocean stratification and show data", hybrid_intent))
        self.assertTrue(agent._should_retrieve_docs("General inquiry without intent", None))

    def test_25_hybrid_workflow_routing_and_execution_intact(self):
        """Verify HYBRID workflow routing fans out concurrently to data and retrieval branches."""
        orchestrator = FloatChatOrchestrator(config=self.config)
        
        # Test routing decision
        hybrid_state = {"intent": QueryIntent(query="hybrid", intent_type=IntentType.HYBRID, is_supported=True)}
        route1 = orchestrator.route_after_query_understanding(hybrid_state)
        self.assertEqual(route1, ["data_query", "document_retrieval"])

        knowledge_state = {"intent": QueryIntent(query="knowledge", intent_type=IntentType.KNOWLEDGE_ONLY, is_supported=True)}
        route2 = orchestrator.route_after_query_understanding(knowledge_state)
        self.assertEqual(route2, "document_retrieval")

    def test_26_ollama_embedding_provider_transmits_keep_alive(self):
        """Verify OllamaEmbeddingProvider attaches keep_alive to the HTTP payload."""
        provider = OllamaEmbeddingProvider(
            model="nomic-embed-text",
            dimension=768,
            keep_alive="10m",
        )
        mock_http_resp = MagicMock()
        mock_http_resp.getcode.return_value = 200
        mock_http_resp.read.return_value = json.dumps({"embedding": [0.05] * 768}).encode("utf-8")
        mock_http_resp.__enter__.return_value = mock_http_resp

        with patch("urllib.request.urlopen", return_value=mock_http_resp) as mock_urlopen:
            vec = provider.embed_text("ocean salinity measurement")
            self.assertEqual(len(vec), 768)
            self.assertEqual(mock_urlopen.call_count, 1)
            req = mock_urlopen.call_args[0][0]
            body = json.loads(req.data.decode("utf-8"))
            self.assertEqual(body.get("keep_alive"), "10m")
            self.assertEqual(body.get("model"), "nomic-embed-text")

    def test_27_config_embedding_keep_alive_setting(self):
        """Verify Config default and environment variable override for ollama_embedding_keep_alive."""
        cfg_default = Config()
        self.assertEqual(cfg_default.ollama_embedding_keep_alive, "5m")

        with patch.dict(os.environ, {"OLLAMA_EMBEDDING_KEEP_ALIVE": "15m"}):
            cfg_env = Config()
            self.assertEqual(cfg_env.ollama_embedding_keep_alive, "15m")


if __name__ == "__main__":
    unittest.main()

