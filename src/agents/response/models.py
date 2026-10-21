"""
src/agents/response/models.py

FloatChat Scientific Knowledge & Response Agent Models.
Defines strongly-typed Pydantic schemas representing the structured output
contract: scientific answer narratives, chunk-grounded citations, data summaries,
grounded visualization specifications, and response status metadata.
"""

from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class ResponseStatus(str, Enum):
    """Execution and grounding status for scientific responses."""
    SUCCESS = "SUCCESS"                        # Complete grounded response with evidence
    NO_DATA_MATCH = "NO_DATA_MATCH"            # Database executed but returned 0 rows
    NO_KNOWLEDGE_MATCH = "NO_KNOWLEDGE_MATCH"  # Document retrieval returned 0 chunks meeting threshold
    DEGRADED = "DEGRADED"                      # Generated with partial evidence or fallback (e.g. LLM/RAG error)
    ERROR = "ERROR"                            # Unrecoverable error in response synthesis


class ChartType(str, Enum):
    """Supported interactive visualization chart types."""
    LINE = "line"
    SCATTER = "scatter"
    MAP = "map"
    BAR = "bar"
    HISTOGRAM = "histogram"


class VisualizationSpec(BaseModel):
    """
    Validated visualization specification for rendering interactive charts.
    Must be strictly grounded in actual database result columns and values.
    """
    chart_type: ChartType = Field(description="Visual chart type (line, scatter, map, bar, histogram).")
    x_axis: str = Field(description="Column name to use for the X-axis / horizontal dimension.")
    y_axis: Optional[str] = Field(default=None, description="Column name to use for the Y-axis / vertical dimension.")
    title: str = Field(description="Human-readable title describing the visualization.")
    invert_y: bool = Field(
        default=False,
        description="True if Y-axis should be inverted (standard oceanographic profile convention for depth/pressure)."
    )
    series_column: Optional[str] = Field(
        default=None,
        description="Optional column name used to partition data into distinct traces/series (e.g. platform_number)."
    )
    description: Optional[str] = Field(
        default=None,
        description="Brief caption explaining the scientific significance of the plot."
    )


class Citation(BaseModel):
    """
    Evidence citation explicitly grounded in an authoritative scientific document chunk.
    """
    document_title: str = Field(description="Title of the authoritative scientific source document.")
    section_title: Optional[str] = Field(default=None, description="Section or chapter header where evidence appears.")
    chunk_id: Optional[str] = Field(default=None, description="Stable chunk identifier (e.g. primary key or chunk hash).")
    snippet: Optional[str] = Field(default=None, description="Brief supporting quote or excerpt from the chunk.")

    def format_citation(self) -> str:
        """Returns standard citation string [Document Title, Section Title]."""
        parts = [self.document_title]
        if self.section_title:
            parts.append(self.section_title)
        return f"[{', '.join(parts)}]"


class DataSummary(BaseModel):
    """
    Deterministic summary of measured ARGO observational data records.
    """
    total_records: int = Field(default=0, description="Total number of observation rows returned.")
    variables_present: List[str] = Field(default_factory=list, description="Names of observed physical/geographical variables.")
    temporal_coverage: Optional[str] = Field(default=None, description="Temporal span or date range of observations.")
    spatial_coverage: Optional[str] = Field(default=None, description="Geographic bounding summary of observations.")
    highlights: List[str] = Field(default_factory=list, description="Key deterministic statistics (min, max, mean, count).")


class ScientificResponse(BaseModel):
    """
    Structured outcome of the Scientific Knowledge & Response Agent.
    Unifies evidence-grounded scientific synthesis, observational data interpretation,
    citations, and visualization specifications.
    """
    answer: str = Field(description="Primary grounded Markdown answer narrative.")
    citations: List[Citation] = Field(
        default_factory=list,
        description="Authoritative citations directly referenced in the answer."
    )
    data_summary: Optional[DataSummary] = Field(
        default=None,
        description="Summary of measured observational data when database results are provided."
    )
    visualization_spec: Optional[VisualizationSpec] = Field(
        default=None,
        description="Validated visualization configuration supported by actual result columns."
    )
    status: ResponseStatus = Field(
        default=ResponseStatus.SUCCESS,
        description="Response generation status outcome."
    )
    warnings: List[str] = Field(
        default_factory=list,
        description="List of notices, degradation warnings, or grounding caveats."
    )
    raw_llm_response: Optional[str] = Field(
        default=None,
        description="Raw output from the language model for auditing/debugging if available."
    )

    @property
    def is_success(self) -> bool:
        """Returns True if the response succeeded cleanly without fatal errors."""
        return self.status in (ResponseStatus.SUCCESS, ResponseStatus.NO_DATA_MATCH, ResponseStatus.NO_KNOWLEDGE_MATCH)
