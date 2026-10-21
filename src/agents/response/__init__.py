"""
src/agents/response/__init__.py

FloatChat Scientific Knowledge & Response Agent Package.
Exposes the agent, models, citations, visualization specifications, and exceptions.
"""

from src.agents.response.agent import ScientificResponseAgent
from src.agents.response.exceptions import (
    ResponseAgentException,
    ResponseGenerationError,
    ResponseValidationError,
    VisualizationGroundingError,
)
from src.agents.response.models import (
    ChartType,
    Citation,
    DataSummary,
    ResponseStatus,
    ScientificResponse,
    VisualizationSpec,
)

__all__ = [
    "ScientificResponseAgent",
    "ScientificResponse",
    "ResponseStatus",
    "ChartType",
    "VisualizationSpec",
    "Citation",
    "DataSummary",
    "ResponseAgentException",
    "ResponseGenerationError",
    "ResponseValidationError",
    "VisualizationGroundingError",
]
