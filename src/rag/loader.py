"""
src/rag/loader.py

FloatChat Scientific Document Loader.
Parses authoritative scientific documentation (Markdown, PDF, Plaintext)
into strongly-typed Document objects with preserved provenance metadata.
Conservative text cleaning guarantees oceanographic symbols, units, and terms are preserved.
"""

import os
from pathlib import Path
import re
from typing import List, Optional, Union

from src.rag.exceptions import DocumentLoadingError
from src.rag.models import Document


def _clean_text_conservatively(raw_text: str) -> str:
    """
    Cleans raw document text conservatively:
    - Normalizes line endings to UNIX format (\n).
    - Removes null bytes and corrupt decoding characters.
    - Condenses multiple consecutive blank lines without collapsing paragraph boundaries.
    - Strictly preserves oceanographic symbols, formulas, and units (°C, dbar, PSU, etc.).
    """
    if not raw_text:
        return ""

    # Replace null bytes and common Unicode replacement characters
    text = raw_text.replace("\x00", "").replace("\ufffd", " ")

    # Normalize Windows CRLF to UNIX LF
    text = text.replace("\r\n", "\n").replace("\r", "\n")

    # Condense 3+ consecutive newlines into 2 (preserve paragraph separation)
    text = re.sub(r"\n{3,}", "\n\n", text)

    # Strip trailing whitespace on each line while preserving indentation
    cleaned_lines = [line.rstrip() for line in text.split("\n")]
    return "\n".join(cleaned_lines).strip()


def _extract_markdown_title(content: str, default_title: str) -> str:
    """
    Extracts the top-level H1 header (# Title) from Markdown content, if present.
    """
    match = re.search(r"^#\s+(.+)$", content, re.MULTILINE)
    if match:
        title = match.group(1).strip()
        # Remove any Markdown link syntax [Title](url) if present
        title = re.sub(r"\[(.*?)\]\(.*?\)", r"\1", title)
        return title
    return default_title


class DocumentLoader:
    """
    Loads and extracts structured text from authoritative oceanographic documents.
    Supports Markdown (.md), Plain Text (.txt), and PDF (.pdf) files.
    """

    SUPPORTED_EXTENSIONS = {".md", ".markdown", ".txt", ".pdf"}

    def load_file(self, file_path: Union[str, Path]) -> Document:
        """
        Loads a single document file from disk.

        Args:
            file_path: Absolute or relative path to the file.

        Returns:
            Document object containing cleaned content and metadata.

        Raises:
            DocumentLoadingError: If file is missing, empty, corrupt, or unsupported.
        """
        path = Path(file_path).resolve()
        if not path.exists():
            raise DocumentLoadingError(f"File not found: {path}")
        if not path.is_file():
            raise DocumentLoadingError(f"Target path is not a file: {path}")

        ext = path.suffix.lower()
        if ext not in self.SUPPORTED_EXTENSIONS:
            raise DocumentLoadingError(
                f"Unsupported file format '{ext}' for file {path.name}. "
                f"Supported formats: {sorted(list(self.SUPPORTED_EXTENSIONS))}"
            )

        file_size = path.stat().st_size
        if file_size == 0:
            raise DocumentLoadingError(f"Document file is empty (0 bytes): {path.name}")

        default_title = path.stem.replace("_", " ").replace("-", " ").title()

        if ext in {".md", ".markdown", ".txt"}:
            return self._load_text_file(path, ext, default_title, file_size)
        elif ext == ".pdf":
            return self._load_pdf_file(path, default_title, file_size)
        else:
            raise DocumentLoadingError(f"Unhandled file extension: {ext}")

    def _load_text_file(
        self,
        path: Path,
        ext: str,
        default_title: str,
        file_size: int,
    ) -> Document:
        """Loads and cleans a plain text or Markdown document."""
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                raw_content = f.read()
        except Exception as e:
            raise DocumentLoadingError(f"Failed to read file {path.name}: {str(e)}") from e

        cleaned_content = _clean_text_conservatively(raw_content)
        if not cleaned_content:
            raise DocumentLoadingError(f"Document content is empty after cleaning: {path.name}")

        file_type = "markdown" if ext in {".md", ".markdown"} else "text"
        title = _extract_markdown_title(cleaned_content, default_title) if file_type == "markdown" else default_title

        return Document(
            content=cleaned_content,
            source_path=str(path),
            document_title=title,
            file_type=file_type,
            metadata={
                "filename": path.name,
                "file_size_bytes": file_size,
                "char_count": len(cleaned_content),
            },
        )

    def _load_pdf_file(
        self,
        path: Path,
        default_title: str,
        file_size: int,
    ) -> Document:
        """Loads and extracts text page-by-page from a PDF document using pypdf."""
        try:
            import pypdf
        except ImportError:
            raise DocumentLoadingError(
                "pypdf package is required to parse PDF files. Please verify installation."
            )

        try:
            reader = pypdf.PdfReader(str(path))
            page_count = len(reader.pages)
            if page_count == 0:
                raise DocumentLoadingError(f"PDF contains 0 pages: {path.name}")

            extracted_pages: List[str] = []
            for page_idx, page in enumerate(reader.pages):
                page_text = page.extract_text() or ""
                cleaned_page = _clean_text_conservatively(page_text)
                if cleaned_page:
                    # Insert explicit page markers to preserve page number provenance during chunking
                    extracted_pages.append(f"<!-- Page {page_idx + 1} -->\n{cleaned_page}")

            full_content = "\n\n".join(extracted_pages).strip()
            if not full_content:
                raise DocumentLoadingError(f"PDF contains no extractable text: {path.name}")

            # Check if PDF metadata has title
            doc_info = reader.metadata
            title = default_title
            if doc_info and doc_info.title:
                clean_meta_title = doc_info.title.strip()
                if clean_meta_title:
                    title = clean_meta_title

            return Document(
                content=full_content,
                source_path=str(path),
                document_title=title,
                file_type="pdf",
                metadata={
                    "filename": path.name,
                    "file_size_bytes": file_size,
                    "page_count": page_count,
                    "char_count": len(full_content),
                },
            )
        except DocumentLoadingError:
            raise
        except Exception as e:
            raise DocumentLoadingError(f"Failed to parse PDF document {path.name}: {str(e)}") from e

    def load_directory(
        self,
        dir_path: Union[str, Path],
        recursive: bool = False,
    ) -> List[Document]:
        """
        Loads all supported documents from an explicit directory.

        Args:
            dir_path: Directory path to scan.
            recursive: If True, recursively scans subdirectories.

        Returns:
            List of loaded Document objects.

        Raises:
            DocumentLoadingError: If directory does not exist or contains no supported documents.
        """
        path = Path(dir_path).resolve()
        if not path.exists():
            raise DocumentLoadingError(f"Directory not found: {path}")
        if not path.is_dir():
            raise DocumentLoadingError(f"Target path is not a directory: {path}")

        pattern = "**/*" if recursive else "*"
        documents: List[Document] = []
        errors: List[str] = []

        for item in sorted(path.glob(pattern)):
            if item.is_file() and item.suffix.lower() in self.SUPPORTED_EXTENSIONS:
                try:
                    doc = self.load_file(item)
                    documents.append(doc)
                except Exception as e:
                    errors.append(f"{item.name}: {str(e)}")

        if not documents:
            err_detail = f" (Encountered errors: {'; '.join(errors)})" if errors else ""
            raise DocumentLoadingError(
                f"No valid scientific documents found in directory: {path}{err_detail}"
            )

        return documents
