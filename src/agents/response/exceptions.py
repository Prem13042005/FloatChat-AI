"""
src/agents/response/exceptions.py

FloatChat Scientific Knowledge & Response Agent Exceptions.
Defines strongly-typed exception classes for response synthesis failures,
grounding violations, and validation errors.
"""


class ResponseAgentException(Exception):
    """Base exception for all Scientific Knowledge & Response Agent errors."""
    pass


class ResponseGenerationError(ResponseAgentException):
    """Raised when language model generation fails during response synthesis."""
    pass


class ResponseValidationError(ResponseAgentException):
    """Raised when generated response fails schema validation or grounding rules."""
    pass


class VisualizationGroundingError(ResponseAgentException):
    """Raised when a visualization specification references nonexistent columns or invalid chart types."""
    pass
