"""
src/database/models.py

FloatChat Controlled Database Execution Layer Models.
Defines strongly-typed Pydantic schemas representing database execution status,
result payloads, column definitions, and execution metadata.
"""

from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class ExecutionStatus(str, Enum):
    """Execution status outcome for controlled database queries."""
    SUCCESS = "SUCCESS"                        # Query successfully executed and results fetched
    REJECTED_INPUT = "REJECTED_INPUT"          # Input DataQueryResult is invalid, not SUCCESS, or missing SQL
    VALIDATION_FAILED = "VALIDATION_FAILED"    # Pre-execution AST re-validation failed
    CONNECTION_FAILED = "CONNECTION_FAILED"    # Database connection could not be established
    TIMEOUT = "TIMEOUT"                        # Query execution exceeded statement_timeout_ms
    EXECUTION_FAILED = "EXECUTION_FAILED"      # PostgreSQL execution error (syntax, missing table, etc.)
    SERIALIZATION_FAILED = "SERIALIZATION_FAILED"  # Result row serialization failed


class DatabaseExecutionResult(BaseModel):
    """
    Structured outcome of a controlled database query execution.
    """
    status: ExecutionStatus = Field(description="Database execution outcome status.")
    columns: List[str] = Field(
        default_factory=list,
        description="List of column names returned by the query."
    )
    rows: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="List of serialized rows as column-to-value dictionaries."
    )
    row_count: int = Field(
        default=0,
        description="Number of rows returned (capped at max limit)."
    )
    execution_time_ms: float = Field(
        default=0.0,
        description="Wall-clock query execution time in milliseconds."
    )
    is_truncated: bool = Field(
        default=False,
        description="True if returned rows exceeded limit and were truncated."
    )
    executed_sql: Optional[str] = Field(
        default=None,
        description="The exact normalized SQL query string executed against the database."
    )
    error_message: Optional[str] = Field(
        default=None,
        description="Sanitized, human-readable error description when status is not SUCCESS."
    )
    statement_timeout_ms: int = Field(
        default=5000,
        description="The statement timeout applied to the transaction in milliseconds."
    )

    @property
    def is_success(self) -> bool:
        """Returns True if execution completed successfully."""
        return self.status == ExecutionStatus.SUCCESS
