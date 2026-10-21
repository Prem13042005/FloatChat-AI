"""
src/llm/ollama_provider.py

FloatChat Ollama Provider Implementation.
Communicates with local Ollama server via standard HTTP API endpoints (/api/generate).
Uses Python standard library urllib.request for zero additional third-party dependencies.
"""

import json
import socket
import urllib.error
import urllib.request
from typing import Any, Dict, Optional, Type, TypeVar

from pydantic import BaseModel, ValidationError

from src.config import get_config
from src.llm.base import BaseLLMProvider, GenerationResult
from src.llm.exceptions import (
    LLMConnectionError,
    LLMResponseError,
    LLMStructuredOutputError,
    LLMTimeoutError,
)

T = TypeVar("T", bound=BaseModel)


class OllamaProvider(BaseLLMProvider):
    """
    Ollama LLM Provider implementation for local inference.
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        timeout: Optional[float] = None,
    ):
        config = get_config()
        self.base_url = (base_url or config.ollama_base_url).rstrip("/")
        self.model = model or config.ollama_model
        self.timeout = timeout if timeout is not None else config.ollama_timeout_seconds

    def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: float = 0.0,
        max_tokens: Optional[int] = None,
        **kwargs: Any,
    ) -> GenerationResult:
        """
        Generates text completion via Ollama POST /api/generate endpoint.
        """
        payload: Dict[str, Any] = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": temperature,
            },
        }

        if system_prompt:
            payload["system"] = system_prompt

        if max_tokens is not None:
            payload["options"]["num_predict"] = max_tokens

        # Merge additional options/kwargs if provided
        format_param = kwargs.get("format")
        if format_param:
            payload["format"] = format_param

        response_data = self._post_generate(payload)

        text = response_data.get("response", "")
        if text is None:
            text = ""

        return GenerationResult(
            text=text,
            raw_response=response_data,
            model=response_data.get("model", self.model),
            finish_reason=response_data.get("done_reason", "stop" if response_data.get("done") else None),
        )

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
        Generates structured JSON output and validates it against the provided Pydantic model.
        """
        # Inject schema guidelines into system prompt
        schema_json = json.dumps(response_model.model_json_schema(), indent=2)
        structured_system = (
            f"{system_prompt or ''}\n\n"
            f"You MUST return ONLY a valid JSON object matching this JSON Schema:\n{schema_json}\n"
            f"Do not wrap in markdown quotes or code blocks."
        ).strip()

        # Enforce Ollama JSON mode via format="json"
        res = self.generate(
            prompt=prompt,
            system_prompt=structured_system,
            temperature=temperature,
            max_tokens=max_tokens,
            format="json",
            **kwargs,
        )

        raw_text = res.text.strip()
        if not raw_text:
            raise LLMStructuredOutputError("Ollama returned empty response string for structured output.")

        # Clean potential markdown wrapping if present
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
                f"Failed to decode JSON from Ollama response: {str(e)}. Raw text: '{raw_text[:200]}'"
            ) from e

        try:
            validated_obj = response_model.model_validate(parsed_json)
            return validated_obj
        except ValidationError as ve:
            raise LLMStructuredOutputError(
                f"Pydantic validation failed for model '{response_model.__name__}': {str(ve)}"
            ) from ve

    def _post_generate(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Internal HTTP POST request executor with exception normalization.
        """
        endpoint = f"{self.base_url}/api/generate"
        json_bytes = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            endpoint,
            data=json_bytes,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                resp_bytes = resp.read()
                resp_str = resp_bytes.decode("utf-8")
                return json.loads(resp_str)
        except socket.timeout as e:
            raise LLMTimeoutError(
                f"Ollama request timed out after {self.timeout}s calling '{endpoint}'."
            ) from e
        except urllib.error.HTTPError as e:
            if e.code == 404:
                raise LLMResponseError(
                    f"Ollama HTTP 404: Model '{self.model}' or endpoint '{endpoint}' not found. "
                    f"Ensure model is pulled (e.g. `ollama pull {self.model}`)."
                ) from e
            raise LLMResponseError(
                f"Ollama HTTP Error {e.code}: {e.reason}"
            ) from e
        except urllib.error.URLError as e:
            if isinstance(e.reason, socket.timeout):
                raise LLMTimeoutError(
                    f"Ollama request timed out after {self.timeout}s calling '{endpoint}'."
                ) from e
            raise LLMConnectionError(
                f"Failed to connect to Ollama server at '{self.base_url}': {e.reason}. "
                f"Ensure Ollama server is running."
            ) from e
        except json.JSONDecodeError as e:
            raise LLMResponseError(
                f"Malformed non-JSON response received from Ollama server at '{endpoint}'."
            ) from e
        except Exception as e:
            raise LLMConnectionError(
                f"Unexpected error communicating with Ollama server: {str(e)}"
            ) from e
