"""
src/agents/data_query/exceptions.py

FloatChat Data Query Agent Exception Hierarchy.
Defines domain-specific exceptions for SQL generation, validation, and intent routing failures.
"""

from typing import List, Optional


class DataQueryError(Exception):
    """Base exception for all Data Query Agent errors."""
    pass


class SQLValidationError(DataQueryError):
    """Raised when generated candidate SQL fails deterministic validation."""

    def __init__(
        self,
        message: str,
        errors: Optional[List[str]] = None,
        candidate_sql: Optional[str] = None,
    ):
        super().__init__(message)
        self.errors = errors or []
        self.candidate_sql = candidate_sql


class UnsupportedIntentError(DataQueryError):
    """Raised when query intent is marked unsupported for V1 oceanographic dataset."""
    pass


class AmbiguousIntentError(DataQueryError):
    """Raised when query intent requires user clarification before SQL generation."""
    pass


class InsufficientIntentError(DataQueryError):
    """Raised when query intent contains no usable search criteria, platform IDs, or variables."""
    pass


class SQLGenerationError(DataQueryError):
    """Raised when underlying LLM provider fails to generate candidate SQL."""
    pass
