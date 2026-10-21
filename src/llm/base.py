"""
src/llm/base.py

FloatChat Base LLM Provider Interface.
Defines the provider-agnostic abstract base class that all LLM implementations
(Ollama, Gemini, etc.) must implement. Future agents depend strictly on this interface.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, Optional, Type, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


@dataclass
class GenerationResult:
    """Standardized result returned by LLM text generation calls."""
    text: str
    raw_response: Optional[Dict[str, Any]] = None
    model: Optional[str] = None
    finish_reason: Optional[str] = None


class BaseLLMProvider(ABC):
    """Abstract Base Class for all FloatChat LLM providers."""

    @abstractmethod
    def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: float = 0.0,
        max_tokens: Optional[int] = None,
        **kwargs: Any,
    ) -> GenerationResult:
        """
        Generates a text completion for the given prompt.

        Args:
            prompt: User/Input prompt text.
            system_prompt: Optional system instruction or context.
            temperature: Sampling temperature (0.0 = deterministic).
            max_tokens: Maximum completion tokens to generate.
            **kwargs: Additional provider-specific parameters.

        Returns:
            GenerationResult object containing output text and metadata.

        Raises:
            LLMConnectionError: Network connection failure.
            LLMTimeoutError: Request timeout.
            LLMResponseError: HTTP or API response failure.
            LLMProviderError: Base provider error.
        """
        pass

    @abstractmethod
    def generate_structured(
        self,
        prompt: str,
        response_model: Type[T],
        system_prompt: Optional[str] = None,
        temperature: float = 0.0,
        max_tokens: Optional[int] = None,
        **kwargs: Any,
    ) -> T:
        """
        Generates structured output validated against a Pydantic model.

        Args:
            prompt: User/Input prompt text.
            response_model: Pydantic model class to validate and instantiate.
            system_prompt: Optional system instruction or context.
            temperature: Sampling temperature (0.0 = deterministic).
            max_tokens: Maximum completion tokens to generate.
            **kwargs: Additional provider-specific parameters.

        Returns:
            Instantiated and validated Pydantic model instance.

        Raises:
            LLMStructuredOutputError: If JSON parsing or Pydantic validation fails.
            LLMProviderError: Base provider error.
        """
        pass
