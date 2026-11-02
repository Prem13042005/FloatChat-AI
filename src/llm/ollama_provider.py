"""
src/llm/ollama_provider.py

FloatChat Ollama Provider Implementation.
Communicates with local Ollama server via standard HTTP API endpoints (/api/generate).
Uses Python standard library urllib.request for zero additional third-party dependencies.
"""

import enum
import json
import logging
import socket
import urllib.error
import urllib.request
from typing import Any, Dict, List, Literal, Optional, Set, Tuple, Type, TypeVar, Union, get_args, get_origin

from pydantic import BaseModel, ValidationError
from pydantic_core import PydanticUndefined

from src.config import get_config
from src.llm.base import BaseLLMProvider, GenerationResult
from src.llm.exceptions import (
    LLMConnectionError,
    LLMResponseError,
    LLMStructuredOutputError,
    LLMTimeoutError,
)

logger = logging.getLogger("floatchat.llm.ollama")

T = TypeVar("T", bound=BaseModel)


def _ns_to_ms(val: Any) -> Optional[float]:
    """Converts Ollama duration in nanoseconds to milliseconds (rounded to 2 decimal places)."""
    if val is not None and isinstance(val, (int, float)):
        return round(float(val) / 1_000_000.0, 2)
    return None


def _to_int(val: Any) -> Optional[int]:
    """Safely coerces integer metrics."""
    if val is not None and isinstance(val, (int, float)):
        return int(val)
    return None


# ==============================================================================
# Model-Level and Field-Level Semantic Metadata Registry
# ==============================================================================
# Centralized, explicit metadata documenting cross-field validation rules and
# domain-specific slot value constraints for FloatChat structured Pydantic models.
# This complements automatic Pydantic introspection for custom cross-field rules
# (e.g. @model_validator ordering checks) without altering runtime validation logic.

MODEL_CROSS_FIELD_RULES: Dict[str, List[str]] = {
    "SpatialBounds": [
        "latitude_min <= latitude_max",
        "longitude_min <= longitude_max",
    ],
    "TemporalRange": [
        "start_date <= end_date (ISO 8601 YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS[Z])",
    ],
    "PressureRange": [
        "pressure_min <= pressure_max",
    ],
}

MODEL_FIELD_SPEC_OVERRIDES: Dict[Tuple[str, str], Dict[str, Any]] = {
    ("QueryIntent", "target_entity"): {
        "type_desc": "floats | profiles | measurements | null",
    },
    ("SpatialBounds", "latitude_min"): {"constraints": ["-90 to 90"]},
    ("SpatialBounds", "latitude_max"): {"constraints": ["-90 to 90"]},
    ("SpatialBounds", "longitude_min"): {"constraints": ["-180 to 180"]},
    ("SpatialBounds", "longitude_max"): {"constraints": ["-180 to 180"]},
    ("PressureRange", "pressure_min"): {"constraints": [">= 0"]},
    ("PressureRange", "pressure_max"): {"constraints": [">= 0"]},
}


def build_compact_schema_instruction(response_model: Type[BaseModel]) -> str:
    """
    Builds a compact, semantically complete JSON schema specification for a Pydantic model.
    Strips verbose JSON Schema boilerplate ($defs, $ref, draft URLs, titles) and eliminates
    redundant whitespace while preserving all field definitions, types, enums, literals,
    constraints, defaults, nullability, and cross-field validation rules.
    """
    visited_models: Set[Type[BaseModel]] = set()
    collected_rules: List[str] = []

    def _extract_constraints(model_name: str, field_name: str, field_info: Any) -> List[str]:
        constraints: List[str] = []
        override = MODEL_FIELD_SPEC_OVERRIDES.get((model_name, field_name), {})
        if "constraints" in override:
            constraints.extend(override["constraints"])

        if field_info is not None:
            for attr in ("ge", "gt", "le", "lt", "min_length", "max_length"):
                val = getattr(field_info, attr, None)
                if val is not None:
                    constraints.append(f"{attr}: {val}")
            for m in getattr(field_info, "metadata", []):
                for attr in ("ge", "gt", "le", "lt", "min_length", "max_length"):
                    val = getattr(m, attr, None)
                    if val is not None and f"{attr}: {val}" not in constraints:
                        constraints.append(f"{attr}: {val}")
        return constraints

    def _inspect_type(annotation: Any, field_info: Any = None) -> Any:
        origin = get_origin(annotation)
        args = get_args(annotation)

        # Handle Literal
        if origin is Literal:
            return " | ".join(str(a) for a in args)

        # Handle Union / Optional
        if origin is Union:
            non_none = [a for a in args if a is not type(None)]
            is_nullable = len(non_none) < len(args)
            if len(non_none) == 1:
                inner = _inspect_type(non_none[0])
                if isinstance(inner, dict):
                    return inner
                return f"{inner} | null" if is_nullable else str(inner)
            else:
                opts = [str(_inspect_type(a)) for a in non_none]
                desc = " | ".join(opts)
                return f"{desc} | null" if is_nullable else desc

        # Handle Enum
        if isinstance(annotation, type) and issubclass(annotation, enum.Enum):
            return " | ".join(str(e.value) for e in annotation)

        # Handle List / Sequence
        if origin in (list, List):
            item_arg = args[0] if args else Any
            return [_inspect_type(item_arg)]

        # Handle nested BaseModel
        if isinstance(annotation, type) and issubclass(annotation, BaseModel):
            if annotation in visited_models:
                return f"object ({annotation.__name__})"
            visited_models.add(annotation)
            try:
                if annotation.__name__ in MODEL_CROSS_FIELD_RULES:
                    for r in MODEL_CROSS_FIELD_RULES[annotation.__name__]:
                        rule_entry = f"{annotation.__name__}: {r}"
                        if rule_entry not in collected_rules:
                            collected_rules.append(rule_entry)
                return _build_model_dict(annotation)
            finally:
                visited_models.discard(annotation)

        # Handle Primitives and common structures
        if annotation is str:
            return "string"
        if annotation is int:
            return "integer"
        if annotation is float:
            return "number"
        if annotation is bool:
            return "boolean"
        if annotation in (dict, Dict) or origin in (dict, Dict):
            return "object"

        return "any"

    def _build_model_dict(model_cls: Type[BaseModel]) -> Dict[str, Any]:
        result: Dict[str, Any] = {}

        for name, field_info in model_cls.model_fields.items():
            override = MODEL_FIELD_SPEC_OVERRIDES.get((model_cls.__name__, name), {})

            type_desc = _inspect_type(field_info.annotation, field_info)

            # Check override for type_desc
            if "type_desc" in override:
                type_desc = override["type_desc"]

            constraints = _extract_constraints(model_cls.__name__, name, field_info)
            constraint_suffix = f" [{', '.join(constraints)}]" if constraints else ""

            # Required vs optional/default semantics
            is_required = field_info.is_required()
            default_val = field_info.default
            default_factory = field_info.default_factory

            if is_required:
                req_str = "(required)"
            else:
                if default_val is not PydanticUndefined and default_val is not None:
                    if isinstance(default_val, enum.Enum):
                        d_str = str(default_val.value)
                    elif isinstance(default_val, bool):
                        d_str = "true" if default_val else "false"
                    elif isinstance(default_val, (int, float, str)):
                        d_str = str(default_val)
                    else:
                        d_str = json.dumps(default_val)
                    req_str = f"(optional, default: {d_str})"
                elif default_factory is not None:
                    try:
                        factory_val = default_factory()
                        req_str = f"(optional, default: {json.dumps(factory_val)})"
                    except Exception:
                        req_str = "(optional)"
                elif default_val is None:
                    req_str = "(optional, default: null)"
                else:
                    req_str = "(optional)"

            if isinstance(type_desc, str):
                result[name] = f"{type_desc}{constraint_suffix} {req_str}"
            elif isinstance(type_desc, list) and len(type_desc) > 0 and isinstance(type_desc[0], str):
                result[name] = [f"{type_desc[0]}{constraint_suffix} {req_str}"]
            else:
                result[name] = type_desc

        if model_cls.__name__ in MODEL_CROSS_FIELD_RULES:
            for r in MODEL_CROSS_FIELD_RULES[model_cls.__name__]:
                rule_entry = f"{model_cls.__name__}: {r}"
                if rule_entry not in collected_rules:
                    collected_rules.append(rule_entry)

        return result

    schema_dict = _build_model_dict(response_model)
    schema_json = json.dumps(schema_dict, indent=2)

    if collected_rules:
        rules_str = "\n".join(f"- {r}" for r in collected_rules)
        return f"{schema_json}\n\nValidation rules:\n{rules_str}"
    return schema_json


class OllamaProvider(BaseLLMProvider):
    """
    Ollama LLM Provider implementation for local inference.
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        timeout: Optional[float] = None,
        keep_alive: Optional[str] = None,
    ):
        config = get_config()
        self.base_url = (base_url or config.ollama_base_url).rstrip("/")
        self.model = model or config.ollama_model
        self.timeout = timeout if timeout is not None else config.ollama_timeout_seconds
        self.keep_alive = keep_alive if keep_alive is not None else config.ollama_keep_alive
        self.last_metrics: Optional[Dict[str, Any]] = None

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

        # Configurable keep-alive for the generation model
        keep_alive_val = kwargs.get("keep_alive", self.keep_alive)
        if keep_alive_val is not None and keep_alive_val != "":
            payload["keep_alive"] = keep_alive_val

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

        # Extract Ollama performance metadata (nanoseconds -> milliseconds)
        total_duration_ms = _ns_to_ms(response_data.get("total_duration"))
        load_duration_ms = _ns_to_ms(response_data.get("load_duration"))
        prompt_eval_duration_ms = _ns_to_ms(response_data.get("prompt_eval_duration"))
        eval_duration_ms = _ns_to_ms(response_data.get("eval_duration"))
        prompt_eval_count = _to_int(response_data.get("prompt_eval_count"))
        eval_count = _to_int(response_data.get("eval_count"))
        finish_reason = response_data.get("done_reason", "stop" if response_data.get("done") else None)

        self.last_metrics = {
            "total_duration_ms": total_duration_ms,
            "load_duration_ms": load_duration_ms,
            "prompt_eval_count": prompt_eval_count,
            "prompt_eval_duration_ms": prompt_eval_duration_ms,
            "eval_count": eval_count,
            "eval_duration_ms": eval_duration_ms,
            "finish_reason": finish_reason,
        }

        # Log performance telemetry without logging full prompt or secrets
        total_str = f"{total_duration_ms:.2f}ms" if total_duration_ms is not None else "N/A"
        load_str = f"{load_duration_ms:.2f}ms" if load_duration_ms is not None else "N/A"
        pe_str = f"{prompt_eval_duration_ms:.2f}ms" if prompt_eval_duration_ms is not None else "N/A"
        eval_str = f"{eval_duration_ms:.2f}ms" if eval_duration_ms is not None else "N/A"

        logger.info(
            "Ollama generate completed [model=%s, total=%s, load=%s, prompt_eval=%s (%s tokens), eval=%s (%s tokens)]",
            self.model,
            total_str,
            load_str,
            pe_str,
            prompt_eval_count if prompt_eval_count is not None else "N/A",
            eval_str,
            eval_count if eval_count is not None else "N/A",
        )

        return GenerationResult(
            text=text,
            raw_response=response_data,
            model=response_data.get("model", self.model),
            finish_reason=response_data.get("done_reason", "stop" if response_data.get("done") else None),
            total_duration_ms=total_duration_ms,
            load_duration_ms=load_duration_ms,
            prompt_eval_count=prompt_eval_count,
            prompt_eval_duration_ms=prompt_eval_duration_ms,
            eval_count=eval_count,
            eval_duration_ms=eval_duration_ms,
        )

    def _build_compact_schema_instruction(self, response_model: Type[BaseModel]) -> str:
        """
        Builds a compact, semantically complete JSON schema specification for the given model.
        """
        return build_compact_schema_instruction(response_model)

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
        # Inject compact schema guidelines into system prompt
        compact_schema = self._build_compact_schema_instruction(response_model)
        top_keys = list(response_model.model_fields.keys())
        structured_system = (
            f"{system_prompt or ''}\n\n"
            f"You MUST return ONLY a valid JSON object matching this schema with top-level keys {top_keys}:\n{compact_schema}\n"
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
            raise LLMStructuredOutputError(
                "Ollama returned empty response string for structured output.",
                raw_text=raw_text,
                finish_reason=res.finish_reason,
                response_model_name=response_model.__name__,
            )

        if res.finish_reason == "length":
            logger.warning(
                "Ollama structured output terminated early due to token limit (finish_reason='length') for model '%s'.",
                response_model.__name__,
            )
            raise LLMStructuredOutputError(
                f"Ollama structured generation for '{response_model.__name__}' terminated prematurely "
                f"due to output token limit (finish_reason='length'). Response is incomplete.",
                raw_text=raw_text,
                finish_reason=res.finish_reason,
                response_model_name=response_model.__name__,
            )

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
                f"Failed to decode JSON from Ollama response: {str(e)}. Raw text: '{raw_text[:200]}'",
                raw_text=raw_text,
                finish_reason=res.finish_reason,
                response_model_name=response_model.__name__,
            ) from e

        try:
            validated_obj = response_model.model_validate(parsed_json)
            metrics_summary = ""
            if self.last_metrics and self.last_metrics.get("total_duration_ms") is not None:
                metrics_summary = f" (total={self.last_metrics['total_duration_ms']:.2f}ms)"
            logger.info("Ollama structured output validated for '%s'%s", response_model.__name__, metrics_summary)
            return validated_obj
        except ValidationError as ve:
            raise LLMStructuredOutputError(
                f"Pydantic validation failed for model '{response_model.__name__}': {str(ve)}",
                raw_text=raw_text,
                finish_reason=res.finish_reason,
                response_model_name=response_model.__name__,
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
