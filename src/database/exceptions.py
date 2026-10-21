"""
src/database/exceptions.py

FloatChat Controlled Database Execution Layer Exceptions.
Defines a domain-specific hierarchy for database connection, validation,
timeout, and execution errors.
"""

from typing import List, Optional


class DatabaseExecutionError(Exception):
    """Base exception for all database execution layer errors."""
    pass


class ExecutionInputRejectionError(DatabaseExecutionError):
    """Raised when input DataQueryResult does not meet the execution trust boundary."""
    pass


class PreExecutionValidationError(DatabaseExecutionError):
    """Raised when candidate SQL fails re-validation immediately before execution."""

    def __init__(self, message: str, errors: Optional[List[str]] = None):
        super().__init__(message)
        self.errors = errors or []


class DatabaseConnectionError(DatabaseExecutionError):
    """Raised when connection to PostgreSQL fails."""
    pass


class DatabaseTimeoutError(DatabaseExecutionError):
    """Raised when database query execution exceeds the configured statement timeout."""

    def __init__(self, message: str, timeout_ms: int = 5000):
        super().__init__(message)
        self.timeout_ms = timeout_ms


class QueryExecutionError(DatabaseExecutionError):
    """Raised when PostgreSQL returns an execution error."""
    pass


class SerializationError(DatabaseExecutionError):
    """Raised when returned row values cannot be serialized into JSON-compatible types."""
    pass
