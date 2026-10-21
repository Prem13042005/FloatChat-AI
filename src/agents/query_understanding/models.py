"""
src/agents/query_understanding/models.py

FloatChat Query Understanding Agent Data Models.
Defines strongly-typed Pydantic schemas representing structured query intents,
taxonomy classifications, and physical spatial-temporal slot constraints.
"""

from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, Field, model_validator


class IntentType(str, Enum):
    """High-level query routing intent type."""
    KNOWLEDGE_ONLY = "KNOWLEDGE_ONLY"
    DATA_ONLY = "DATA_ONLY"
    HYBRID = "HYBRID"


class IntentCategory(str, Enum):
    """Specific query taxonomy category matching FloatChat benchmark categories."""
    RETRIEVAL = "retrieval"
    FILTERING = "filtering"
    AGGREGATION = "aggregation"
    STATISTICS = "statistics"
    TEMPORAL = "temporal"
    PRESSURE_DEPTH = "pressure_depth"
    FLOAT_SPECIFIC = "float_specific"
    SPATIAL = "spatial"
    COMPARISON = "comparison"
    COMBINED = "combined"


class PhysicalVariable(str, Enum):
    """Supported V1 ARGO oceanographic variables."""
    TEMP = "TEMP"
    PSAL = "PSAL"
    PRES = "PRES"


class AggregationOp(str, Enum):
    """Supported numerical aggregation operations."""
    AVERAGE = "average"
    MINIMUM = "minimum"
    MAXIMUM = "maximum"
    COUNT = "count"
    SUM = "sum"


class SpatialBounds(BaseModel):
    """Geographic coordinate bounding box constraints (WGS84)."""
    latitude_min: Optional[float] = Field(default=None, description="Minimum latitude in degrees (-90 to 90)")
    latitude_max: Optional[float] = Field(default=None, description="Maximum latitude in degrees (-90 to 90)")
    longitude_min: Optional[float] = Field(default=None, description="Minimum longitude in degrees (-180 to 180)")
    longitude_max: Optional[float] = Field(default=None, description="Maximum longitude in degrees (-180 to 180)")

    @model_validator(mode="after")
    def validate_bounds(self) -> "SpatialBounds":
        if self.latitude_min is not None and self.latitude_max is not None:
            if self.latitude_min > self.latitude_max:
                raise ValueError(
                    f"latitude_min ({self.latitude_min}) cannot be greater than latitude_max ({self.latitude_max})"
                )
        if self.longitude_min is not None and self.longitude_max is not None:
            if self.longitude_min > self.longitude_max:
                raise ValueError(
                    f"longitude_min ({self.longitude_min}) cannot be greater than longitude_max ({self.longitude_max})"
                )
        return self


class TemporalRange(BaseModel):
    """Time-range constraints (ISO 8601 YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS)."""
    start_date: Optional[str] = Field(default=None, description="Start date/timestamp string")
    end_date: Optional[str] = Field(default=None, description="End date/timestamp string")

    @model_validator(mode="after")
    def validate_range(self) -> "TemporalRange":
        if self.start_date and self.end_date:
            if self.start_date > self.end_date:
                raise ValueError(
                    f"start_date ({self.start_date}) cannot be after end_date ({self.end_date})"
                )
        return self


class PressureRange(BaseModel):
    """Vertical pressure/depth constraints in decibars (dbar)."""
    pressure_min: Optional[float] = Field(default=None, description="Minimum ocean pressure in dbar (>= 0)")
    pressure_max: Optional[float] = Field(default=None, description="Maximum ocean pressure in dbar (>= 0)")
    is_depth_requested: bool = Field(
        default=False,
        description="True if user explicitly requested depth in meters (interpreted as 1 dbar ≈ 1 m)"
    )

    @model_validator(mode="after")
    def validate_pressure_range(self) -> "PressureRange":
        if self.pressure_min is not None and self.pressure_max is not None:
            if self.pressure_min > self.pressure_max:
                raise ValueError(
                    f"pressure_min ({self.pressure_min}) cannot be greater than pressure_max ({self.pressure_max})"
                )
        return self


class ComparisonTarget(BaseModel):
    """Structure representing comparison constraints across regions, floats, or time periods."""
    is_comparison: bool = Field(default=False, description="True if query compares multiple entities/regions")
    comparison_targets: List[str] = Field(default_factory=list, description="Entities or regions being compared")
    comparison_aspect: Optional[str] = Field(default=None, description="Property being compared (e.g. salinity)")


class QueryIntent(BaseModel):
    """
    Structured representation of a user's natural language ocean data query intent.
    Input contract between Phase 5 Query Understanding and Phase 6 Text-to-SQL / RAG.
    """
    intent_type: IntentType = Field(
        default=IntentType.DATA_ONLY,
        description="High-level intent type: KNOWLEDGE_ONLY, DATA_ONLY, or HYBRID"
    )
    intent_category: IntentCategory = Field(
        default=IntentCategory.FILTERING,
        description="Taxonomy subcategory matching FloatChat query taxonomy"
    )
    physical_variables: List[PhysicalVariable] = Field(
        default_factory=list,
        description="Requested physical observation variables (TEMP, PSAL, PRES)"
    )
    aggregation_operation: Optional[AggregationOp] = Field(
        default=None,
        description="Numerical aggregation function if requested (average, minimum, maximum, count, sum)"
    )
    spatial_bounds: Optional[SpatialBounds] = Field(
        default=None,
        description="Bounding box coordinate constraints"
    )
    temporal_range: Optional[TemporalRange] = Field(
        default=None,
        description="Temporal date/time range constraints"
    )
    pressure_range: Optional[PressureRange] = Field(
        default=None,
        description="Vertical pressure range constraints"
    )
    wmo_ids: List[str] = Field(
        default_factory=list,
        description="List of targeted float platform WMO identification numbers"
    )
    comparison_target: Optional[ComparisonTarget] = Field(
        default=None,
        description="Comparison targets and properties if query is a comparison"
    )

    # Status & Ambiguity Flags
    is_supported: bool = Field(
        default=True,
        description="True if query concept is supported by FloatChat V1"
    )
    needs_clarification: bool = Field(
        default=False,
        description="True if query prompt is ambiguous and requires user clarification"
    )
    clarification_question: Optional[str] = Field(
        default=None,
        description="Follow-up clarification question to present to user if prompt is ambiguous"
    )
    unsupported_reason: Optional[str] = Field(
        default=None,
        description="Explanation of why query request cannot be fulfilled by FloatChat V1"
    )
