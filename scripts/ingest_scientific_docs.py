"""
scripts/ingest_scientific_docs.py

FloatChat Scientific Document Ingestion CLI / Automation Script.
Ingests curated oceanographic and ARGO documentation into the isolated
FloatChat PostgreSQL + pgvector database container (port 5433).

Safety Guarantees:
- Enforces strict target database check (refuses to write to native port 5432).
- Verifies pgvector extension and vector(768) schema before writing.
- Idempotent: safe to run repeatedly without creating duplicate rows.
- Zero modifications to ARGO observation tables.
"""

import argparse
import logging
import os
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.config import Config, get_config
from src.rag.pipeline import DocumentIngestionPipeline
from src.rag.retriever import ScientificDocumentRetriever
from src.rag.storage import DocumentVectorStore

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("floatchat.ingest")


def run_ingestion(
    docs_dir: str = "data/scientific_docs",
    target_port: int = 5433,
    force_verify: bool = True,
):
    """
    Executes end-to-end ingestion of scientific documentation into pgvector.
    """
    logger.info("Starting FloatChat Scientific Document Ingestion...")

    # 1. Critical Database Safety Pre-check
    if target_port == 5432:
        logger.error(
            "CRITICAL SAFETY VIOLATION: Port 5432 is reserved for native Windows PostgreSQL. "
            "Ingestion writes to port 5432 are strictly prohibited."
        )
        sys.exit(1)

    config = Config(
        postgres_host="localhost",
        postgres_port=target_port,
        postgres_db="floatchat_db",
        postgres_user="floatchat_user",
        postgres_password="floatchat_password",
        expected_embedding_dimension=768,
        embedding_provider="ollama",
        embedding_model="nomic-embed-text",
        vector_top_k=4,
        vector_similarity_threshold=0.70,
    )

    # 2. Verify target database environment capabilities
    store = DocumentVectorStore(config=config)
    try:
        env = store.check_database_environment()
        logger.info("Target database environment check on port %d: %s", target_port, env)
        if not env.get("pgvector_extension_available"):
            logger.error("Database lacks pgvector extension. Ingestion cannot proceed.")
            sys.exit(1)
        if not env.get("embedding_column_exists"):
            logger.error("Database table argo_doc_embeddings lacks 'embedding' column.")
            sys.exit(1)
        if env.get("expected_column_dimension") != 768:
            logger.error(
                "Embedding column dimension is %s, expected 768.",
                env.get("expected_column_dimension"),
            )
            sys.exit(1)
    except Exception as e:
        logger.error("Failed to connect to target container on port %d: %s", target_port, str(e))
        sys.exit(1)

    # 3. Initialize Ingestion Pipeline
    pipeline = DocumentIngestionPipeline(config=config)

    docs_path = Path(docs_dir).resolve()
    if not docs_path.exists():
        logger.error("Document directory not found: %s", docs_path)
        sys.exit(1)

    logger.info("Ingesting documents from directory: %s", docs_path)
    chunks, report = pipeline.ingest_directory(docs_path)

    logger.info("=== Ingestion Summary Report ===")
    logger.info("Documents loaded:     %d", report.documents_loaded)
    logger.info("Chunks created:       %d", report.chunks_created)
    logger.info("Embeddings generated: %d", report.embeddings_generated)
    logger.info("Chunks stored in DB:  %d", report.chunks_stored)
    logger.info("Duplicates skipped:   %d", report.skipped_duplicates)
    logger.info("Vector dimension:     %s", report.vector_dimension)
    logger.info("Ingestion success:    %s", report.is_success)

    if report.warnings:
        for w in report.warnings:
            logger.warning("Warning: %s", w)
    if report.errors:
        for err in report.errors:
            logger.error("Error: %s", err)
        sys.exit(1)

    # 4. Post-ingestion verification query
    logger.info("Executing sample semantic retrieval validation...")
    retriever = ScientificDocumentRetriever(config=config)
    test_query = "What is the Practical Salinity Scale PSS-78 and how is salinity calculated?"
    result = retriever.retrieve(test_query, top_k=3)

    logger.info("Sample Query: '%s'", test_query)
    logger.info("Retrieval Status: %s | Chunks Found: %d", result.status, len(result.chunks))
    for i, chunk in enumerate(result.chunks, 1):
        logger.info(
            "  Match #%d: [%s - %s] (Similarity: %.4f, Dist: %.4f)",
            i,
            chunk.document_title,
            chunk.section_title,
            chunk.similarity_score,
            chunk.distance or 0.0,
        )
        logger.info("    Snippet: %s...", chunk.chunk_content[:120].replace("\n", " "))

    logger.info("FloatChat Scientific Document Ingestion completed successfully.")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="FloatChat Scientific Document Ingestion")
    parser.add_argument("--docs-dir", default="data/scientific_docs", help="Path to document directory")
    parser.add_argument("--port", type=int, default=5433, help="Database host port (default: 5433)")
    args = parser.parse_args()

    run_ingestion(docs_dir=args.docs_dir, target_port=args.port)
