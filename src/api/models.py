"""
src/api/models.py

FloatChat FastAPI Request and Response Models.
Defines strongly-typed Pydantic schemas for the REST API endpoints:
- POST /api/v1/chat (and /api/v1/query)
- GET /health
- GET /ready
- Standardized error envelopes
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, field_validator

from src.agents.response.models import Citation, DataSummary, VisualizationSpec


class ChatRequest(BaseModel):
    """
    Request payload for natural language ocean data querying.
    """
    query: str = Field(
        ...,
        min_length=1,
        max_length=2000,
        description="Natural language question or ARGO observation request.",
        examples=["How do CTD sensors measure salinity?", "Show water temperature readings in the Arabian Sea."]
    )
    session_id: Optional[str] = Field(
        default=None,
        max_length=128,
        description="Optional client session identifier for request context tracking.",
        examples=["sess-12345"]
    )

    @field_validator("query")
    @classmethod
    def validate_query_not_whitespace(cls, v: str) -> str:
        cleaned = v.strip()
        if not cleaned:
            raise ValueError("Query cannot be empty or whitespace-only.")
        return cleaned


class SQLMeta(BaseModel):
    """
    Metadata describing SQL query generation and database execution.
    """
    generated_sql: Optional[str] = Field(default=None, description="Validated SQL query executed against PostgreSQL.")
    execution_time_ms: Optional[float] = Field(default=None, description="Query execution wall-clock time in milliseconds.")
    row_count: Optional[int] = Field(default=None, description="Number of observation rows returned.")
    is_truncated: Optional[bool] = Field(default=None, description="True if query results were capped at row limit.")


class ChatResponse(BaseModel):
    """
    Structured outcome returned by the FloatChat AI Service.
    Conforms to Java backend integration specifications.
    """
    session_id: Optional[str] = Field(default=None, description="Echoed client session identifier.")
    intent_type: str = Field(description="High-level intent classification (KNOWLEDGE_ONLY, DATA_ONLY, HYBRID).")
    answer: str = Field(description="Evidence-grounded scientific or observational Markdown response narrative.")
    citations: List[Citation] = Field(
        default_factory=list,
        description="Authoritative document citations grounded in retrieved passages."
    )
    sql_meta: Optional[SQLMeta] = Field(
        default=None,
        description="SQL generation and execution metrics when an observation query was run."
    )
    visualization_spec: Optional[VisualizationSpec] = Field(
        default=None,
        description="Validated visualization configuration grounded in returned observation columns."
    )
    data_summary: Optional[DataSummary] = Field(
        default=None,
        description="Summary of observational statistics and geographic/temporal bounds."
    )
    status: str = Field(default="SUCCESS", description="Workflow execution status (SUCCESS, DEGRADED, NO_DATA_MATCH, etc.).")
    warnings: List[str] = Field(default_factory=list, description="Caveats, degradation notices, or truncation warnings.")


class HealthResponse(BaseModel):
    """
    Liveness probe reporting process status.
    """
    status: str = Field(default="healthy", description="Service liveness status.")
    version: str = Field(default="0.5.0", description="FloatChat version identifier.")
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="UTC timestamp of the health check."
    )


class ReadinessResponse(BaseModel):
    """
    Readiness probe verifying essential runtime dependencies without modifying data.
    """
    status: str = Field(description="'ready' if all critical dependencies are accessible, otherwise 'not_ready'.")
    database: str = Field(description="Database connectivity status ('connected', 'unreachable', 'misconfigured').")
    postgis: str = Field(description="PostGIS extension status ('available', 'missing', 'unverified').")
    pgvector: str = Field(description="pgvector extension status ('available', 'missing', 'unverified').")
    llm_provider: str = Field(description="Configured LLM provider and active model name.")
    embedding_provider: str = Field(description="Configured embedding provider and vector model name.")
    details: Dict[str, Any] = Field(default_factory=dict, description="Diagnostic details or sanitized error messages.")
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="UTC timestamp of the readiness check."
    )


class ErrorDetail(BaseModel):
    """
    Standardized error envelope preventing exposure of stack traces, paths, or secrets.
    """
    error_code: str = Field(description="Standardized FloatChat error code.")
    message: str = Field(description="User-facing sanitized error description.")
    details: Optional[str] = Field(default=None, description="Optional safe contextual details.")
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="UTC timestamp of the error event."
    )
