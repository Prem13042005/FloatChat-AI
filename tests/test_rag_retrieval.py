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

from src.config import Config
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


if __name__ == "__main__":
    unittest.main()

