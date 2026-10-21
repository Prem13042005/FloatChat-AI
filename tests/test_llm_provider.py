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

from pydantic import BaseModel, Field

# Ensure src is in python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.config import Config, get_config
from src.llm import (
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


if __name__ == "__main__":
    unittest.main()
