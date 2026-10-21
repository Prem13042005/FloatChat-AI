"""
src/rag/chunker.py

FloatChat Scientific Document Chunker.
Splits parsed documents into bounded, semantically coherent passages.
Preserves document title, section headers, page numbers, and computes
deterministic, stable chunk hashes to guarantee idempotent vector ingestion.
"""

import hashlib
import re
from typing import List, Optional

from src.rag.exceptions import ChunkingError
from src.rag.models import Document, DocumentChunk

DEFAULT_CHUNK_SIZE: int = 1000      # Character count threshold (~200-250 words)
DEFAULT_CHUNK_OVERLAP: int = 150    # Character overlap between adjacent chunks
MIN_CHUNK_SIZE: int = 60            # Minimum chunk size to avoid orphan fragments


class DocumentChunker:
    """
    Splits scientific documents into overlapping, bounded passages with preserved context.
    """

    def __init__(
        self,
        chunk_size: int = DEFAULT_CHUNK_SIZE,
        chunk_overlap: int = DEFAULT_CHUNK_OVERLAP,
        min_chunk_size: int = MIN_CHUNK_SIZE,
    ):
        """
        Initializes the DocumentChunker.

        Args:
            chunk_size: Maximum character size of each chunk.
            chunk_overlap: Number of overlapping characters between consecutive chunks.
            min_chunk_size: Minimum character length for a standalone chunk.
        """
        if chunk_size <= 0:
            raise ValueError("chunk_size must be positive.")
        if chunk_overlap < 0:
            raise ValueError("chunk_overlap cannot be negative.")
        if chunk_overlap >= chunk_size:
            raise ValueError("chunk_overlap must be strictly less than chunk_size.")

        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.min_chunk_size = min_chunk_size

    def chunk_document(self, document: Document) -> List[DocumentChunk]:
        """
        Splits a single Document into a sequence of DocumentChunk objects.

        Args:
            document: Document object produced by DocumentLoader.

        Returns:
            List of DocumentChunk objects with section, page, and hash metadata.
        """
        if not document.content or not document.content.strip():
            return []

        # Split document by paragraphs or sections
        raw_sections = self._split_by_sections(document.content)
        chunks: List[DocumentChunk] = []
        global_chunk_idx = 0

        for section_title, current_page, section_text in raw_sections:
            if not section_text.strip():
                continue

            section_chunks = self._recursive_split_text(section_text)
            for chunk_text in section_chunks:
                clean_chunk = chunk_text.strip()
                if len(clean_chunk) < self.min_chunk_size and chunks:
                    # Append very small trailing fragment to previous chunk if within size
                    prev = chunks[-1]
                    if len(prev.chunk_content) + len(clean_chunk) + 1 <= self.chunk_size * 1.3:
                        prev.chunk_content = f"{prev.chunk_content}\n\n{clean_chunk}"
                        prev.metadata["char_count"] = len(prev.chunk_content)
                        continue

                # Generate deterministic chunk hash based on source, title, and content
                hash_input = f"{document.document_title}|{section_title or ''}|{clean_chunk}"
                chunk_hash = hashlib.sha256(hash_input.encode("utf-8")).hexdigest()[:16]

                # Format stable chunk identifier
                safe_title = re.sub(r"[^a-zA-Z0-9]+", "_", document.document_title).strip("_").lower()[:24]
                chunk_id = f"{safe_title}_{global_chunk_idx:04d}_{chunk_hash[:8]}"

                chunk = DocumentChunk(
                    chunk_id=chunk_id,
                    document_title=document.document_title,
                    section_title=section_title,
                    chunk_index=global_chunk_idx,
                    page_number=current_page,
                    chunk_content=clean_chunk,
                    metadata={
                        "source_path": document.source_path,
                        "file_type": document.file_type,
                        "chunk_hash": chunk_hash,
                        "char_count": len(clean_chunk),
                        "word_count": len(clean_chunk.split()),
                    },
                )
                chunks.append(chunk)
                global_chunk_idx += 1

        return chunks

    def _split_by_sections(self, content: str) -> List[tuple[Optional[str], Optional[int], str]]:
        """
        Scans content for Markdown headers and PDF page markers to segment text into sections.
        Returns list of (section_title, page_number, section_content).
        """
        lines = content.split("\n")
        sections: List[tuple[Optional[str], Optional[int], str]] = []

        current_section: Optional[str] = None
        current_page: Optional[int] = None
        current_lines: List[str] = []

        for line in lines:
            # Check for PDF Page marker <!-- Page N -->
            page_match = re.match(r"^<!--\s*Page\s+(\d+)\s*-->$", line.strip())
            if page_match:
                current_page = int(page_match.group(1))
                continue

            # Check for Markdown header (# Header)
            header_match = re.match(r"^(#{1,4})\s+(.+)$", line)
            if header_match:
                # Flush existing buffer if it contains body content
                if current_lines:
                    text_block = "\n".join(current_lines).strip()
                    content_without_headers = "\n".join([l for l in current_lines if not re.match(r"^#{1,4}\s+", l)]).strip()
                    if content_without_headers:
                        sections.append((current_section, current_page, text_block))
                    current_lines = []
                current_section = header_match.group(2).strip()
                current_lines.append(line)
            else:
                current_lines.append(line)

        # Flush final buffer
        if current_lines:
            text_block = "\n".join(current_lines).strip()
            if text_block:
                sections.append((current_section, current_page, text_block))

        return sections

    def _recursive_split_text(self, text: str) -> List[str]:
        """
        Recursively splits text into segments under self.chunk_size with self.chunk_overlap.
        Prefers natural boundaries: paragraph break (\n\n) -> newline (\n) -> sentence (. ) -> space.
        """
        if len(text) <= self.chunk_size:
            return [text]

        # Candidate separators ordered by semantic integrity
        separators = ["\n\n", "\n", ". ", "; ", ", ", " "]

        def split_segment(seg: str, sep_idx: int) -> List[str]:
            if len(seg) <= self.chunk_size or sep_idx >= len(separators):
                # Cannot split further by separator, chunk by fixed window with overlap
                chunks = []
                start = 0
                while start < len(seg):
                    end = start + self.chunk_size
                    chunks.append(seg[start:end])
                    if end >= len(seg):
                        break
                    start += self.chunk_size - self.chunk_overlap
                return chunks

            sep = separators[sep_idx]
            parts = seg.split(sep)
            result_chunks = []
            current_chunk = ""

            for part in parts:
                candidate = f"{current_chunk}{sep}{part}" if current_chunk else part
                if len(candidate) <= self.chunk_size:
                    current_chunk = candidate
                else:
                    if current_chunk:
                        result_chunks.append(current_chunk)
                    if len(part) > self.chunk_size:
                        # Part itself exceeds chunk_size, split with next separator
                        sub_chunks = split_segment(part, sep_idx + 1)
                        result_chunks.extend(sub_chunks)
                        current_chunk = ""
                    else:
                        current_chunk = part

            if current_chunk:
                result_chunks.append(current_chunk)

            return result_chunks

        raw_chunks = split_segment(text, 0)
        return [c.strip() for c in raw_chunks if c.strip()]
