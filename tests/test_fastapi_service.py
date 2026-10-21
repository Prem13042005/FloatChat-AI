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
from src.orchestration import FloatChatOrchestrator, FloatChatState


class TestFastAPIService(unittest.TestCase):

    def setUp(self):
        self.config = Config(
            postgres_port=5432,
            request_timeout_seconds=5.0,
            max_query_length=2000,
            cors_origins="http://localhost:3000,http://localhost:8080",
        )
        self.app = create_app(config=self.config)
        self.mock_orchestrator = MagicMock(spec=FloatChatOrchestrator)
        self.app.state.orchestrator = self.mock_orchestrator
        self.app.state.config = self.config
        self.client = TestClient(self.app)

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
        """Verify workflow timeout returns HTTP 504 Gateway Timeout."""
        import time

        def slow_invoke(query, session_id):
            time.sleep(0.3)
            return {}

        self.mock_orchestrator.invoke.side_effect = slow_invoke

        # Re-initialize client with 0.1s timeout
        fast_timeout_config = Config(request_timeout_seconds=0.1)
        fast_app = create_app(config=fast_timeout_config)
        fast_app.state.orchestrator = self.mock_orchestrator
        fast_app.state.config = fast_timeout_config
        fast_client = TestClient(fast_app)

        res = fast_client.post("/api/v1/chat", json={"query": "Slow query"})
        self.assertEqual(res.status_code, status.HTTP_504_GATEWAY_TIMEOUT)
        data = res.json()
        self.assertEqual(data["error_code"], "HTTP_ERROR")
        self.assertIn("timed out", data["message"])

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


if __name__ == "__main__":
    unittest.main()
