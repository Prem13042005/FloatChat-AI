"""
src/llm/gemini_provider.py

FloatChat Gemini Cloud Provider Implementation.
Provides a pluggable cloud provider interface for Google Gemini API.
Uses lazy initialization to ensure Gemini imports and local Ollama development
do not require an API key or network access.
"""

import json
from typing import Any, Dict, Optional, Type, TypeVar

from pydantic import BaseModel, ValidationError

from src.config import get_config
from src.llm.base import BaseLLMProvider, GenerationResult
from src.llm.exceptions import (
    LLMConfigurationError,
    LLMConnectionError,
    LLMResponseError,
    LLMStructuredOutputError,
    LLMTimeoutError,
)

T = TypeVar("T", bound=BaseModel)


class GeminiProvider(BaseLLMProvider):
    """
    Google Gemini Cloud LLM Provider implementation.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        timeout: Optional[float] = None,
    ):
        config = get_config()
        self.api_key = api_key or config.gemini_api_key
        self.model = model or config.gemini_model
        self.timeout = timeout if timeout is not None else config.gemini_timeout_seconds
        self._genai_client = None

    def _ensure_client(self) -> None:
        """
        Lazily initializes the Google GenerativeAI client.
        Raises LLMConfigurationError if GEMINI_API_KEY is missing.
        """
        if not self.api_key or not self.api_key.strip():
            raise LLMConfigurationError(
                "Gemini API key is required but not configured. Set GEMINI_API_KEY in environment or .env."
            )

        if self._genai_client is None:
            try:
                import google.generativeai as genai
                genai.configure(api_key=self.api_key)
                self._genai_client = genai.GenerativeModel(self.model)
            except ImportError as e:
                raise LLMConfigurationError(
                    "google-generativeai SDK is not installed. Install google-generativeai to use GeminiProvider."
                ) from e
            except Exception as e:
                raise LLMConnectionError(
                    f"Failed to initialize Gemini client: {str(e)}"
                ) from e

    def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: float = 0.0,
        max_tokens: Optional[int] = None,
        **kwargs: Any,
    ) -> GenerationResult:
        """
        Generates text completion via Gemini API.
        """
        self._ensure_client()

        try:
            full_prompt = prompt
            if system_prompt:
                full_prompt = f"System: {system_prompt}\n\nUser: {prompt}"

            generation_config: Dict[str, Any] = {
                "temperature": temperature,
            }
            if max_tokens is not None:
                generation_config["max_output_tokens"] = max_tokens

            # Pass request to Gemini model
            response = self._genai_client.generate_content(
                full_prompt,
                generation_config=generation_config,
            )

            text = response.text if hasattr(response, "text") and response.text else ""

            return GenerationResult(
                text=text,
                raw_response={"text": text},
                model=self.model,
                finish_reason="stop",
            )
        except Exception as e:
            err_msg = str(e)
            if "timeout" in err_msg.lower():
                raise LLMTimeoutError(f"Gemini API request timed out: {err_msg}") from e
            if "API_KEY" in err_msg or "unauthorized" in err_msg.lower() or "403" in err_msg:
                raise LLMConfigurationError(f"Gemini API authentication failed: {err_msg}") from e
            raise LLMResponseError(f"Gemini API error: {err_msg}") from e

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
        Generates structured JSON output via Gemini and validates it against Pydantic response_model.
        """
        schema_json = json.dumps(response_model.model_json_schema(), indent=2)
        structured_system = (
            f"{system_prompt or ''}\n\n"
            f"You MUST return ONLY a valid JSON object matching this JSON Schema:\n{schema_json}\n"
            f"Do not wrap in markdown quotes or code blocks."
        ).strip()

        res = self.generate(
            prompt=prompt,
            system_prompt=structured_system,
            temperature=temperature,
            max_tokens=max_tokens,
            **kwargs,
        )

        raw_text = res.text.strip()
        if not raw_text:
            raise LLMStructuredOutputError("Gemini returned empty response string for structured output.")

        if raw_text.startswith("```json"):
            raw_text = raw_text[7:]
        if raw_text.startswith("```"):
            raw_text = raw_text[3:]
        if raw_text.endswith("```"):
            raw_text = raw_text[:-3]
        raw_text = raw_text.strip()

        try:
            parsed_json = json.loads(raw_text)
        except json.JSONDecodeError as e:
            raise LLMStructuredOutputError(
                f"Failed to decode JSON from Gemini response: {str(e)}. Raw text: '{raw_text[:200]}'"
            ) from e

        try:
            validated_obj = response_model.model_validate(parsed_json)
            return validated_obj
        except ValidationError as ve:
            raise LLMStructuredOutputError(
                f"Pydantic validation failed for model '{response_model.__name__}': {str(ve)}"
            ) from ve
