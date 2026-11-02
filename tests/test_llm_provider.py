"""
tests/test_llm_provider.py

Phase 4 — LLM Provider Abstraction Test Suite.
Verifies provider-agnostic BaseLLMProvider contract, OllamaProvider HTTP client behavior,
GeminiProvider pluggable integration, provider selection factory, error exception mapping,
and Pydantic structured output validation.

All unit tests run completely offline by default using unittest.mock.
Optional live Ollama tests run only when RUN_LIVE_OLLAMA_TESTS=1 environment variable is set.
"""

import json
import os
import socket
import sys
import unittest
import urllib.error
from io import BytesIO
from unittest.mock import MagicMock, patch

from pydantic import BaseModel, Field, ValidationError

# Ensure src is in python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.agents.data_query.agent import DataQueryAgent
from src.agents.data_query.models import DataQueryResult, DataQueryStatus, SQLCandidate
from src.agents.query_understanding.agent import QueryUnderstandingAgent
from src.agents.query_understanding.models import (
    ComparisonTarget,
    PressureRange,
    QueryIntent,
    SpatialBounds,
    TemporalRange,
)
from src.agents.response.agent import ScientificResponseAgent, _LLMResponsePayload
from src.config import Config, get_config
from src.database.executor import ControlledDatabaseExecutor
from src.database.models import ExecutionStatus
from src.security.sql_validator import ValidationErrorCode, validator as sql_validator
from src.llm import (
    MODEL_CROSS_FIELD_RULES,
    MODEL_FIELD_SPEC_OVERRIDES,
    BaseLLMProvider,
    GeminiProvider,
    GenerationResult,
    LLMConfigurationError,
    LLMConnectionError,
    LLMProviderError,
    LLMResponseError,
    LLMStructuredOutputError,
    LLMTimeoutError,
    OllamaProvider,
    build_compact_schema_instruction,
    get_llm_provider,
)


# Test Pydantic model for structured output testing
class DummyWeatherReport(BaseModel):
    location: str
    temperature_c: float
    conditions: str
    is_safe: bool = Field(default=True)


class TestLLMProvider(unittest.TestCase):

    def setUp(self):
        # Patch environment variables for consistent test defaults
        self.env_patcher = patch.dict(
            os.environ,
            {
                "LLM_PROVIDER": "ollama",
                "OLLAMA_BASE_URL": "http://localhost:11434",
                "OLLAMA_MODEL": "qwen2.5:1.5b-instruct",
                "OLLAMA_TIMEOUT_SECONDS": "30.0",
                "GEMINI_MODEL": "gemini-1.5-flash",
            },
            clear=False,
        )
        self.env_patcher.start()

    def tearDown(self):
        self.env_patcher.stop()

    # ===================================================================
    # 1. Base Provider & Configuration Tests
    # ===================================================================

    def test_01_config_defaults(self):
        """Verify Config loads default Phase 4 environment variables."""
        cfg = get_config()
        self.assertEqual(cfg.llm_provider, "ollama")
        self.assertEqual(cfg.ollama_base_url, "http://localhost:11434")
        self.assertEqual(cfg.ollama_model, "qwen2.5:1.5b-instruct")
        self.assertEqual(cfg.ollama_timeout_seconds, 30.0)
        self.assertEqual(cfg.ollama_warmup_timeout_seconds, 5.0)

    def test_02_config_environment_overrides(self):
        """Verify Config reads custom model and base_url from environment."""
        with patch.dict(
            os.environ,
            {
                "OLLAMA_MODEL": "custom-model:latest",
                "OLLAMA_BASE_URL": "http://custom-host:9999",
                "OLLAMA_TIMEOUT_SECONDS": "15.5",
            },
        ):
            cfg = get_config()
            self.assertEqual(cfg.ollama_model, "custom-model:latest")
            self.assertEqual(cfg.ollama_base_url, "http://custom-host:9999")
            self.assertEqual(cfg.ollama_timeout_seconds, 15.5)

    def test_03_provider_selection_factory(self):
        """Verify get_llm_provider instantiates OllamaProvider or GeminiProvider based on config."""
        provider_ollama = get_llm_provider("ollama")
        self.assertIsInstance(provider_ollama, OllamaProvider)
        self.assertIsInstance(provider_ollama, BaseLLMProvider)
        self.assertEqual(provider_ollama.model, "qwen2.5:1.5b-instruct")

        provider_gemini = get_llm_provider("gemini")
        self.assertIsInstance(provider_gemini, GeminiProvider)
        self.assertIsInstance(provider_gemini, BaseLLMProvider)

    def test_04_invalid_provider_selection(self):
        """Verify get_llm_provider raises LLMConfigurationError for invalid provider name."""
        with self.assertRaises(LLMConfigurationError) as ctx:
            get_llm_provider("invalid_provider")
        self.assertIn("Unsupported LLM provider 'invalid_provider'", str(ctx.exception))

    # ===================================================================
    # 2. OllamaProvider Request & Response Mock Tests
    # ===================================================================

    @patch("urllib.request.urlopen")
    def test_05_ollama_generate_success(self, mock_urlopen):
        """Verify OllamaProvider constructs correct HTTP request and parses successful text completion."""
        mock_response_data = {
            "model": "qwen2.5:1.5b-instruct",
            "response": "Ocean temperature is 24.5 degrees C.",
            "done": True,
            "done_reason": "stop",
        }
        mock_cm = MagicMock()
        mock_cm.read.return_value = json.dumps(mock_response_data).encode("utf-8")
        mock_cm.__enter__.return_value = mock_cm
        mock_urlopen.return_value = mock_cm

        provider = OllamaProvider()
        res = provider.generate("What is the ocean temperature?", system_prompt="You are an oceanographer.")

        self.assertEqual(res.text, "Ocean temperature is 24.5 degrees C.")
        self.assertEqual(res.model, "qwen2.5:1.5b-instruct")
        self.assertEqual(res.finish_reason, "stop")

        # Assert correct request construction
        mock_urlopen.assert_called_once()
        req_arg = mock_urlopen.call_args[0][0]
        self.assertEqual(req_arg.full_url, "http://localhost:11434/api/generate")

        sent_payload = json.loads(req_arg.data.decode("utf-8"))
        self.assertEqual(sent_payload["model"], "qwen2.5:1.5b-instruct")
        self.assertEqual(sent_payload["prompt"], "What is the ocean temperature?")
        self.assertEqual(sent_payload["system"], "You are an oceanographer.")
        self.assertFalse(sent_payload["stream"])

    @patch("urllib.request.urlopen")
    def test_06_ollama_connection_error(self, mock_urlopen):
        """Verify URLError (connection refused) is converted to LLMConnectionError."""
        mock_urlopen.side_effect = urllib.error.URLError("[Errno 111] Connection refused")

        provider = OllamaProvider()
        with self.assertRaises(LLMConnectionError) as ctx:
            provider.generate("Test prompt")
        self.assertIn("Failed to connect to Ollama server", str(ctx.exception))

    @patch("urllib.request.urlopen")
    def test_07_ollama_timeout_error(self, mock_urlopen):
        """Verify socket.timeout or URLError timeout is converted to LLMTimeoutError."""
        mock_urlopen.side_effect = urllib.error.URLError(socket.timeout("timed out"))

        provider = OllamaProvider(timeout=5.0)
        with self.assertRaises(LLMTimeoutError) as ctx:
            provider.generate("Test prompt")
        self.assertIn("Ollama request timed out after 5.0s", str(ctx.exception))

    @patch("urllib.request.urlopen")
    def test_08_ollama_http_404_model_not_found(self, mock_urlopen):
        """Verify HTTP 404 response raises LLMResponseError mentioning model pull."""
        mock_urlopen.side_effect = urllib.error.HTTPError(
            url="http://localhost:11434/api/generate",
            code=404,
            msg="Not Found",
            hdrs={},
            fp=BytesIO(b"model not found"),
        )

        provider = OllamaProvider()
        with self.assertRaises(LLMResponseError) as ctx:
            provider.generate("Test prompt")
        self.assertIn("Model 'qwen2.5:1.5b-instruct' or endpoint", str(ctx.exception))

    @patch("urllib.request.urlopen")
    def test_09_ollama_malformed_json_response(self, mock_urlopen):
        """Verify malformed non-JSON payload from server raises LLMResponseError."""
        mock_cm = MagicMock()
        mock_cm.read.return_value = b"<html>502 Bad Gateway</html>"
        mock_cm.__enter__.return_value = mock_cm
        mock_urlopen.return_value = mock_cm

        provider = OllamaProvider()
        with self.assertRaises(LLMResponseError) as ctx:
            provider.generate("Test prompt")
        self.assertIn("Malformed non-JSON response", str(ctx.exception))

    # ===================================================================
    # 3. Structured Output & Pydantic Validation Tests
    # ===================================================================

    @patch("urllib.request.urlopen")
    def test_10_generate_structured_success(self, mock_urlopen):
        """Verify generate_structured parses valid JSON output into requested Pydantic model."""
        valid_weather_data = {
            "location": "Indian Ocean",
            "temperature_c": 28.4,
            "conditions": "Sunny",
            "is_safe": True,
        }
        mock_response = {
            "model": "qwen2.5:1.5b-instruct",
            "response": json.dumps(valid_weather_data),
            "done": True,
        }
        mock_cm = MagicMock()
        mock_cm.read.return_value = json.dumps(mock_response).encode("utf-8")
        mock_cm.__enter__.return_value = mock_cm
        mock_urlopen.return_value = mock_cm

        provider = OllamaProvider()
        report = provider.generate_structured("Get weather report", response_model=DummyWeatherReport)

        self.assertIsInstance(report, DummyWeatherReport)
        self.assertEqual(report.location, "Indian Ocean")
        self.assertEqual(report.temperature_c, 28.4)
        self.assertEqual(report.conditions, "Sunny")
        self.assertTrue(report.is_safe)

    @patch("urllib.request.urlopen")
    def test_11_generate_structured_invalid_json_text(self, mock_urlopen):
        """Verify invalid JSON text returned raises LLMStructuredOutputError."""
        mock_response = {
            "model": "qwen2.5:1.5b-instruct",
            "response": "Here is the weather: location=Indian Ocean, temp=28.4",
            "done": True,
        }
        mock_cm = MagicMock()
        mock_cm.read.return_value = json.dumps(mock_response).encode("utf-8")
        mock_cm.__enter__.return_value = mock_cm
        mock_urlopen.return_value = mock_cm

        provider = OllamaProvider()
        with self.assertRaises(LLMStructuredOutputError) as ctx:
            provider.generate_structured("Get weather", response_model=DummyWeatherReport)
        self.assertIn("Failed to decode JSON", str(ctx.exception))

    @patch("urllib.request.urlopen")
    def test_12_generate_structured_validation_mismatch(self, mock_urlopen):
        """Verify JSON with invalid field types raises LLMStructuredOutputError."""
        invalid_weather_data = {
            "location": "Indian Ocean",
            "temperature_c": "NOT_A_FLOAT",
            "conditions": "Sunny",
        }
        mock_response = {
            "model": "qwen2.5:1.5b-instruct",
            "response": json.dumps(invalid_weather_data),
            "done": True,
        }
        mock_cm = MagicMock()
        mock_cm.read.return_value = json.dumps(mock_response).encode("utf-8")
        mock_cm.__enter__.return_value = mock_cm
        mock_urlopen.return_value = mock_cm

        provider = OllamaProvider()
        with self.assertRaises(LLMStructuredOutputError) as ctx:
            provider.generate_structured("Get weather", response_model=DummyWeatherReport)
        self.assertIn("Pydantic validation failed for model 'DummyWeatherReport'", str(ctx.exception))

    # ===================================================================
    # 4. GeminiProvider Pluggable Tests
    # ===================================================================

    def test_13_gemini_lazy_initialization_without_key(self):
        """Verify GeminiProvider can be instantiated without API key without raising exception on import/init."""
        provider = GeminiProvider(api_key=None)
        self.assertIsInstance(provider, BaseLLMProvider)
        self.assertEqual(provider.model, "gemini-1.5-flash")

    def test_14_gemini_missing_api_key_on_generate(self):
        """Verify calling generate() on GeminiProvider without API key raises LLMConfigurationError."""
        provider = GeminiProvider(api_key="")
        with self.assertRaises(LLMConfigurationError) as ctx:
            provider.generate("Test prompt")
        self.assertIn("Gemini API key is required", str(ctx.exception))

    # ===================================================================
    # 5. Optional Live Ollama Integration Test
    # ===================================================================

    @unittest.skipUnless(
        os.getenv("RUN_LIVE_OLLAMA_TESTS") == "1",
        "Live Ollama integration test skipped by default. Set RUN_LIVE_OLLAMA_TESTS=1 to execute.",
    )
    def test_15_live_ollama_qwen_generation(self):
        """Live integration test against running local Ollama server with qwen2.5:1.5b-instruct."""
        provider = OllamaProvider()
        res = provider.generate("Say 'FloatChat Live Test Passed' in exactly 4 words.")
        self.assertTrue(len(res.text.strip()) > 0)
        self.assertIn("FloatChat", res.text)


    @patch("urllib.request.urlopen")
    def test_16_ollama_metadata_extraction_when_present(self, mock_urlopen):
        """Verify OllamaProvider extracts nanosecond metadata and converts to ms correctly."""
        mock_response_data = {
            "model": "qwen2.5:1.5b-instruct",
            "response": "Ocean salinity is 35 PSU.",
            "done": True,
            "done_reason": "stop",
            "total_duration": 5000000000,       # 5.0s -> 5000.0ms
            "load_duration": 1200000000,        # 1.2s -> 1200.0ms
            "prompt_eval_count": 45,
            "prompt_eval_duration": 300000000,  # 0.3s -> 300.0ms
            "eval_count": 12,
            "eval_duration": 400000000,         # 0.4s -> 400.0ms
        }
        mock_cm = MagicMock()
        mock_cm.read.return_value = json.dumps(mock_response_data).encode("utf-8")
        mock_cm.__enter__.return_value = mock_cm
        mock_urlopen.return_value = mock_cm

        provider = OllamaProvider()
        res = provider.generate("What is the salinity?")

        self.assertEqual(res.total_duration_ms, 5000.0)
        self.assertEqual(res.load_duration_ms, 1200.0)
        self.assertEqual(res.prompt_eval_count, 45)
        self.assertEqual(res.prompt_eval_duration_ms, 300.0)
        self.assertEqual(res.eval_count, 12)
        self.assertEqual(res.eval_duration_ms, 400.0)
        self.assertIsNotNone(provider.last_metrics)
        self.assertEqual(provider.last_metrics["eval_count"], 12)

    @patch("urllib.request.urlopen")
    def test_17_ollama_metadata_extraction_when_missing(self, mock_urlopen):
        """Verify OllamaProvider safely handles responses without timing metadata."""
        mock_response_data = {
            "model": "qwen2.5:1.5b-instruct",
            "response": "Minimal response without durations.",
            "done": True,
        }
        mock_cm = MagicMock()
        mock_cm.read.return_value = json.dumps(mock_response_data).encode("utf-8")
        mock_cm.__enter__.return_value = mock_cm
        mock_urlopen.return_value = mock_cm

        provider = OllamaProvider()
        res = provider.generate("Test prompt")

        self.assertIsNone(res.total_duration_ms)
        self.assertIsNone(res.load_duration_ms)
        self.assertIsNone(res.prompt_eval_count)
        self.assertIsNone(res.eval_count)

    @patch("urllib.request.urlopen")
    def test_18_ollama_keep_alive_configuration(self, mock_urlopen):
        """Verify keep_alive parameter is passed in HTTP payload."""
        mock_response_data = {"model": "qwen2.5:1.5b-instruct", "response": "OK", "done": True}
        mock_cm = MagicMock()
        mock_cm.read.return_value = json.dumps(mock_response_data).encode("utf-8")
        mock_cm.__enter__.return_value = mock_cm
        mock_urlopen.return_value = mock_cm

        # Default keep_alive from config (30m)
        provider = OllamaProvider()
        provider.generate("Test")
        req_arg = mock_urlopen.call_args[0][0]
        sent_payload = json.loads(req_arg.data.decode("utf-8"))
        self.assertEqual(sent_payload.get("keep_alive"), "30m")

        # Custom keep_alive via constructor
        mock_urlopen.reset_mock()
        custom_provider = OllamaProvider(keep_alive="1h")
        custom_provider.generate("Test")
        req_arg = mock_urlopen.call_args[0][0]
        sent_payload = json.loads(req_arg.data.decode("utf-8"))
        self.assertEqual(sent_payload.get("keep_alive"), "1h")

        # Custom keep_alive via kwargs override
        mock_urlopen.reset_mock()
        provider.generate("Test", keep_alive="15m")
        req_arg = mock_urlopen.call_args[0][0]
        sent_payload = json.loads(req_arg.data.decode("utf-8"))
        self.assertEqual(sent_payload.get("keep_alive"), "15m")

    # ===================================================================
    # 6. Stage 2B.1.3 Metadata Consistency & Automated Parity Tests
    # ===================================================================

    MODEL_REGISTRY = {
        "QueryIntent": QueryIntent,
        "SpatialBounds": SpatialBounds,
        "TemporalRange": TemporalRange,
        "PressureRange": PressureRange,
        "ComparisonTarget": ComparisonTarget,
        "SQLCandidate": SQLCandidate,
        "_LLMResponsePayload": _LLMResponsePayload,
    }

    RULE_TO_VALIDATOR_MAP = {
        ("SpatialBounds", "latitude_min <= latitude_max"): ("SpatialBounds", "validate_bounds"),
        ("SpatialBounds", "longitude_min <= longitude_max"): ("SpatialBounds", "validate_bounds"),
        ("TemporalRange", "start_date <= end_date (ISO 8601 YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS[Z])"): ("TemporalRange", "validate_range"),
        ("PressureRange", "pressure_min <= pressure_max"): ("PressureRange", "validate_pressure_range"),
    }

    def test_19_compact_schema_structure_completeness(self):
        """Verify build_compact_schema_instruction generates complete compact schemas for all core models."""
        # 1. QueryIntent
        qi_full = build_compact_schema_instruction(QueryIntent)
        qi_json_part = qi_full.split("\n\nValidation rules:\n")[0]
        parsed_qi_schema = json.loads(qi_json_part)

        # All 14 actual model fields must be present
        expected_fields = [
            "intent_type",
            "intent_category",
            "physical_variables",
            "aggregation_operation",
            "spatial_bounds",
            "temporal_range",
            "pressure_range",
            "wmo_ids",
            "comparison_target",
            "target_entity",
            "is_supported",
            "unsupported_reason",
            "needs_clarification",
            "clarification_question",
        ]
        for field_name in expected_fields:
            self.assertIn(field_name, parsed_qi_schema, f"Field '{field_name}' must be present in QueryIntent schema")

        # Nonexistent confidence_score must NOT appear
        self.assertNotIn("confidence_score", parsed_qi_schema)
        self.assertNotIn("confidence_score", qi_full)

        # Nested structures must contain expected child fields
        self.assertIn("latitude_min", parsed_qi_schema["spatial_bounds"])
        self.assertIn("latitude_max", parsed_qi_schema["spatial_bounds"])
        self.assertIn("longitude_min", parsed_qi_schema["spatial_bounds"])
        self.assertIn("longitude_max", parsed_qi_schema["spatial_bounds"])

        self.assertIn("start_date", parsed_qi_schema["temporal_range"])
        self.assertIn("end_date", parsed_qi_schema["temporal_range"])

        self.assertIn("pressure_min", parsed_qi_schema["pressure_range"])
        self.assertIn("pressure_max", parsed_qi_schema["pressure_range"])
        self.assertIn("is_depth_requested", parsed_qi_schema["pressure_range"])

        self.assertIn("is_comparison", parsed_qi_schema["comparison_target"])
        self.assertIn("comparison_targets", parsed_qi_schema["comparison_target"])
        self.assertIn("comparison_aspect", parsed_qi_schema["comparison_target"])

        # Enum and Literal values must be preserved exactly
        self.assertIn("KNOWLEDGE_ONLY", parsed_qi_schema["intent_type"])
        self.assertIn("DATA_ONLY", parsed_qi_schema["intent_type"])
        self.assertIn("HYBRID", parsed_qi_schema["intent_type"])
        self.assertIn("TEMP", parsed_qi_schema["physical_variables"][0])
        self.assertIn("PSAL", parsed_qi_schema["physical_variables"][0])
        self.assertIn("PRES", parsed_qi_schema["physical_variables"][0])
        self.assertIn("average", parsed_qi_schema["aggregation_operation"])
        self.assertIn("minimum", parsed_qi_schema["aggregation_operation"])
        self.assertIn("maximum", parsed_qi_schema["aggregation_operation"])
        self.assertIn("count", parsed_qi_schema["aggregation_operation"])
        self.assertIn("sum", parsed_qi_schema["aggregation_operation"])

        # target_entity exact allowed values
        self.assertIn("floats", parsed_qi_schema["target_entity"])
        self.assertIn("profiles", parsed_qi_schema["target_entity"])
        self.assertIn("measurements", parsed_qi_schema["target_entity"])
        self.assertIn("null", parsed_qi_schema["target_entity"])

        # Required, optional, and default semantics
        self.assertIn("optional, default: DATA_ONLY", parsed_qi_schema["intent_type"])
        self.assertIn("optional, default: filtering", parsed_qi_schema["intent_category"])
        self.assertIn("optional, default: true", parsed_qi_schema["is_supported"])
        self.assertIn("optional, default: false", parsed_qi_schema["needs_clarification"])
        self.assertIn("optional, default: []", parsed_qi_schema["physical_variables"][0])
        self.assertIn("optional, default: []", parsed_qi_schema["wmo_ids"][0])

        # Numeric constraints
        self.assertIn("-90 to 90", parsed_qi_schema["spatial_bounds"]["latitude_min"])
        self.assertIn("-180 to 180", parsed_qi_schema["spatial_bounds"]["longitude_min"])
        self.assertIn(">= 0", parsed_qi_schema["pressure_range"]["pressure_min"])

        # Cross-field validation rules
        self.assertIn("Validation rules:", qi_full)
        self.assertIn("latitude_min <= latitude_max", qi_full)
        self.assertIn("longitude_min <= longitude_max", qi_full)
        self.assertIn("start_date <= end_date", qi_full)
        self.assertIn("pressure_min <= pressure_max", qi_full)

        # 2. SQLCandidate
        sql_schema = build_compact_schema_instruction(SQLCandidate)
        parsed_sql_schema = json.loads(sql_schema)
        self.assertIn("sql", parsed_sql_schema)
        self.assertIn("explanation", parsed_sql_schema)
        self.assertIn("string (required)", parsed_sql_schema["sql"])
        self.assertIn("optional, default: null", parsed_sql_schema["explanation"])

        # 3. _LLMResponsePayload
        resp_schema = build_compact_schema_instruction(_LLMResponsePayload)
        parsed_resp_schema = json.loads(resp_schema)
        self.assertIn("answer", parsed_resp_schema)
        self.assertIn("citations", parsed_resp_schema)
        self.assertIn("string (required)", parsed_resp_schema["answer"])
        self.assertIsInstance(parsed_resp_schema["citations"], list)

    def test_20_compact_schema_validation_invariance(self):
        """Verify payloads adhering to compact schema pass validation, and invalid ones fail."""
        # Representative valid QueryIntent payload
        valid_intent_payload = {
            "intent_type": "DATA_ONLY",
            "intent_category": "filtering",
            "physical_variables": ["TEMP", "PSAL"],
            "aggregation_operation": "average",
            "spatial_bounds": {
                "latitude_min": 10.0,
                "latitude_max": 20.0,
                "longitude_min": 60.0,
                "longitude_max": 70.0,
            },
            "temporal_range": {
                "start_date": "2023-01-01",
                "end_date": "2023-12-31",
            },
            "pressure_range": {
                "pressure_min": 0.0,
                "pressure_max": 500.0,
                "is_depth_requested": False,
            },
            "wmo_ids": ["2901550"],
            "comparison_target": None,
            "target_entity": "profiles",
            "is_supported": True,
            "needs_clarification": False,
            "clarification_question": None,
            "unsupported_reason": None,
        }
        validated_qi = QueryIntent.model_validate(valid_intent_payload)
        self.assertEqual(validated_qi.intent_type.value, "DATA_ONLY")
        self.assertEqual(validated_qi.spatial_bounds.latitude_min, 10.0)

        # Invalid QueryIntent payload (illegal enum)
        invalid_intent_payload = dict(valid_intent_payload)
        invalid_intent_payload["intent_type"] = "INVALID_TYPE_XYZ"
        with self.assertRaises(ValidationError):
            QueryIntent.model_validate(invalid_intent_payload)

        # Cross-field validator enforcement matches documented rules
        with self.assertRaises(ValueError):
            SpatialBounds(latitude_min=25.0, latitude_max=10.0)
        with self.assertRaises(ValueError):
            SpatialBounds(longitude_min=90.0, longitude_max=40.0)
        with self.assertRaises(ValueError):
            TemporalRange(start_date="2024-01-01", end_date="2022-01-01")
        with self.assertRaises(ValueError):
            PressureRange(pressure_min=300.0, pressure_max=100.0)

        # Representative valid SQLCandidate payload
        valid_sql_payload = {
            "sql": "SELECT platform_number FROM argo_floats LIMIT 10;",
            "explanation": "Selects 10 floats.",
        }
        validated_sql = SQLCandidate.model_validate(valid_sql_payload)
        self.assertEqual(validated_sql.sql, "SELECT platform_number FROM argo_floats LIMIT 10;")

        # Invalid SQLCandidate payload (missing required field)
        with self.assertRaises(ValidationError):
            SQLCandidate.model_validate({"explanation": "Missing sql key"})

        # Representative valid _LLMResponsePayload
        valid_resp_payload = {
            "answer": "The Indian Ocean exhibits high salinity.",
            "citations": [{"title": "Argo Manual", "section": "3.1"}],
        }
        validated_resp = _LLMResponsePayload.model_validate(valid_resp_payload)
        self.assertEqual(validated_resp.answer, "The Indian Ocean exhibits high salinity.")
        self.assertEqual(len(validated_resp.citations), 1)

    def test_21_compact_schema_prompt_size_regression(self):
        """Verify compact schemas achieve substantial token/character reduction versus verbose model_json_schema()."""
        # QueryIntent (verbose: 9,240 chars; compact: ~1,970 chars, > 78% reduction)
        verbose_qi = json.dumps(QueryIntent.model_json_schema(), indent=2)
        compact_qi = build_compact_schema_instruction(QueryIntent)
        self.assertLess(len(compact_qi), 2100, f"QueryIntent compact schema should be < 2100 chars (was {len(compact_qi)})")
        self.assertLess(
            len(compact_qi),
            len(verbose_qi) * 0.30,
            f"QueryIntent compact schema ({len(compact_qi)}) should be < 30% of verbose schema ({len(verbose_qi)})",
        )

        # SQLCandidate
        verbose_sql = json.dumps(SQLCandidate.model_json_schema(), indent=2)
        compact_sql = build_compact_schema_instruction(SQLCandidate)
        self.assertLess(len(compact_sql), 150, f"SQLCandidate compact schema should be < 150 chars (was {len(compact_sql)})")
        self.assertLess(len(compact_sql), len(verbose_sql) * 0.25)

        # _LLMResponsePayload
        verbose_resp = json.dumps(_LLMResponsePayload.model_json_schema(), indent=2)
        compact_resp = build_compact_schema_instruction(_LLMResponsePayload)
        self.assertLess(len(compact_resp), 150, f"_LLMResponsePayload compact schema should be < 150 chars (was {len(compact_resp)})")
        self.assertLess(len(compact_resp), len(verbose_resp) * 0.25)

    @patch("urllib.request.urlopen")
    def test_22_provider_generate_structured_uses_compact_schema(self, mock_urlopen):
        """Verify OllamaProvider.generate_structured injects compact schema instruction instead of verbose schema."""
        mock_response = {
            "model": "qwen2.5:1.5b-instruct",
            "response": json.dumps({
                "intent_type": "DATA_ONLY",
                "intent_category": "filtering",
                "physical_variables": ["TEMP"],
                "is_supported": True,
                "needs_clarification": False,
            }),
            "done": True,
        }
        mock_cm = MagicMock()
        mock_cm.read.return_value = json.dumps(mock_response).encode("utf-8")
        mock_cm.__enter__.return_value = mock_cm
        mock_urlopen.return_value = mock_cm

        provider = OllamaProvider()
        result = provider.generate_structured("Get temperature data", response_model=QueryIntent)

        self.assertIsInstance(result, QueryIntent)
        self.assertEqual(result.intent_type.value, "DATA_ONLY")

        # Inspect sent payload
        req_arg = mock_urlopen.call_args[0][0]
        sent_payload = json.loads(req_arg.data.decode("utf-8"))
        sent_system = sent_payload.get("system", "")

        # System prompt must contain compact schema, NOT the verbose $defs/draft schema
        self.assertNotIn("$defs", sent_system)
        self.assertNotIn("draft/2020-12", sent_system)
        self.assertIn('"intent_type"', sent_system)
        self.assertIn("KNOWLEDGE_ONLY", sent_system)
        self.assertIn("Validation rules:", sent_system)
        self.assertLess(len(sent_system), 3500, f"System prompt with compact schema should be compact (was {len(sent_system)})")

    def test_23_metadata_field_override_integrity(self):
        """Verify every (model_name, field_name) in MODEL_FIELD_SPEC_OVERRIDES resolves to an actual model field."""
        for (model_name, field_name) in MODEL_FIELD_SPEC_OVERRIDES.keys():
            self.assertIn(model_name, self.MODEL_REGISTRY, f"Model '{model_name}' must exist in MODEL_REGISTRY")
            model_cls = self.MODEL_REGISTRY[model_name]
            self.assertIn(
                field_name,
                model_cls.model_fields,
                f"MODEL_FIELD_SPEC_OVERRIDES references nonexistent field '{field_name}' on model '{model_name}'",
            )

    def test_24_metadata_field_semantics_consistency(self):
        """Verify field overrides accurately reflect model definitions or documented domain constraints."""
        for (model_name, field_name), override in MODEL_FIELD_SPEC_OVERRIDES.items():
            model_cls = self.MODEL_REGISTRY[model_name]
            field_info = model_cls.model_fields[field_name]

            # If constraints are specified, verify they are grounded in the field description
            if "constraints" in override:
                desc = field_info.description or ""
                for constraint in override["constraints"]:
                    self.assertTrue(
                        constraint in desc or (">=" in constraint and ">= 0" in desc),
                        f"Constraint '{constraint}' for {model_name}.{field_name} must be documented in model description",
                    )

            # If type_desc is specified, verify it agrees with field description
            if "type_desc" in override:
                desc = field_info.description or ""
                self.assertTrue(
                    "floats" in desc and "profiles" in desc and "measurements" in desc,
                    f"Override type_desc for {model_name}.{field_name} must agree with model slot values",
                )

    def test_25_metadata_cross_field_rule_integrity(self):
        """Verify every rule in MODEL_CROSS_FIELD_RULES corresponds to an actual validator method on the model."""
        for model_name, rules in MODEL_CROSS_FIELD_RULES.items():
            self.assertIn(model_name, self.MODEL_REGISTRY, f"Model '{model_name}' must exist in MODEL_REGISTRY")
            model_cls = self.MODEL_REGISTRY[model_name]

            for rule in rules:
                mapping_key = (model_name, rule)
                self.assertIn(
                    mapping_key,
                    self.RULE_TO_VALIDATOR_MAP,
                    f"Rule '{rule}' on model '{model_name}' must be mapped in RULE_TO_VALIDATOR_MAP",
                )
                target_model_name, validator_method_name = self.RULE_TO_VALIDATOR_MAP[mapping_key]
                self.assertEqual(target_model_name, model_name)

                # Ensure validator method exists and is callable
                self.assertTrue(
                    hasattr(model_cls, validator_method_name),
                    f"Model '{model_name}' must have validator method '{validator_method_name}'",
                )
                validator_fn = getattr(model_cls, validator_method_name)
                self.assertTrue(
                    callable(validator_fn),
                    f"Validator attribute '{validator_method_name}' on '{model_name}' must be callable",
                )

    def test_26_temporal_compatibility(self):
        """Verify compact schema instruction communicates both date and timestamp support for TemporalRange."""
        qi_full = build_compact_schema_instruction(QueryIntent)
        self.assertIn("YYYY-MM-DD", qi_full)
        self.assertIn("YYYY-MM-DDTHH:MM:SS", qi_full)
        self.assertIn("start_date <= end_date", qi_full)

        # Verify TemporalRange accepts calendar dates
        date_range = TemporalRange(start_date="2023-01-01", end_date="2023-12-31")
        self.assertEqual(date_range.start_date, "2023-01-01")
        self.assertEqual(date_range.end_date, "2023-12-31")

        # Verify TemporalRange accepts full ISO 8601 timestamps with Z
        timestamp_range = TemporalRange(
            start_date="2023-01-01T00:00:00Z",
            end_date="2023-01-01T12:00:00Z",
        )
        self.assertEqual(timestamp_range.start_date, "2023-01-01T00:00:00Z")
        self.assertEqual(timestamp_range.end_date, "2023-01-01T12:00:00Z")

    # ===================================================================
    # 7. Stage 2B.2B: Agent-Specific Bounded Generation Tests
    # ===================================================================

    def test_27_token_limit_config_defaults(self):
        """1. Verify default configuration values for agent-specific token limits."""
        cfg = get_config()
        self.assertEqual(cfg.ollama_num_predict_query_understanding, 300)
        self.assertEqual(cfg.ollama_num_predict_data_query, 384)
        self.assertEqual(cfg.ollama_num_predict_response, 512)

    def test_28_token_limit_config_env_overrides(self):
        """2. Verify environment variable overrides for agent token limits."""
        with patch.dict(
            os.environ,
            {
                "OLLAMA_NUM_PREDICT_QUERY_UNDERSTANDING": "256",
                "OLLAMA_NUM_PREDICT_DATA_QUERY": "400",
                "OLLAMA_NUM_PREDICT_RESPONSE": "768",
            },
        ):
            cfg = Config()
            self.assertEqual(cfg.ollama_num_predict_query_understanding, 256)
            self.assertEqual(cfg.ollama_num_predict_data_query, 400)
            self.assertEqual(cfg.ollama_num_predict_response, 768)

    def test_29_token_limit_config_rejection(self):
        """3. Verify rejection of invalid token limits (negative, zero, non-integer)."""
        with self.assertRaises(ValueError):
            Config(ollama_num_predict_query_understanding=-1)

        with self.assertRaises(ValueError):
            Config(ollama_num_predict_data_query=0)

        with patch.dict(os.environ, {"OLLAMA_NUM_PREDICT_RESPONSE": "invalid_int"}):
            with self.assertRaises(ValueError):
                Config()

        with patch.dict(os.environ, {"OLLAMA_NUM_PREDICT_QUERY_UNDERSTANDING": "-50"}):
            with self.assertRaises(ValueError):
                Config()

    def test_30_query_understanding_forwards_token_limit(self):
        """4. Verify QueryUnderstandingAgent forwards its configured limit to generate_structured."""
        mock_provider = MagicMock(spec=BaseLLMProvider)
        mock_intent = QueryIntent(
            query="test",
            target_entity="profiles",
            is_supported=True,
        )
        mock_provider.generate_structured.return_value = mock_intent

        custom_cfg = Config(ollama_num_predict_query_understanding=250)
        agent = QueryUnderstandingAgent(llm_provider=mock_provider, config=custom_cfg)

        res = agent.analyze("Show all profiles in the Arabian Sea")
        self.assertEqual(res, mock_intent)
        mock_provider.generate_structured.assert_called_once()
        _, kwargs = mock_provider.generate_structured.call_args
        self.assertEqual(kwargs.get("max_tokens"), 250)

    def test_31_data_query_forwards_token_limit(self):
        """5. Verify DataQueryAgent forwards its configured limit to generate_structured/generate."""
        mock_provider = MagicMock(spec=BaseLLMProvider)
        mock_candidate = SQLCandidate(
            sql="SELECT * FROM argo_profiles LIMIT 10;",
            explanation="Test candidate",
        )
        mock_provider.generate_structured.return_value = mock_candidate

        custom_cfg = Config(ollama_num_predict_data_query=320)
        agent = DataQueryAgent(llm_provider=mock_provider, config=custom_cfg)

        intent = QueryIntent(
            query="profiles in 2024",
            physical_variables=["TEMP"],
            target_entity="profiles",
            is_supported=True,
        )
        res = agent.generate_sql(intent)
        self.assertTrue(res.is_executable)
        mock_provider.generate_structured.assert_called_once()
        _, kwargs = mock_provider.generate_structured.call_args
        self.assertEqual(kwargs.get("max_tokens"), 320)

    def test_32_data_query_retry_applies_same_limit(self):
        """6. Verify DataQueryAgent applies the same limit to its bounded retry."""
        mock_provider = MagicMock(spec=BaseLLMProvider)
        # Attempt 1 returns invalid SQL, Attempt 2 returns valid SQL
        invalid_candidate = SQLCandidate(sql="INVALID SYNTAX FROM table", explanation="Bad")
        valid_candidate = SQLCandidate(sql="SELECT * FROM argo_profiles LIMIT 10;", explanation="Good")
        mock_provider.generate_structured.side_effect = [invalid_candidate, valid_candidate]

        custom_cfg = Config(ollama_num_predict_data_query=410)
        agent = DataQueryAgent(llm_provider=mock_provider, enable_retry=True, config=custom_cfg)

        intent = QueryIntent(
            query="profiles in 2024",
            physical_variables=["TEMP"],
            target_entity="profiles",
            is_supported=True,
        )
        res = agent.generate_sql(intent)
        self.assertTrue(res.is_executable)
        self.assertEqual(res.retry_count, 1)
        self.assertEqual(mock_provider.generate_structured.call_count, 2)
        # Verify both calls used max_tokens=410
        for call in mock_provider.generate_structured.call_args_list:
            _, kwargs = call
            self.assertEqual(kwargs.get("max_tokens"), 410)

    def test_33_scientific_response_forwards_token_limit(self):
        """7. Verify ScientificResponseAgent forwards its configured limit."""
        mock_provider = MagicMock(spec=BaseLLMProvider)
        mock_payload = _LLMResponsePayload(
            answer="Ocean stratification describes layered density structures.",
            citations=[],
        )
        mock_provider.generate_structured.return_value = mock_payload

        custom_cfg = Config(ollama_num_predict_response=600)
        agent = ScientificResponseAgent(llm_provider=mock_provider, config=custom_cfg)

        payload, raw, err = agent._invoke_llm("test prompt")
        self.assertIsNotNone(payload)
        self.assertIsNone(err)
        mock_provider.generate_structured.assert_called_once()
        _, kwargs = mock_provider.generate_structured.call_args
        self.assertEqual(kwargs.get("max_tokens"), 600)

    def test_34_ollama_provider_transmits_num_predict(self):
        """8. Verify OllamaProvider transmits options.num_predict in HTTP POST payload."""
        provider = OllamaProvider(base_url="http://localhost:11434", model="qwen2.5:1.5b-instruct")

        captured_payloads = []
        def fake_post_generate(payload):
            captured_payloads.append(payload)
            return {
                "response": "Hello world",
                "done": True,
                "done_reason": "stop",
                "eval_count": 2,
            }

        with patch.object(provider, "_post_generate", side_effect=fake_post_generate):
            res = provider.generate("Test prompt", max_tokens=384)
            self.assertEqual(res.text, "Hello world")
            self.assertEqual(len(captured_payloads), 1)
            options = captured_payloads[0].get("options", {})
            self.assertEqual(options.get("num_predict"), 384)

    def test_35_output_limit_termination_and_incomplete_json(self):
        """9. Verify output-limit termination (finish_reason='length') and incomplete JSON handling."""
        provider = OllamaProvider(base_url="http://localhost:11434", model="qwen2.5:1.5b-instruct")

        # Scenario A: finish_reason='length' explicitly raises LLMStructuredOutputError
        mock_res_length = GenerationResult(
            text='{"location": "Arabian Sea", "temperature_c": 28.5, "conditions": "Clear"}',
            finish_reason="length",
        )
        with patch.object(provider, "generate", return_value=mock_res_length):
            with self.assertRaises(LLMStructuredOutputError) as ctx:
                provider.generate_structured("Weather?", DummyWeatherReport)
            self.assertIn("finish_reason='length'", str(ctx.exception))

        # Scenario B: Incomplete/truncated JSON string fails JSON decoding
        mock_res_truncated = GenerationResult(
            text='{"location": "Arabian Sea", "temperature_c": 28.5',
            finish_reason="stop",
        )
        with patch.object(provider, "generate", return_value=mock_res_truncated):
            with self.assertRaises(LLMStructuredOutputError) as ctx:
                provider.generate_structured("Weather?", DummyWeatherReport)
            self.assertIn("Failed to decode JSON", str(ctx.exception))

    def test_36_truncated_sql_rejected_before_execution(self):
        """10. Verify truncated SQL is rejected by AST validator and blocked before database execution."""
        # 1. Truncated SQL fails AST parsing in validator
        truncated_sql = "SELECT * FROM argo_profiles WHERE profile_time >="
        val_res = sql_validator.validate(truncated_sql)
        self.assertFalse(val_res.valid)
        self.assertEqual(val_res.error_code, ValidationErrorCode.PARSE_ERROR)

        # 2. ControlledDatabaseExecutor rejects execution of unvalidated result
        mock_executor = ControlledDatabaseExecutor()
        dqr_failed = DataQueryResult(
            status=DataQueryStatus.VALIDATION_FAILED,
            sql=truncated_sql,
            error_message="Truncated SQL",
        )
        exec_res = mock_executor.execute(dqr_failed)
        self.assertFalse(exec_res.is_success)
        self.assertEqual(exec_res.status, ExecutionStatus.REJECTED_INPUT)

    def test_37_structured_output_error_preserves_attributes(self):
        """11. Verify LLMStructuredOutputError preserves raw_text, finish_reason, and response_model_name."""
        provider = OllamaProvider(base_url="http://mock:11434")

        # Mock length termination
        mock_response = GenerationResult(
            text='{"answer": "Incomplete text',
            finish_reason="length",
            model="qwen2.5:1.5b-instruct",
        )
        with patch.object(provider, "generate", return_value=mock_response):
            with self.assertRaises(LLMStructuredOutputError) as ctx:
                provider.generate_structured(
                    prompt="test",
                    response_model=DummyWeatherReport,
                )
            err = ctx.exception
            self.assertEqual(err.finish_reason, "length")
            self.assertEqual(err.raw_text, '{"answer": "Incomplete text')
            self.assertEqual(err.response_model_name, "DummyWeatherReport")


if __name__ == "__main__":
    unittest.main()
