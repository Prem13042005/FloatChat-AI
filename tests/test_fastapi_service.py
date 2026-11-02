"""
tests/test_fastapi_service.py

Phase 10 — FastAPI AI Service Test Suite.
Verifies:
- Liveness probe (GET /health)
- Deep readiness probe (GET /ready) with connected and degraded database states
- REST API chat endpoint (POST /api/v1/chat) for Knowledge-Only, Data-Only, and Hybrid flows
- Query alias endpoint (POST /api/v1/query)
- Input validation: empty queries, whitespace, oversized queries (>2000 chars)
- Error handling: timeouts (504 Gateway Timeout), unhandled exceptions (500 Internal Server Error)
- CORS header configuration for allowed origins
- Sanitized error responses without stack traces or credential leaks

All unit tests run isolated using FastAPI's TestClient and unittest.mock.
"""

import os
import sys
import unittest
from unittest.mock import MagicMock, patch

from fastapi import status
from fastapi.testclient import TestClient

# Ensure src is in python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.agents.response.models import (
    ChartType,
    Citation,
    DataSummary,
    ResponseStatus,
    ScientificResponse,
    VisualizationSpec,
)
from src.api.main import create_app
from src.config import Config
from src.database.models import DatabaseExecutionResult, ExecutionStatus
from src.llm import GenerationResult
from src.orchestration import FloatChatOrchestrator, FloatChatState


class TestFastAPIService(unittest.TestCase):

    def setUp(self):
        self.internal_secret = "test_shared_secret_for_unit_tests"
        self.config = Config(
            postgres_port=5432,
            request_timeout_seconds=5.0,
            max_query_length=2000,
            cors_origins="http://localhost:3000,http://localhost:8080",
            internal_secret=self.internal_secret,
        )
        self.app = create_app(config=self.config)
        self.mock_orchestrator = MagicMock(spec=FloatChatOrchestrator)
        self.app.state.orchestrator = self.mock_orchestrator
        self.app.state.config = self.config
        self.client = TestClient(self.app, headers={"X-Internal-Secret": self.internal_secret})

    # ===================================================================
    # 1. Health & Readiness Probe Tests
    # ===================================================================

    def test_01_health_endpoint(self):
        """Verify GET /health returns 200 with healthy status and version."""
        res = self.client.get("/health")
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        data = res.json()
        self.assertEqual(data["status"], "healthy")
        self.assertIn("version", data)
        self.assertIn("timestamp", data)

    @patch("src.api.main.get_db_connection")
    def test_02_readiness_endpoint_ready(self, mock_get_conn):
        """Verify GET /ready returns 200 when database and extensions are available."""
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_cur.fetchall.return_value = [("postgis",), ("vector",)]
        mock_conn.cursor.return_value.__enter__.return_value = mock_cur
        mock_get_conn.return_value = mock_conn

        res = self.client.get("/ready")
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        data = res.json()
        self.assertEqual(data["status"], "ready")
        self.assertEqual(data["database"], "connected")
        self.assertEqual(data["postgis"], "available")
        self.assertEqual(data["pgvector"], "available")
        self.assertIn("llm_provider", data)

    @patch("src.api.main.get_db_connection")
    def test_03_readiness_endpoint_unreachable_database(self, mock_get_conn):
        """Verify GET /ready returns 503 when database connection fails."""
        mock_get_conn.side_effect = Exception("Connection refused on port 5432")

        res = self.client.get("/ready")
        self.assertEqual(res.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)
        data = res.json()
        self.assertEqual(data["status"], "not_ready")
        self.assertEqual(data["database"], "unreachable")
        self.assertIn("database_error", data["details"])

    # ===================================================================
    # 2. Chat API Routing Tests (Flows 1, 2, 3)
    # ===================================================================

    def test_04_chat_knowledge_only_request(self):
        """Verify Flow 1 (KNOWLEDGE_ONLY) returns grounded citations and no SQL metadata."""
        mock_state: FloatChatState = {
            "user_query": "How do CTD sensors work?",
            "session_id": "sess-k1",
            "intent_type": "KNOWLEDGE_ONLY",
            "final_response": "CTD sensors measure conductivity, temperature, and depth [CTD Sensor Principles, Section 1].",
            "citations": [
                {
                    "document_title": "CTD Sensor Principles",
                    "section_title": "Section 1",
                    "chunk_id": "1",
                    "snippet": "CTD sensors measure conductivity...",
                }
            ],
            "generated_sql": None,
            "db_result": None,
            "visualization_spec": None,
            "status": "SUCCESS",
            "warnings": [],
        }
        self.mock_orchestrator.invoke.return_value = mock_state

        res = self.client.post("/api/v1/chat", json={"query": "How do CTD sensors work?", "session_id": "sess-k1"})
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        data = res.json()

        self.assertEqual(data["intent_type"], "KNOWLEDGE_ONLY")
        self.assertEqual(data["session_id"], "sess-k1")
        self.assertIn("CTD sensors measure", data["answer"])
        self.assertEqual(len(data["citations"]), 1)
        self.assertEqual(data["citations"][0]["document_title"], "CTD Sensor Principles")
        self.assertIsNone(data["sql_meta"])
        self.assertIsNone(data["visualization_spec"])

    def test_05_chat_data_only_request(self):
        """Verify Flow 2 (DATA_ONLY) returns SQL metrics, data summary, and visualization spec."""
        mock_state: FloatChatState = {
            "user_query": "Show temperature readings for float 2901333",
            "session_id": "sess-d1",
            "intent_type": "DATA_ONLY",
            "final_response": "Float 2901333 recorded water temperatures between 25.0°C and 28.5°C.",
            "citations": [],
            "generated_sql": "SELECT temp, pres FROM argo_measurements WHERE platform_number = 2901333",
            "db_row_count": 25,
            "db_execution_time_ms": 14.2,
            "db_result": DatabaseExecutionResult(
                status=ExecutionStatus.SUCCESS,
                columns=["temp", "pres"],
                rows=[{"temp": 28.5, "pres": 10.0}],
                row_count=25,
                execution_time_ms=14.2,
            ),
            "data_summary": {
                "total_records": 25,
                "variables_present": ["temp", "pres"],
                "highlights": ["temp: min=25.00, max=28.50, mean=27.10"],
            },
            "visualization_spec": {
                "chart_type": "line",
                "x_axis": "temp",
                "y_axis": "pres",
                "title": "Vertical Temperature Profile",
                "invert_y": True,
            },
            "status": "SUCCESS",
            "warnings": [],
        }
        self.mock_orchestrator.invoke.return_value = mock_state

        res = self.client.post("/api/v1/chat", json={"query": "Show temperature readings for float 2901333"})
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        data = res.json()

        self.assertEqual(data["intent_type"], "DATA_ONLY")
        self.assertIsNotNone(data["sql_meta"])
        self.assertEqual(data["sql_meta"]["row_count"], 25)
        self.assertEqual(data["sql_meta"]["execution_time_ms"], 14.2)
        self.assertIsNotNone(data["visualization_spec"])
        self.assertEqual(data["visualization_spec"]["chart_type"], "line")
        self.assertTrue(data["visualization_spec"]["invert_y"])

    def test_06_chat_hybrid_request(self):
        """Verify Flow 3 (HYBRID) returns both scientific citations and observation SQL metrics."""
        mock_state: FloatChatState = {
            "user_query": "Explain thermocline measurements for float 2901333.",
            "intent_type": "HYBRID",
            "final_response": "Observations show a steep thermocline gradient consistent with ARGO QC standards [ARGO QC, Thermal Test].",
            "citations": [{"document_title": "ARGO QC", "section_title": "Thermal Test"}],
            "generated_sql": "SELECT temp, pres FROM argo_measurements",
            "db_row_count": 10,
            "db_execution_time_ms": 11.0,
            "visualization_spec": {
                "chart_type": "line",
                "x_axis": "temp",
                "y_axis": "pres",
                "title": "Thermocline Profile",
                "invert_y": True,
            },
            "status": "SUCCESS",
            "warnings": [],
        }
        self.mock_orchestrator.invoke.return_value = mock_state

        res = self.client.post("/api/v1/chat", json={"query": "Explain thermocline measurements."})
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        data = res.json()

        self.assertEqual(data["intent_type"], "HYBRID")
        self.assertEqual(len(data["citations"]), 1)
        self.assertIsNotNone(data["sql_meta"])
        self.assertIsNotNone(data["visualization_spec"])

    def test_07_query_endpoint_alias(self):
        """Verify POST /api/v1/query serves as a valid alias for /api/v1/chat."""
        mock_state: FloatChatState = {
            "user_query": "Test query",
            "intent_type": "KNOWLEDGE_ONLY",
            "final_response": "Test answer",
            "status": "SUCCESS",
        }
        self.mock_orchestrator.invoke.return_value = mock_state

        res = self.client.post("/api/v1/query", json={"query": "Test query"})
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.json()["answer"], "Test answer")

    # ===================================================================
    # 3. Input Validation & Edge Cases
    # ===================================================================

    def test_08_invalid_input_empty_and_whitespace_query(self):
        """Verify empty or whitespace-only queries are rejected with HTTP 422."""
        # Empty string
        res1 = self.client.post("/api/v1/chat", json={"query": ""})
        self.assertEqual(res1.status_code, status.HTTP_422_UNPROCESSABLE_ENTITY)
        self.assertEqual(res1.json()["error_code"], "VALIDATION_ERROR")

        # Whitespace-only string
        res2 = self.client.post("/api/v1/chat", json={"query": "    \n   "})
        self.assertEqual(res2.status_code, status.HTTP_422_UNPROCESSABLE_ENTITY)
        self.assertEqual(res2.json()["error_code"], "VALIDATION_ERROR")

    def test_09_invalid_input_oversized_query(self):
        """Verify queries exceeding 2000 characters are rejected with HTTP 422."""
        oversized = "a" * 2001
        res = self.client.post("/api/v1/chat", json={"query": oversized})
        self.assertEqual(res.status_code, status.HTTP_422_UNPROCESSABLE_ENTITY)
        self.assertEqual(res.json()["error_code"], "VALIDATION_ERROR")

    # ===================================================================
    # 4. Error Handling & Timeouts
    # ===================================================================

    def test_10_orchestration_timeout_returns_504(self):
        """Verify workflow timeout returns HTTP 504 Gateway Timeout and signals cancellation."""
        import time

        captured_tokens = []

        def slow_invoke(query, session_id, cancellation_token=None):
            captured_tokens.append(cancellation_token)
            for _ in range(30):
                if cancellation_token and cancellation_token.is_cancelled:
                    break
                time.sleep(0.01)
            return {}

        self.mock_orchestrator.invoke.side_effect = slow_invoke

        # Re-initialize client with 0.1s timeout
        fast_timeout_config = Config(request_timeout_seconds=0.1, internal_secret=self.internal_secret)
        fast_app = create_app(config=fast_timeout_config)
        fast_app.state.orchestrator = self.mock_orchestrator
        fast_app.state.config = fast_timeout_config
        fast_client = TestClient(fast_app, headers={"X-Internal-Secret": self.internal_secret})

        res = fast_client.post("/api/v1/chat", json={"query": "Slow query"})
        self.assertEqual(res.status_code, status.HTTP_504_GATEWAY_TIMEOUT)
        data = res.json()
        self.assertEqual(data["error_code"], "HTTP_ERROR")
        self.assertIn("timed out", data["message"])
        self.assertTrue(len(captured_tokens) > 0)
        self.assertIsNotNone(captured_tokens[0])
        self.assertTrue(captured_tokens[0].is_cancelled, "Cancellation token must be signalled on timeout")

    def test_11_orchestration_unhandled_exception_returns_500_without_leaks(self):
        """Verify unhandled orchestrator crash returns HTTP 500 without leaking stack traces or paths."""
        self.mock_orchestrator.invoke.side_effect = RuntimeError("Fatal internal memory error at /internal/secrets.key")

        res = self.client.post("/api/v1/chat", json={"query": "Crash query"})
        self.assertEqual(res.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR)
        data = res.json()
        self.assertEqual(data["error_code"], "HTTP_ERROR")
        # Ensure stack trace or internal path is NOT exposed to client
        self.assertNotIn("/internal/secrets.key", data["message"])
        self.assertIn("internal error", data["message"].lower())

    # ===================================================================
    # 5. CORS Header Verification
    # ===================================================================

    def test_12_cors_preflight_headers(self):
        """Verify CORS preflight request allows configured origins."""
        headers = {
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "Content-Type",
        }
        res = self.client.options("/api/v1/chat", headers=headers)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.headers.get("access-control-allow-origin"), "http://localhost:3000")


    # ===================================================================
    # 6. Concurrency Protection & Rate Limiting (Phase F6B & F6C)
    # ===================================================================

    def test_13_concurrency_limit_rejects_with_429_and_retry_after(self):
        """Verify prompt rejection with HTTP 429 and Retry-After header when concurrency limit is reached."""
        sem = self.app.state.inference_semaphore
        # Artificially lock the semaphore to simulate active inference
        sem._value = 0
        try:
            res = self.client.post("/api/v1/chat", json={"query": "Test query while busy"})
            self.assertEqual(res.status_code, status.HTTP_429_TOO_MANY_REQUESTS)
            self.assertEqual(res.headers.get("retry-after"), "30")
            data = res.json()
            self.assertEqual(data["error_code"], "RATE_LIMIT_EXCEEDED")
            self.assertIn("busy", data["message"].lower())
        finally:
            sem._value = 1

    def test_14_concurrency_slot_released_on_success_and_error(self):
        """Verify concurrency slot is always released after success and after errors."""
        sem = self.app.state.inference_semaphore
        self.assertEqual(sem._value, 1)

        # 1. Success case
        self.mock_orchestrator.invoke.return_value = {
            "user_query": "Test query",
            "intent_type": "KNOWLEDGE_ONLY",
            "final_response": "Success answer",
            "status": "SUCCESS",
        }
        res_success = self.client.post("/api/v1/chat", json={"query": "Test query"})
        self.assertEqual(res_success.status_code, status.HTTP_200_OK)
        self.assertEqual(sem._value, 1, "Semaphore slot must be released after successful inference")

        # 2. Error case (orchestrator crash)
        self.mock_orchestrator.invoke.side_effect = RuntimeError("Simulated crash")
        res_error = self.client.post("/api/v1/chat", json={"query": "Crashing query"})
        self.assertEqual(res_error.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR)
        self.assertEqual(sem._value, 1, "Semaphore slot must be released after error")

        # 3. Subsequent request succeeds after slot is released
        self.mock_orchestrator.invoke.side_effect = None
        self.mock_orchestrator.invoke.return_value = {
            "user_query": "Follow-up query",
            "intent_type": "KNOWLEDGE_ONLY",
            "final_response": "Subsequent success",
            "status": "SUCCESS",
        }
        res_subsequent = self.client.post("/api/v1/chat", json={"query": "Follow-up query"})
        self.assertEqual(res_subsequent.status_code, status.HTTP_200_OK)
        self.assertEqual(res_subsequent.json()["answer"], "Subsequent success")
        self.assertEqual(sem._value, 1)

    @patch("src.api.main.get_db_connection")
    def test_15_health_and_ready_responsive_during_inference_overload(self, mock_get_conn):
        """Verify /health and /ready remain responsive when inference capacity is fully occupied."""
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_cur.fetchall.return_value = [("postgis",), ("vector",)]
        mock_conn.cursor.return_value.__enter__.return_value = mock_cur
        mock_get_conn.return_value = mock_conn

        sem = self.app.state.inference_semaphore
        sem._value = 0  # Inference capacity occupied
        try:
            # /health must respond with 200
            res_health = self.client.get("/health")
            self.assertEqual(res_health.status_code, status.HTTP_200_OK)
            self.assertEqual(res_health.json()["status"], "healthy")

            # /ready must respond with 200
            res_ready = self.client.get("/ready")
            self.assertEqual(res_ready.status_code, status.HTTP_200_OK)
            self.assertEqual(res_ready.json()["status"], "ready")

            # But /api/v1/chat must be rejected with 429
            res_chat = self.client.post("/api/v1/chat", json={"query": "Are you busy?"})
            self.assertEqual(res_chat.status_code, status.HTTP_429_TOO_MANY_REQUESTS)
        finally:
            sem._value = 1

    def test_16_query_length_validation_with_configured_limit(self):
        """Verify queries exceeding config.max_query_length are rejected with HTTP 400."""
        custom_config = Config(max_query_length=50, internal_secret=self.internal_secret)
        custom_app = create_app(config=custom_config)
        custom_app.state.orchestrator = self.mock_orchestrator
        custom_app.state.config = custom_config
        custom_client = TestClient(custom_app, headers={"X-Internal-Secret": self.internal_secret})

        oversized_for_config = "A" * 60
        res = custom_client.post("/api/v1/chat", json={"query": oversized_for_config})
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("exceeds the maximum allowed limit of 50", res.json()["message"])

    # ===================================================================
    # 7. F11 Shared Secret & Security Hardening Tests
    # ===================================================================

    def test_17_internal_secret_missing_rejects_with_401(self):
        """Verify request without X-Internal-Secret header is rejected with HTTP 401."""
        unauthenticated_client = TestClient(self.app)
        res = unauthenticated_client.post("/api/v1/chat", json={"query": "Test query without auth"})
        self.assertEqual(res.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertIn("Invalid or missing internal service secret", res.json()["message"])

    def test_18_internal_secret_invalid_rejects_with_401(self):
        """Verify request with wrong X-Internal-Secret header is rejected with HTTP 401."""
        wrong_auth_client = TestClient(self.app, headers={"X-Internal-Secret": "wrong_secret_12345"})
        res = wrong_auth_client.post("/api/v1/chat", json={"query": "Test query with wrong auth"})
        self.assertEqual(res.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertIn("Invalid or missing internal service secret", res.json()["message"])

    def test_19_health_and_ready_remain_public_without_auth_secret(self):
        """Verify /health and /ready do not require X-Internal-Secret."""
        unauthenticated_client = TestClient(self.app)
        res_health = unauthenticated_client.get("/health")
        self.assertEqual(res_health.status_code, status.HTTP_200_OK)

        with patch("src.api.main.get_db_connection") as mock_conn:
            mock_c = MagicMock()
            mock_cur = MagicMock()
            mock_cur.fetchall.return_value = [("postgis",), ("vector",)]
            mock_c.cursor.return_value.__enter__.return_value = mock_cur
            mock_conn.return_value = mock_c
            res_ready = unauthenticated_client.get("/ready")
            self.assertEqual(res_ready.status_code, status.HTTP_200_OK)

    def test_20_scientific_stats_endpoint_returns_metrics(self):
        """Verify /api/v1/stats returns real dataset count metrics with valid auth."""
        with patch("src.api.main.get_db_connection") as mock_conn:
            mock_c = MagicMock()
            mock_cur = MagicMock()
            # Order of fetchone calls: floats, profiles, measurements, chunks, dim
            mock_cur.fetchone.side_effect = [(30,), (107,), (26046,), (12,), (768,)]
            mock_c.cursor.return_value.__enter__.return_value = mock_cur
            mock_conn.return_value = mock_c

            res = self.client.get("/api/v1/stats")
            self.assertEqual(res.status_code, status.HTTP_200_OK)
            body = res.json()
            self.assertEqual(body["total_floats"], 30)
            self.assertEqual(body["total_profiles"], 107)
            self.assertEqual(body["total_measurements"], 26046)
            self.assertEqual(body["total_document_chunks"], 12)
            self.assertEqual(body["embedding_dimension"], 768)

    def test_21_scientific_stats_requires_internal_secret(self):
        """Verify /api/v1/stats requires internal secret when configured."""
        unauthenticated_client = TestClient(self.app)
        res = unauthenticated_client.get("/api/v1/stats")
        self.assertEqual(res.status_code, status.HTTP_401_UNAUTHORIZED)


    def test_22_startup_warmup_successful(self):
        """Verify startup warm-up calls generation model with dedicated 5.0s timeout, prompt='ping' and max_tokens=1."""
        config = Config(
            llm_provider="ollama",
            ollama_warmup_on_startup=True,
            ollama_warmup_timeout_seconds=5.0,
            ollama_model="qwen2.5:1.5b-instruct",
            ollama_keep_alive="30m",
            internal_secret=self.internal_secret,
        )
        with patch("src.llm.get_llm_provider") as mock_get_provider:
            mock_provider = MagicMock()
            mock_provider.generate.return_value = GenerationResult(
                text="pong",
                load_duration_ms=15.0,
            )
            mock_get_provider.return_value = mock_provider

            app = create_app(config=config)
            with TestClient(app, headers={"X-Internal-Secret": self.internal_secret}) as client:
                res = client.get("/health")
                self.assertEqual(res.status_code, status.HTTP_200_OK)

            mock_get_provider.assert_called_once_with(
                "ollama",
                model="qwen2.5:1.5b-instruct",
                base_url="http://localhost:11434",
                timeout=5.0,
                keep_alive="30m",
            )
            mock_provider.generate.assert_called_once_with(
                prompt="ping",
                max_tokens=1,
                temperature=0.0,
            )

    def test_23_startup_warmup_failure_is_non_fatal(self):
        """Verify startup warm-up exception does not crash or block service startup."""
        config = Config(
            llm_provider="ollama",
            ollama_warmup_on_startup=True,
            ollama_warmup_timeout_seconds=5.0,
            internal_secret=self.internal_secret,
        )
        with patch("src.llm.get_llm_provider") as mock_get_provider:
            mock_provider = MagicMock()
            mock_provider.generate.side_effect = Exception("Ollama connection refused")
            mock_get_provider.return_value = mock_provider

            app = create_app(config=config)
            with TestClient(app, headers={"X-Internal-Secret": self.internal_secret}) as client:
                res = client.get("/health")
                self.assertEqual(res.status_code, status.HTTP_200_OK)

    def test_24_startup_warmup_disabled(self):
        """Verify startup warm-up is skipped completely when ollama_warmup_on_startup=False."""
        config = Config(
            llm_provider="ollama",
            ollama_warmup_on_startup=False,
            internal_secret=self.internal_secret,
        )
        with patch("src.llm.get_llm_provider") as mock_get_provider:
            app = create_app(config=config)
            with TestClient(app, headers={"X-Internal-Secret": self.internal_secret}) as client:
                res = client.get("/health")
                self.assertEqual(res.status_code, status.HTTP_200_OK)

            mock_get_provider.assert_not_called()

    # ===================================================================
    # 10. Competition Fix 2: Worker Cancellation & Concurrency Lifecycle
    # ===================================================================

    def test_25_timed_out_request_keeps_slot_until_worker_exits(self):
        """Verify concurrency slot remains occupied after timeout until background worker completes."""
        import time
        from concurrent.futures import ThreadPoolExecutor
        from threading import Event

        worker_started_event = Event()

        def lingering_invoke(query, session_id, cancellation_token=None):
            worker_started_event.set()
            # Wait until cancellation is signalled upon timeout
            for _ in range(100):
                if cancellation_token and cancellation_token.is_cancelled:
                    break
                time.sleep(0.01)
            return {}

        self.mock_orchestrator.invoke.side_effect = lingering_invoke

        fast_timeout_config = Config(request_timeout_seconds=0.1, internal_secret=self.internal_secret)
        fast_app = create_app(config=fast_timeout_config)
        fast_app.state.orchestrator = self.mock_orchestrator
        fast_client = TestClient(fast_app, headers={"X-Internal-Secret": self.internal_secret})

        with ThreadPoolExecutor(max_workers=2) as executor:
            # 1. Start request 1 in thread
            fut1 = executor.submit(fast_client.post, "/api/v1/chat", json={"query": "Lingering query"})

            # 2. Wait until worker 1 has started and acquired slot
            started = worker_started_event.wait(timeout=1.0)
            self.assertTrue(started, "Worker 1 must have started")

            # 3. Request 2 while worker 1 is active must receive HTTP 429
            res2 = fast_client.post("/api/v1/chat", json={"query": "Subsequent query during linger"})
            self.assertEqual(res2.status_code, status.HTTP_429_TOO_MANY_REQUESTS)
            self.assertEqual(res2.headers.get("retry-after"), "30")

            # 4. Request 1 times out with HTTP 504
            res1 = fut1.result(timeout=2.0)
            self.assertEqual(res1.status_code, status.HTTP_504_GATEWAY_TIMEOUT)

        # 5. After worker finishes, slot is freed
        time.sleep(0.05)
        self.assertEqual(fast_app.state.active_inferences, 0)

    def test_26_worker_cancelled_error_post_timeout_consumed_cleanly(self):
        """Verify WorkflowCancelledError in background worker is consumed without unhandled exception warning."""
        import time
        from src.orchestration.cancellation import WorkflowCancelledError

        def cancelling_invoke(query, session_id, cancellation_token=None):
            for _ in range(50):
                if cancellation_token and cancellation_token.is_cancelled:
                    raise WorkflowCancelledError("Cancelled by token")
                time.sleep(0.01)
            return {}

        self.mock_orchestrator.invoke.side_effect = cancelling_invoke

        fast_timeout_config = Config(request_timeout_seconds=0.05, internal_secret=self.internal_secret)
        fast_app = create_app(config=fast_timeout_config)
        fast_app.state.orchestrator = self.mock_orchestrator
        fast_client = TestClient(fast_app, headers={"X-Internal-Secret": self.internal_secret})

        res = fast_client.post("/api/v1/chat", json={"query": "Cancel worker query"})
        self.assertEqual(res.status_code, status.HTTP_504_GATEWAY_TIMEOUT)

        time.sleep(0.05)
        self.assertEqual(fast_app.state.active_inferences, 0)
        sem = fast_app.state.inference_semaphore
        self.assertEqual(sem._value, 1)

    def test_27_cancellation_and_completion_slot_accounting(self):
        """Verify subsequent request proceeds smoothly after cancelled request worker finishes."""
        import time

        def fast_exit_invoke(query, session_id, cancellation_token=None):
            while not (cancellation_token and cancellation_token.is_cancelled):
                time.sleep(0.01)
            return {}

        self.mock_orchestrator.invoke.side_effect = fast_exit_invoke

        fast_timeout_config = Config(request_timeout_seconds=0.05, internal_secret=self.internal_secret)
        fast_app = create_app(config=fast_timeout_config)
        fast_app.state.orchestrator = self.mock_orchestrator
        fast_client = TestClient(fast_app, headers={"X-Internal-Secret": self.internal_secret})

        res1 = fast_client.post("/api/v1/chat", json={"query": "First query"})
        self.assertEqual(res1.status_code, status.HTTP_504_GATEWAY_TIMEOUT)

        time.sleep(0.05)
        self.assertEqual(fast_app.state.active_inferences, 0)

        # Subsequent query succeeds
        self.mock_orchestrator.invoke.side_effect = None
        self.mock_orchestrator.invoke.return_value = {
            "user_query": "Next query",
            "intent_type": "KNOWLEDGE_ONLY",
            "final_response": "Next response",
            "status": "SUCCESS",
        }
        res2 = fast_client.post("/api/v1/chat", json={"query": "Next query"})
        self.assertEqual(res2.status_code, status.HTTP_200_OK)
        self.assertEqual(res2.json()["answer"], "Next response")
        self.assertEqual(fast_app.state.active_inferences, 0)


if __name__ == "__main__":
    unittest.main()
