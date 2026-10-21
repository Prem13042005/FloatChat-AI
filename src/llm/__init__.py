"""
src/llm/__init__.py

FloatChat LLM Provider System Package.
Exports provider classes, base interfaces, exception types, and the `get_llm_provider` factory function.
"""

from typing import Any, Optional

from src.config import get_config
from src.llm.base import BaseLLMProvider, GenerationResult
from src.llm.exceptions import (
    LLMConfigurationError,
    LLMConnectionError,
    LLMProviderError,
    LLMResponseError,
    LLMStructuredOutputError,
    LLMTimeoutError,
)
from src.llm.gemini_provider import GeminiProvider
from src.llm.ollama_provider import OllamaProvider


def get_llm_provider(
    provider_name: Optional[str] = None,
    **kwargs: Any,
) -> BaseLLMProvider:
    """
    Factory function returning the configured LLM provider instance.

    Args:
        provider_name: Provider identifier ('ollama' or 'gemini'). Defaults to LLM_PROVIDER env config.
        **kwargs: Provider-specific parameter overrides (e.g. model, base_url, api_key, timeout).

    Returns:
        Instance of BaseLLMProvider (OllamaProvider or GeminiProvider).

    Raises:
        LLMConfigurationError: If an unsupported or invalid provider name is specified.
    """
    config = get_config()
    target_provider = (provider_name or config.llm_provider).strip().lower()

    if target_provider == "ollama":
        return OllamaProvider(**kwargs)
    elif target_provider == "gemini":
        return GeminiProvider(**kwargs)
    else:
        raise LLMConfigurationError(
            f"Unsupported LLM provider '{target_provider}'. Supported providers are: 'ollama', 'gemini'."
        )


__all__ = [
    "BaseLLMProvider",
    "GenerationResult",
    "OllamaProvider",
    "GeminiProvider",
    "get_llm_provider",
    "LLMProviderError",
    "LLMConnectionError",
    "LLMTimeoutError",
    "LLMResponseError",
    "LLMStructuredOutputError",
    "LLMConfigurationError",
]
