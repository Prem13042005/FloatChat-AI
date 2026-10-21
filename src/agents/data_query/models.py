"""
src/agents/data_query/models.py

FloatChat Data Query Agent Data Models.
Defines strongly-typed Pydantic schemas representing candidate SQL generation,
typed execution outcomes, and validation status.
"""

from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class DataQueryStatus(str, Enum):
    """Status enumeration for Data Query Agent execution outcomes."""
    SUCCESS = "SUCCESS"                        # Candidate SQL generated and successfully validated
    NO_SQL_REQUIRED = "NO_SQL_REQUIRED"        # Query intent is KNOWLEDGE_ONLY, no SQL query needed
    UNSUPPORTED_INTENT = "UNSUPPORTED_INTENT"  # Intent marked unsupported for V1 dataset
    AMBIGUOUS_INTENT = "AMBIGUOUS_INTENT"      # Intent requires clarification before SQL generation
    INSUFFICIENT_INTENT = "INSUFFICIENT_INTENT"# Intent lacks sufficient parameters to construct SQL
    VALIDATION_FAILED = "VALIDATION_FAILED"    # Candidate SQL failed deterministic AST validation
    GENERATION_FAILED = "GENERATION_FAILED"    # LLM provider error during SQL generation


class SQLCandidate(BaseModel):
    """Structured LLM candidate SQL generation payload."""
    sql: str = Field(description="The complete PostgreSQL/PostGIS SELECT query string.")
    explanation: Optional[str] = Field(
        default=None,
        description="Brief explanation of how intent constraints were mapped to SQL."
    )


class DataQueryResult(BaseModel):
    """
    Complete typed output of the Data Query Agent.
    Contains the validated SQL query (if successful) or explicit failure details.
    """
    status: DataQueryStatus = Field(description="Execution and validation status outcome.")
    sql: Optional[str] = Field(
        default=None,
        description="Normalized, validated SQL query string. Present only when status is SUCCESS."
    )
    raw_candidate_sql: Optional[str] = Field(
        default=None,
        description="Raw candidate SQL string from LLM before AST normalization."
    )
    explanation: Optional[str] = Field(
        default=None,
        description="Optional LLM explanation of candidate query generation."
    )
    validation_errors: List[str] = Field(
        default_factory=list,
        description="List of security or schema validation errors from DeterministicSQLValidator."
    )
    validation_warnings: List[str] = Field(
        default_factory=list,
        description="List of validation warnings (e.g. LIMIT injection or capping)."
    )
    validation_details: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Serialized SQLValidationResult dictionary."
    )
    error_message: Optional[str] = Field(
        default=None,
        description="Human-readable explanation when status is not SUCCESS."
    )
    retry_count: int = Field(
        default=0,
        description="Number of regeneration/validation retry attempts made (0 or 1)."
    )

    @property
    def is_success(self) -> bool:
        """Returns True if candidate SQL was generated and successfully validated."""
        return self.status == DataQueryStatus.SUCCESS

    @property
    def is_executable(self) -> bool:
        """Returns True if candidate SQL is successfully validated and has query string."""
        return self.status == DataQueryStatus.SUCCESS and bool(self.sql and self.sql.strip())

