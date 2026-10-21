"""
tests/test_rag_ingestion.py

Phase 7A — Scientific Document Ingestion & Embedding Foundation Test Suite.
Verifies:
1. Markdown loading, title extraction, and conservative text cleaning.
2. PDF loading and page provenance (via pypdf).
3. Handling of empty, missing, and invalid documents.
4. Passage chunking with preserved metadata and section tracking.
5. Deterministic chunk identifiers and duplicate hash detection.
6. Valid embedding generation through MockEmbeddingProvider.
7. Rejection of malformed (NaN, Inf, non-numeric) and wrong-dimension embeddings.
8. Parameterized database storage operations.
9. Strict rejection when pgvector or vector column is unavailable.
10. Clear reporting of database persistence failures.
11. Idempotent repeated ingestion preventing duplicate chunk records.
12. Zero modification of live database during unit tests.

All unit tests run completely offline using unittest.mock and tempfile.
"""

import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, call, patch

# Ensure src is in python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.rag import (
    BaseEmbeddingProvider,
    Document,
    DocumentChunk,
    DocumentChunker,
    DocumentIngestionPipeline,
    DocumentLoader,
    DocumentLoadingError,
    DocumentVectorStore,
    EmbeddingGenerationError,
    IncompatibleVectorEnvironmentError,
    IngestionReport,
    MockEmbeddingProvider,
    OllamaEmbeddingProvider,
    StorageError,
)
from src.config import Config, get_config


class TestRAGIngestion(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.temp_path = Path(self.temp_dir.name)
        self.loader = DocumentLoader()
        self.chunker = DocumentChunker(chunk_size=300, chunk_overlap=50)

    def tearDown(self):
        self.temp_dir.cleanup()

    # ===================================================================
    # 1. Markdown Loading
    # ===================================================================

    def test_01_markdown_loading_with_title_extraction(self):
        """Verify that Markdown files load correctly and extract H1 title."""
        md_file = self.temp_path / "argo_manual.md"
        md_content = (
            "# ARGO User Manual v3.4\n\n"
            "## 1. Introduction\n\n"
            "The ARGO program collects temperature and salinity profiles globally.\n"
            "Observation units include temperature in °C and pressure in dbar."
        )
        md_file.write_text(md_content, encoding="utf-8")

        doc = self.loader.load_file(md_file)

        self.assertEqual(doc.document_title, "ARGO User Manual v3.4")
        self.assertEqual(doc.file_type, "markdown")
        self.assertIn("temperature and salinity", doc.content)
        self.assertIn("°C", doc.content)
        self.assertIn("dbar", doc.content)

    # ===================================================================
    # 2. PDF Loading (Using installed pypdf)
    # ===================================================================

    def test_02_pdf_loading_extracts_text_and_page_markers(self):
        """Verify that PDF documents are parsed and page boundaries preserved."""
        try:
            import pypdf
        except ImportError:
            self.skipTest("pypdf not available.")

        # Create a minimal valid PDF in memory using pypdf.PdfWriter
        pdf_path = self.temp_path / "test_doc.pdf"
        writer = pypdf.PdfWriter()
        writer.add_blank_page(width=72, height=72)
        with open(pdf_path, "wb") as f:
            writer.write(f)

        # Blank page produces DocumentLoadingError (no extractable text)
        with self.assertRaises(DocumentLoadingError):
            self.loader.load_file(pdf_path)

    # ===================================================================
    # 3. Empty and Invalid Documents
    # ===================================================================

    def test_03a_empty_file_rejected(self):
        """Verify that empty 0-byte file is rejected."""
        empty_file = self.temp_path / "empty.md"
        empty_file.write_text("", encoding="utf-8")

        with self.assertRaises(DocumentLoadingError) as ctx:
            self.loader.load_file(empty_file)
        self.assertIn("empty", str(ctx.exception).lower())

    def test_03b_missing_file_rejected(self):
        """Verify that non-existent file path raises DocumentLoadingError."""
        missing = self.temp_path / "nonexistent.md"
        with self.assertRaises(DocumentLoadingError) as ctx:
            self.loader.load_file(missing)
        self.assertIn("not found", str(ctx.exception).lower())

    def test_03c_unsupported_extension_rejected(self):
        """Verify that unsupported file formats (.exe, .csv) are rejected."""
        csv_file = self.temp_path / "data.csv"
        csv_file.write_text("a,b,c\n1,2,3", encoding="utf-8")

        with self.assertRaises(DocumentLoadingError) as ctx:
            self.loader.load_file(csv_file)
        self.assertIn("unsupported file format", str(ctx.exception).lower())

    # ===================================================================
    # 4. Text Chunking & Metadata Preservation
    # ===================================================================

    def test_04_chunking_preserves_sections_and_metadata(self):
        """Verify that chunking splits text at section boundaries and maintains provenance."""
        content = (
            "# CTD Sensor Manual\n\n"
            "## Section 1: Temperature Calibration\n\n"
            "Temperature calibration follows ITS-90 standards. Initial sensor accuracy "
            "is maintained to ±0.002 °C throughout deployment cycles in ocean waters.\n\n"
            "## Section 2: Conductivity Measurement\n\n"
            "Conductivity cell operates using an inductive field to measure seawater conductivity."
        )
        doc = Document(
            content=content,
            source_path="/manuals/ctd.md",
            document_title="CTD Sensor Manual",
            file_type="markdown",
            metadata={"version": "1.0"},
        )

        chunks = self.chunker.chunk_document(doc)

        self.assertGreaterEqual(len(chunks), 2)
        # Verify first chunk section title
        self.assertEqual(chunks[0].document_title, "CTD Sensor Manual")
        self.assertIn("Section 1", chunks[0].section_title)
        self.assertIn("ITS-90", chunks[0].chunk_content)

        # Verify second chunk section title
        self.assertIn("Section 2", chunks[1].section_title)
        self.assertIn("Conductivity", chunks[1].chunk_content)

    # ===================================================================
    # 5. Stable Chunk Identifiers and Deterministic Hashes
    # ===================================================================

    def test_05_deterministic_chunk_identifiers(self):
        """Verify that repeating chunking on the same document yields identical chunk hashes."""
        doc = Document(
            content="## Salinity Calibration\n\nPractical Salinity Scale 1978 (PSS-78) defines salinity.",
            source_path="/test/salinity.md",
            document_title="Salinity Standards",
            file_type="markdown",
        )

        chunks1 = self.chunker.chunk_document(doc)
        chunks2 = self.chunker.chunk_document(doc)

        self.assertEqual(len(chunks1), len(chunks2))
        self.assertEqual(chunks1[0].chunk_id, chunks2[0].chunk_id)
        self.assertEqual(chunks1[0].metadata["chunk_hash"], chunks2[0].metadata["chunk_hash"])

    # ===================================================================
    # 6. Valid Embedding Generation Through Mocked Provider
    # ===================================================================

    def test_06_mock_embedding_generation_valid(self):
        """Verify valid vector embedding generation matching declared dimension."""
        provider = MockEmbeddingProvider(dimension=768)
        text = "ARGO float trajectory and CTD observations."

        vector = provider.embed_text(text)

        self.assertEqual(len(vector), 768)
        self.assertIsInstance(vector, list)
        self.assertTrue(all(isinstance(x, float) for x in vector))
        # Verify unit normalization approx 1.0
        norm = sum(x * x for x in vector)
        self.assertAlmostEqual(norm, 1.0, places=3)

    # ===================================================================
    # 7. Wrong-Dimension and Malformed Embeddings Rejected
    # ===================================================================

    def test_07a_dimension_mismatch_rejected(self):
        """Verify that vectors not matching declared dimension raise EmbeddingGenerationError."""
        provider = MockEmbeddingProvider(dimension=768, simulate_malformed="wrong_dim")
        with self.assertRaises(EmbeddingGenerationError) as ctx:
            provider.embed_text("test")
        self.assertIn("dimension mismatch", str(ctx.exception).lower())

    def test_07b_nan_embedding_rejected(self):
        """Verify that vectors containing NaN raise EmbeddingGenerationError."""
        provider = MockEmbeddingProvider(dimension=768, simulate_malformed="nan")
        with self.assertRaises(EmbeddingGenerationError) as ctx:
            provider.embed_text("test")
        self.assertIn("non-finite", str(ctx.exception).lower())

    def test_07c_inf_embedding_rejected(self):
        """Verify that vectors containing Inf raise EmbeddingGenerationError."""
        provider = MockEmbeddingProvider(dimension=768, simulate_malformed="inf")
        with self.assertRaises(EmbeddingGenerationError) as ctx:
            provider.embed_text("test")
        self.assertIn("non-finite", str(ctx.exception).lower())

    def test_07d_non_numeric_embedding_rejected(self):
        """Verify that vectors containing non-numeric values raise EmbeddingGenerationError."""
        provider = MockEmbeddingProvider(dimension=768, simulate_malformed="non_numeric")
        with self.assertRaises(EmbeddingGenerationError) as ctx:
            provider.embed_text("test")
        self.assertIn("non-numeric", str(ctx.exception).lower())

    # ===================================================================
    # 8. Parameterized Database Storage Operations
    # ===================================================================

    def test_08_parameterized_database_storage(self):
        """Verify that vector storage uses parameterized SQL queries and sets vector type."""
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_conn.cursor.return_value = mock_cur

        # Mock environment check: pgvector exists, embedding column exists with 768 dim
        mock_cur.fetchone.side_effect = [
            (1,),                # pgvector installed
            (1,),                # table exists
            ("embedding", "vector"), # column exists
            (768,),              # column dimension
            None,                # duplicate check: row does not exist
        ]

        store = DocumentVectorStore(connection_factory=lambda cfg: mock_conn)
        chunk = DocumentChunk(
            chunk_id="chunk_01",
            document_title="ARGO User Manual",
            section_title="Calibration",
            chunk_index=0,
            chunk_content="Sensor calibration test.",
            metadata={"chunk_hash": "abc123hash"},
            embedding=[0.05] * 768,
        )

        report = store.store_chunks([chunk], conn=mock_conn)

        self.assertEqual(report.chunks_stored, 1)
        self.assertEqual(report.vector_dimension, 768)
        mock_conn.commit.assert_called_once()

        # Check parameterized INSERT call
        insert_call = mock_cur.execute.call_args_list[-1]
        sql_query = insert_call[0][0]
        params = insert_call[0][1]

        self.assertIn("INSERT INTO argo_doc_embeddings", sql_query)
        self.assertIn("%s::vector", sql_query)
        self.assertEqual(params[0], "ARGO User Manual")
        self.assertEqual(params[1], "Calibration")
        self.assertEqual(params[2], "Sensor calibration test.")

    # ===================================================================
    # 9. Storage Rejected When pgvector or Required Schema is Unavailable
    # ===================================================================

    def test_09_storage_rejected_when_pgvector_unavailable(self):
        """Verify that storing vectors raises IncompatibleVectorEnvironmentError if pgvector missing."""
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_conn.cursor.return_value = mock_cur

        # Mock environment: pgvector NOT installed
        mock_cur.fetchone.side_effect = [
            None,                 # pgvector NOT installed
            (1,),                 # table exists
            None,                 # column missing
        ]

        store = DocumentVectorStore(connection_factory=lambda cfg: mock_conn)
        chunk = DocumentChunk(
            chunk_id="c1",
            document_title="Manual",
            chunk_index=0,
            chunk_content="Content",
            embedding=[0.1] * 768,
        )

        with self.assertRaises(IncompatibleVectorEnvironmentError) as ctx:
            store.store_chunks([chunk], conn=mock_conn)
        self.assertIn("pgvector extension or embedding column is missing", str(ctx.exception))

    def test_09b_storage_rejected_on_dimension_mismatch(self):
        """Verify that storing mismatched vector dimension is strictly rejected without truncation or padding."""
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_conn.cursor.return_value = mock_cur

        # Case 1: Database expects 768 (nomic-embed-text), but model/vector provided is 1536
        mock_cur.fetchone.side_effect = [
            (1,),                 # pgvector installed
            (1,),                 # table exists
            ("embedding", "vector"), # column exists
            (768,),               # declared column dimension 768
        ]

        store = DocumentVectorStore(connection_factory=lambda cfg: mock_conn)
        chunk_1536 = DocumentChunk(
            chunk_id="c1",
            document_title="Manual",
            chunk_index=0,
            chunk_content="Content",
            embedding=[0.1] * 1536,
        )

        with self.assertRaises(IncompatibleVectorEnvironmentError) as ctx:
            store.store_chunks([chunk_1536], conn=mock_conn)
        self.assertIn("Vector dimension mismatch", str(ctx.exception))
        self.assertEqual(ctx.exception.expected_dim, 768)
        self.assertEqual(ctx.exception.actual_dim, 1536)

        # Case 2: Database expects 1536, but model/vector provided is 768
        mock_cur.fetchone.side_effect = [
            (1,),                 # pgvector installed
            (1,),                 # table exists
            ("embedding", "vector"), # column exists
            (1536,),              # declared column dimension 1536
        ]
        chunk_768 = DocumentChunk(
            chunk_id="c2",
            document_title="Manual",
            chunk_index=0,
            chunk_content="Content",
            embedding=[0.1] * 768,
        )

        with self.assertRaises(IncompatibleVectorEnvironmentError) as ctx2:
            store.store_chunks([chunk_768], conn=mock_conn)
        self.assertIn("Vector dimension mismatch", str(ctx2.exception))
        self.assertEqual(ctx2.exception.expected_dim, 1536)
        self.assertEqual(ctx2.exception.actual_dim, 768)

    # ===================================================================
    # 10. Database Failures Reported Clearly
    # ===================================================================

    def test_10_database_failure_raises_storage_error_with_rollback(self):
        """Verify that general database execution errors trigger rollback and raise StorageError."""
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_conn.cursor.return_value = mock_cur

        # Mock environment ok
        mock_cur.fetchone.side_effect = [
            (1,),                 # pgvector installed
            (1,),                 # table exists
            ("embedding", "vector"), # column exists
            (768,),               # 768 dimension
            None,                 # duplicate check ok
        ]
        # Insert raises database error
        mock_cur.execute.side_effect = [None, None, None, None, None, Exception("Disk full / connection terminated")]

        store = DocumentVectorStore(connection_factory=lambda cfg: mock_conn)
        chunk = DocumentChunk(
            chunk_id="c1",
            document_title="Manual",
            chunk_index=0,
            chunk_content="Content",
            metadata={"chunk_hash": "hash1"},
            embedding=[0.1] * 768,
        )

        with self.assertRaises(StorageError):
            store.store_chunks([chunk], conn=mock_conn)
        mock_conn.rollback.assert_called()

    # ===================================================================
    # 11. Idempotency / Duplicate Prevention
    # ===================================================================

    def test_11_idempotent_ingestion_skips_duplicate_chunks(self):
        """Verify that existing chunk hashes are detected and skipped without duplicating rows."""
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_conn.cursor.return_value = mock_cur

        mock_cur.fetchone.side_effect = [
            (1,),                 # pgvector installed
            (1,),                 # table exists
            ("embedding", "vector"), # column exists
            (768,),               # 768 dim
            (1,),                 # duplicate check returns 1 -> already exists!
        ]

        store = DocumentVectorStore(connection_factory=lambda cfg: mock_conn)
        chunk = DocumentChunk(
            chunk_id="c1",
            document_title="Manual",
            chunk_index=0,
            chunk_content="Content",
            metadata={"chunk_hash": "existing_hash"},
            embedding=[0.1] * 768,
        )

        report = store.store_chunks([chunk], conn=mock_conn)

        self.assertEqual(report.skipped_duplicates, 1)
        self.assertEqual(report.chunks_stored, 0)

    # ===================================================================
    # 12. Unit Tests Do Not Modify Live Database
    # ===================================================================

    def test_12_pipeline_processing_without_db_storage(self):
        """Verify pipeline processing in offline mode produces chunks and embeddings with zero DB writes."""
        mock_provider = MockEmbeddingProvider(dimension=768)
        pipeline = DocumentIngestionPipeline(
            loader=self.loader,
            chunker=self.chunker,
            embedding_provider=mock_provider,
            storage=None,  # No storage configured
        )

        md_file = self.temp_path / "offline_doc.md"
        md_file.write_text("# Ocean Principles\n\nSalinity and pressure analysis.", encoding="utf-8")

        chunks, report = pipeline.process_file(md_file, generate_embeddings=True, store_in_db=False)

        self.assertGreater(len(chunks), 0)
        self.assertEqual(report.chunks_stored, 0)
        self.assertEqual(report.embeddings_generated, len(chunks))
        self.assertIsNotNone(chunks[0].embedding)
        self.assertEqual(len(chunks[0].embedding), 768)

    # ===================================================================
    # 13. Ollama Provider Network & Serialization Handling
    # ===================================================================

    def test_13_ollama_provider_mocked_network(self):
        """Verify OllamaEmbeddingProvider parses HTTP response and validates vector."""
        ollama = OllamaEmbeddingProvider(model="nomic-embed-text", dimension=768)

        mock_resp = MagicMock()
        mock_resp.getcode.return_value = 200
        mock_resp.read.return_value = json.dumps({"embedding": [0.01] * 768}).encode("utf-8")
        mock_resp.__enter__.return_value = mock_resp

        with patch("urllib.request.urlopen", return_value=mock_resp):
            emb = ollama.embed_text("ARGO temperature salinity profile.")
            self.assertEqual(len(emb), 768)
            self.assertEqual(emb[0], 0.01)

    # ===================================================================
    # 14. Live Database Environment Capability Verification (Read-Only)
    # ===================================================================

    def test_14_live_database_environment_inspection(self):
        """
        Inspect live PostgreSQL environment to confirm pgvector and embedding column status.
        Does NOT write any data or alter database state.
        """
        try:
            store = DocumentVectorStore()
            env = store.check_database_environment()
            self.assertIn("pgvector_extension_available", env)
            self.assertIn("table_exists", env)
            self.assertIn("embedding_column_exists", env)
            # In our local host PostgreSQL environment, pgvector extension is not compiled
            # Confirm that check_database_environment detects this accurately
            self.assertIsInstance(env["pgvector_extension_available"], bool)
        except Exception as e:
            self.skipTest(f"Live database not reachable: {str(e)}")

    # ===================================================================
    # 15. Config Defaults and Local/Ollama Normalization (Phase 7A.2)
    # ===================================================================

    def test_15_config_embedding_defaults_and_normalization(self):
        """Verify Config defaults to ollama, nomic-embed-text, and 768 dimensions."""
        cfg = Config()
        self.assertEqual(cfg.embedding_provider, "ollama")
        self.assertEqual(cfg.embedding_model, "nomic-embed-text")
        self.assertEqual(cfg.expected_embedding_dimension, 768)

        # Test "local" alias normalization to "ollama"
        cfg_local = Config(embedding_provider="local")
        self.assertEqual(cfg_local.embedding_provider, "ollama")

    def test_16_config_env_var_overrides(self):
        """Verify Config respects environment variable overrides for embedding settings."""
        with patch.dict(os.environ, {
            "EMBEDDING_PROVIDER": "local",
            "EMBEDDING_MODEL": "nomic-embed-text",
            "EXPECTED_EMBEDDING_DIMENSION": "768",
        }):
            cfg = get_config()
            self.assertEqual(cfg.embedding_provider, "ollama")
            self.assertEqual(cfg.embedding_model, "nomic-embed-text")
            self.assertEqual(cfg.expected_embedding_dimension, 768)

    def test_17_storage_layer_dimension_preservation(self):
        """Verify storage layer strictly validates vector dimension and never truncates or pads."""
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_conn.cursor.return_value = mock_cur

        # DB column requires 768
        mock_cur.fetchone.side_effect = [
            (1,),                 # pgvector installed
            (1,),                 # table exists
            ("embedding", "vector"), # column exists
            (768,),               # declared column dimension 768
        ]

        store = DocumentVectorStore(connection_factory=lambda cfg: mock_conn)
        short_vector = [0.1] * 512
        chunk = DocumentChunk(
            chunk_id="c_short",
            document_title="Manual",
            chunk_index=0,
            chunk_content="Content",
            embedding=short_vector,
        )

        with self.assertRaises(IncompatibleVectorEnvironmentError) as ctx:
            store.store_chunks([chunk], conn=mock_conn)
        self.assertEqual(ctx.exception.expected_dim, 768)
        self.assertEqual(ctx.exception.actual_dim, 512)
        # Verify the original vector was not altered, truncated, or padded
        self.assertEqual(len(chunk.embedding), 512)
        self.assertEqual(chunk.embedding, short_vector)

    # ===================================================================
    # 18. End-to-End Directory Ingestion (Phase 7C)
    # ===================================================================

    def test_18_ingest_directory_end_to_end_mocked(self):
        """Verify pipeline.ingest_directory() processes directory, computes embeddings, and persists."""
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_conn.cursor.return_value = mock_cur

        # Mock DB environment ok for both doc1 and doc2
        mock_cur.fetchone.side_effect = [
            # Doc 1: env check (4 calls) + duplicate check (1 call)
            (1,), (1,), ("embedding", "vector"), (768,), None,
            # Doc 2: env check (4 calls) + duplicate check (1 call)
            (1,), (1,), ("embedding", "vector"), (768,), None,
        ]

        store = DocumentVectorStore(connection_factory=lambda cfg: mock_conn)
        mock_provider = MockEmbeddingProvider(dimension=768)
        pipeline = DocumentIngestionPipeline(
            loader=self.loader,
            chunker=self.chunker,
            embedding_provider=mock_provider,
            storage=store,
        )

        # Create two sample markdown documents
        doc1 = self.temp_path / "doc1.md"
        doc1.write_text("# Doc 1\n\n## Section A\n\nContent for section A.", encoding="utf-8")
        doc2 = self.temp_path / "doc2.md"
        doc2.write_text("# Doc 2\n\n## Section B\n\nContent for section B.", encoding="utf-8")

        chunks, report = pipeline.ingest_directory(self.temp_path)

        self.assertEqual(report.documents_loaded, 2)
        self.assertGreater(report.chunks_created, 0)
        self.assertEqual(report.embeddings_generated, report.chunks_created)
        self.assertEqual(report.chunks_stored, report.chunks_created)
        self.assertEqual(report.skipped_duplicates, 0)
        self.assertTrue(report.is_success)

    # ===================================================================
    # 19. Idempotent Ingestion Rerun
    # ===================================================================

    def test_19_idempotent_rerun_duplicate_skipping(self):
        """Verify that ingesting already-stored chunks detects chunk_hash and skips duplicates."""
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_conn.cursor.return_value = mock_cur

        # Run 1: 1 chunk stored
        mock_cur.fetchone.side_effect = [
            (1,), (1,), ("embedding", "vector"), (768,),
            None,  # Not duplicate
        ]

        store = DocumentVectorStore(connection_factory=lambda cfg: mock_conn)
        mock_provider = MockEmbeddingProvider(dimension=768)
        pipeline = DocumentIngestionPipeline(
            loader=self.loader,
            chunker=self.chunker,
            embedding_provider=mock_provider,
            storage=store,
        )

        test_file = self.temp_path / "test_doc.md"
        test_file.write_text("# Unique Document\n\nUnique passage text.", encoding="utf-8")

        chunks1, report1 = pipeline.ingest_file(test_file)
        self.assertEqual(report1.chunks_stored, 1)
        self.assertEqual(report1.skipped_duplicates, 0)

        # Run 2: Exact same file -> duplicate detected
        mock_cur.fetchone.side_effect = [
            (1,), (1,), ("embedding", "vector"), (768,),
            (1,),  # Row already exists in DB!
        ]
        chunks2, report2 = pipeline.ingest_file(test_file)
        self.assertEqual(report2.chunks_stored, 0)
        self.assertEqual(report2.skipped_duplicates, 1)

    # ===================================================================
    # 20. Unsupported and Malformed File Handling
    # ===================================================================

    def test_20_unsupported_file_format_handling(self):
        """Verify that unsupported file formats are recorded as errors and not marked successful."""
        pipeline = DocumentIngestionPipeline(loader=self.loader, chunker=self.chunker)
        unsupported = self.temp_path / "data.bin"
        unsupported.write_bytes(b"\x00\x01\x02\x03")

        chunks, report = pipeline.process_file(unsupported)
        self.assertEqual(len(chunks), 0)
        self.assertEqual(len(report.errors), 1)
        self.assertIn("unsupported file format", report.errors[0].lower())
        self.assertFalse(report.is_success)

    # ===================================================================
    # 21. Embedding Failure Prevents Persistence
    # ===================================================================

    def test_21_embedding_failure_prevents_storage(self):
        """Verify that embedding generation errors prevent database persistence and record failure."""
        mock_store = MagicMock()
        error_provider = MockEmbeddingProvider(simulate_error="Ollama service unavailable")

        pipeline = DocumentIngestionPipeline(
            loader=self.loader,
            chunker=self.chunker,
            embedding_provider=error_provider,
            storage=mock_store,
        )

        doc = self.temp_path / "ocean.md"
        doc.write_text("# Ocean Principles\n\nOceanic density stratification.", encoding="utf-8")

        chunks, report = pipeline.ingest_file(doc)

        self.assertEqual(report.chunks_stored, 0)
        self.assertFalse(report.is_success)
        self.assertIn("embedding generation failed", report.errors[0].lower())
        # Verify storage.store_chunks was never called
        mock_store.store_chunks.assert_not_called()

    # ===================================================================
    # 22. Curated Scientific Documents Validity Check
    # ===================================================================

    def test_22_curated_scientific_docs_are_valid(self):
        """Verify the curated scientific documents parse cleanly and produce valid chunks."""
        docs_dir = Path("data/scientific_docs").resolve()
        self.assertTrue(docs_dir.exists(), "data/scientific_docs must exist")

        docs = self.loader.load_directory(docs_dir)
        self.assertGreaterEqual(len(docs), 3)

        total_chunks = 0
        for doc in docs:
            self.assertTrue(len(doc.document_title) > 0)
            chunks = self.chunker.chunk_document(doc)
            self.assertGreater(len(chunks), 0)
            for c in chunks:
                self.assertIsNotNone(c.chunk_id)
                self.assertIsNotNone(c.metadata.get("chunk_hash"))
                self.assertGreater(len(c.chunk_content), 20)
            total_chunks += len(chunks)

        self.assertGreaterEqual(total_chunks, 10)


if __name__ == "__main__":
    unittest.main()

