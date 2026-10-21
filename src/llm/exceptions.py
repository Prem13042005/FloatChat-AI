"""
src/llm/exceptions.py

FloatChat LLM Provider Exception Hierarchy.
Provides normalized exception types for all LLM providers (Ollama, Gemini, etc.),
ensuring future AI agents do not depend on provider-specific exception classes.
"""


class LLMProviderError(Exception):
    """Base exception for all LLM provider errors."""
    pass


class LLMConnectionError(LLMProviderError):
    """Raised when connection to LLM provider fails (e.g. host unreachable, server down)."""
    pass


class LLMTimeoutError(LLMProviderError):
    """Raised when an LLM provider request times out."""
    pass


class LLMResponseError(LLMProviderError):
    """Raised when LLM provider returns an HTTP error or unexpected API error response."""
    pass


class LLMStructuredOutputError(LLMProviderError):
    """Raised when structured JSON generation or Pydantic parsing/validation fails."""
    pass


class LLMConfigurationError(LLMProviderError):
    """Raised when invalid or missing provider configuration is specified."""
    pass
