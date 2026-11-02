"""
tests/test_response_agent.py

Phase 8 — Scientific Knowledge & Response Agent Test Suite.
Verifies:
- Scientific document retrieval and grounded citation mapping
- Dual-evidence synthesis combining SQL results with scientific domain context
- Behavior when only scientific evidence or only SQL results are available
- Empty and failed document retrieval handling
- Empty and failed SQL query execution handling
- Anti-hallucination guardrails: filtering ungrounded citations and claims
- Visualization specification grounding in actual database columns and values
- Rejection of visualizations when required columns are absent
- Graceful degradation on language model failures or network timeouts
- Deterministic fallback generation without crashing

All tests run isolated and offline using unittest.mock.
"""

import os
import sys
import unittest
from unittest.mock import MagicMock, patch

# Ensure src is in python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.agents.query_understanding.models import (
    AggregationOp,
    IntentCategory,
    IntentType,
    PhysicalVariable,
    QueryIntent,
    SpatialBounds,
    TemporalRange,
)
from src.agents.response import (
    ChartType,
    Citation,
    DataSummary,
    ResponseStatus,
    ScientificResponse,
    ScientificResponseAgent,
    VisualizationSpec,
)
from src.agents.response.agent import _LLMResponsePayload
from src.database.models import DatabaseExecutionResult, ExecutionStatus
from src.llm import BaseLLMProvider, LLMConnectionError, LLMProviderError, LLMTimeoutError
from src.rag.models import RetrievalResult, RetrievedChunk
from src.rag.retriever import ScientificDocumentRetriever


class TestScientificResponseAgent(unittest.TestCase):

    def setUp(self):
        self.mock_llm = MagicMock(spec=BaseLLMProvider)
        self.mock_retriever = MagicMock(spec=ScientificDocumentRetriever)
        self.mock_retriever.retrieve.return_value = RetrievalResult(
            query="",
            chunks=[],
            total_found=0,
            status="empty",
        )
        self.agent = ScientificResponseAgent(
            llm_provider=self.mock_llm,
            retriever=self.mock_retriever,
        )


    # ===================================================================
    # 1. Knowledge-Only Grounded Response & Citation Mapping
    # ===================================================================

    def test_01_knowledge_only_grounded_response(self):
        """Verify knowledge-only queries produce grounded answer with explicit citations."""
        query = "How do ARGO CTD sensors measure salinity and temperature?"
        intent = QueryIntent(
            intent_type=IntentType.KNOWLEDGE_ONLY,
            intent_category=IntentCategory.RETRIEVAL,
        )

        sample_chunk = RetrievedChunk(
            chunk_id=101,
            document_title="CTD Sensor Principles",
            section_title="Conductivity Cell Operation",
            chunk_content="ARGO floats measure salinity indirectly by measuring conductivity, temperature, and pressure.",
            similarity_score=0.88,
        )
        self.mock_retriever.retrieve.return_value = RetrievalResult(
            query=query,
            chunks=[sample_chunk],
            total_found=1,
            status="success",
        )

        mock_payload = _LLMResponsePayload(
            answer="ARGO floats measure salinity indirectly by sensing electrical conductivity, temperature, and pressure [CTD Sensor Principles, Conductivity Cell Operation].",
            citations=[
                Citation(
                    document_title="CTD Sensor Principles",
                    section_title="Conductivity Cell Operation",
                    chunk_id="101",
                )
            ],
        )
        self.mock_llm.generate_structured.return_value = mock_payload

        response: ScientificResponse = self.agent.respond(query=query, intent=intent)

        self.assertEqual(response.status, ResponseStatus.SUCCESS)
        self.assertTrue(response.is_success)
        self.assertIn("CTD Sensor Principles", response.answer)
        self.assertEqual(len(response.citations), 1)
        self.assertEqual(response.citations[0].document_title, "CTD Sensor Principles")
        self.assertEqual(response.citations[0].section_title, "Conductivity Cell Operation")
        self.assertIsNone(response.visualization_spec)
        self.mock_retriever.retrieve.assert_called_once()
        self.mock_llm.generate_structured.assert_called_once()

    # ===================================================================
    # 2. Data-Only with Observational Results and Grounded Visualization
    # ===================================================================

    def test_02_data_only_with_observations_and_visualization(self):
        """Verify data-only query produces exact data summary and grounded profile visualization."""
        query = "Show vertical temperature readings for float 2901333."
        intent = QueryIntent(
            intent_type=IntentType.DATA_ONLY,
            intent_category=IntentCategory.FILTERING,
            physical_variables=[PhysicalVariable.TEMP],
        )

        db_result = DatabaseExecutionResult(
            status=ExecutionStatus.SUCCESS,
            columns=["pres", "temp", "platform_number", "cycle_number"],
            rows=[
                {"pres": 10.0, "temp": 28.5, "platform_number": 2901333, "cycle_number": 1},
                {"pres": 50.0, "temp": 26.2, "platform_number": 2901333, "cycle_number": 1},
                {"pres": 100.0, "temp": 21.0, "platform_number": 2901333, "cycle_number": 1},
                {"pres": 500.0, "temp": 10.5, "platform_number": 2901333, "cycle_number": 1},
            ],
            row_count=4,
            execution_time_ms=12.5,
        )

        mock_payload = _LLMResponsePayload(
            answer="Float 2901333 measured temperatures decreasing from 28.5°C at 10 dbar to 10.5°C at 500 dbar depth.",
            citations=[],
        )
        self.mock_llm.generate_structured.return_value = mock_payload

        response = self.agent.respond(query=query, intent=intent, db_result=db_result)

        self.assertEqual(response.status, ResponseStatus.SUCCESS)
        self.assertIsNotNone(response.data_summary)
        self.assertEqual(response.data_summary.total_records, 4)
        self.assertIn("pres", response.data_summary.variables_present)
        self.assertIn("temp", response.data_summary.variables_present)

        # Verify visualization spec is strictly grounded
        self.assertIsNotNone(response.visualization_spec)
        self.assertIsNotNone(response.visualization_spec.data)
        self.assertTrue(len(response.visualization_spec.data) > 0)
        self.assertEqual(response.visualization_spec.chart_type, ChartType.LINE)
        self.assertEqual(response.visualization_spec.x_axis, "temp")
        self.assertEqual(response.visualization_spec.y_axis, "pres")
        self.assertTrue(response.visualization_spec.invert_y)
        self.assertEqual(response.visualization_spec.series_column, "platform_number")

    # ===================================================================
    # 3. Hybrid Synthesis: Combining SQL Results with Scientific Context
    # ===================================================================

    def test_03_hybrid_response_combining_sql_and_scientific_context(self):
        """Verify hybrid queries contextualize observations using scientific literature."""
        query = "Explain the thermocline drop in float 2901333 temperature observations."
        intent = QueryIntent(
            intent_type=IntentType.HYBRID,
            intent_category=IntentCategory.COMBINED,
            physical_variables=[PhysicalVariable.TEMP],
        )

        sample_chunk = RetrievedChunk(
            chunk_id=202,
            document_title="ARGO Quality Control Standards",
            section_title="Thermal Gradient Verification",
            chunk_content="Steep temperature decreases across the main thermocline (100-500 dbar) are characteristic of tropical waters.",
            similarity_score=0.85,
        )
        self.mock_retriever.retrieve.return_value = RetrievalResult(
            query=query,
            chunks=[sample_chunk],
            total_found=1,
            status="success",
        )

        db_result = DatabaseExecutionResult(
            status=ExecutionStatus.SUCCESS,
            columns=["pres", "temp"],
            rows=[
                {"pres": 10.0, "temp": 28.0},
                {"pres": 200.0, "temp": 15.0},
                {"pres": 500.0, "temp": 9.0},
            ],
            row_count=3,
        )

        mock_payload = _LLMResponsePayload(
            answer="Measured observations show temperatures dropping from 28.0°C to 9.0°C. As documented in [ARGO Quality Control Standards, Thermal Gradient Verification], steep thermocline gradients are expected in this region.",
            citations=[
                Citation(
                    document_title="ARGO Quality Control Standards",
                    section_title="Thermal Gradient Verification",
                    chunk_id="202",
                )
            ],
        )
        self.mock_llm.generate_structured.return_value = mock_payload

        response = self.agent.respond(query=query, intent=intent, db_result=db_result)

        self.assertEqual(response.status, ResponseStatus.SUCCESS)
        self.assertEqual(len(response.citations), 1)
        self.assertEqual(response.citations[0].document_title, "ARGO Quality Control Standards")
        self.assertIsNotNone(response.data_summary)
        self.assertEqual(response.data_summary.total_records, 3)
        self.assertIsNotNone(response.visualization_spec)
        self.assertIsNotNone(response.visualization_spec.data)
        self.assertTrue(len(response.visualization_spec.data) > 0)

    # ===================================================================
    # 4. Empty and Failed Retrieval Handling
    # ===================================================================

    def test_04_empty_retrieval_knowledge_only(self):
        """Verify empty retrieval on KNOWLEDGE_ONLY returns explicit notice without hallucination."""
        query = "What is the mating cycle of Arctic penguins?"
        intent = QueryIntent(
            intent_type=IntentType.KNOWLEDGE_ONLY,
            intent_category=IntentCategory.RETRIEVAL,
        )

        self.mock_retriever.retrieve.return_value = RetrievalResult(
            query=query,
            chunks=[],
            total_found=0,
            status="empty",
        )

        response = self.agent.respond(query=query, intent=intent)

        self.assertEqual(response.status, ResponseStatus.NO_KNOWLEDGE_MATCH)
        self.assertIn("Information not found in authoritative ARGO documentation", response.answer)
        self.assertEqual(len(response.citations), 0)
        # Verify LLM was NOT invoked to prevent hallucinating unsupported topics
        self.mock_llm.generate_structured.assert_not_called()

    def test_05_failed_retrieval_graceful_degradation(self):
        """Verify agent handles retrieval exceptions gracefully without crashing."""
        query = "What is delayed-mode quality control?"
        intent = QueryIntent(
            intent_type=IntentType.KNOWLEDGE_ONLY,
            intent_category=IntentCategory.RETRIEVAL,
        )

        self.mock_retriever.retrieve.side_effect = Exception("pgvector database connection timeout")

        response = self.agent.respond(query=query, intent=intent)

        self.assertEqual(response.status, ResponseStatus.NO_KNOWLEDGE_MATCH)
        self.assertTrue(any("retrieval degraded" in w.lower() for w in response.warnings))

    # ===================================================================
    # 5. Empty and Failed SQL Results Handling
    # ===================================================================

    def test_06_empty_sql_results_data_only(self):
        """Verify empty database rows on DATA_ONLY returns explicit notice without hallucinating data."""
        query = "Show observations for non-existent float 9999999."
        intent = QueryIntent(
            intent_type=IntentType.DATA_ONLY,
            intent_category=IntentCategory.FILTERING,
        )

        db_result = DatabaseExecutionResult(
            status=ExecutionStatus.SUCCESS,
            columns=["pres", "temp"],
            rows=[],
            row_count=0,
        )

        response = self.agent.respond(query=query, intent=intent, db_result=db_result)

        self.assertEqual(response.status, ResponseStatus.NO_DATA_MATCH)
        self.assertIn("No observation records matched", response.answer)
        self.assertIsNone(response.visualization_spec)
        self.mock_llm.generate_structured.assert_not_called()

    def test_07_failed_database_execution_reported(self):
        """Verify failed database execution is captured in warnings and summarized safely."""
        query = "Select observations."
        intent = QueryIntent(
            intent_type=IntentType.DATA_ONLY,
            intent_category=IntentCategory.FILTERING,
        )

        db_result = DatabaseExecutionResult(
            status=ExecutionStatus.TIMEOUT,
            error_message="Query cancelled due to statement timeout (5000ms).",
            columns=[],
            rows=[],
            row_count=0,
        )

        mock_payload = _LLMResponsePayload(
            answer="The query could not be completed because the database operation timed out.",
            citations=[],
        )
        self.mock_llm.generate_structured.return_value = mock_payload

        response = self.agent.respond(query=query, intent=intent, db_result=db_result)

        self.assertTrue(any("timeout" in w.lower() for w in response.warnings))

    # ===================================================================
    # 6. Anti-Hallucination: Filtering Ungrounded Citations
    # ===================================================================

    def test_08_filters_ungrounded_citations(self):
        """Verify agent strips citations that were NOT present in retrieved chunks."""
        query = "Explain CTD sensors."
        intent = QueryIntent(
            intent_type=IntentType.KNOWLEDGE_ONLY,
            intent_category=IntentCategory.RETRIEVAL,
        )

        valid_chunk = RetrievedChunk(
            chunk_id=303,
            document_title="CTD Sensor Principles",
            section_title="Temperature Measurement",
            chunk_content="Platinum resistance thermometers measure sea temperature.",
            similarity_score=0.90,
        )
        self.mock_retriever.retrieve.return_value = RetrievalResult(
            query=query,
            chunks=[valid_chunk],
            total_found=1,
            status="success",
        )

        # Mock LLM returning 1 valid citation and 1 fabricated citation
        mock_payload = _LLMResponsePayload(
            answer="Temperature is measured with platinum thermistors [CTD Sensor Principles]. Also see [Random Ocean Blog, Chap 1].",
            citations=[
                Citation(
                    document_title="CTD Sensor Principles",
                    section_title="Temperature Measurement",
                    chunk_id="303",
                ),
                Citation(
                    document_title="Random Ocean Blog",
                    section_title="Chap 1",
                    chunk_id="fake_id",
                ),
            ],
        )
        self.mock_llm.generate_structured.return_value = mock_payload

        response = self.agent.respond(query=query, intent=intent)

        # Verify only grounded citation was retained
        self.assertEqual(len(response.citations), 1)
        self.assertEqual(response.citations[0].document_title, "CTD Sensor Principles")

    # ===================================================================
    # 7. Visualization Grounding: Columns Validation and Rejection
    # ===================================================================

    def test_09_visualization_rejection_when_columns_missing(self):
        """Verify visualization is rejected if result columns do not support a valid chart."""
        query = "List unique platform numbers."
        intent = QueryIntent(intent_type=IntentType.DATA_ONLY, intent_category=IntentCategory.FILTERING)

        # Columns only contain ID - no metric or coordinates
        db_result = DatabaseExecutionResult(
            status=ExecutionStatus.SUCCESS,
            columns=["wmo_id"],
            rows=[{"wmo_id": 2901333}, {"wmo_id": 2901334}, {"wmo_id": 2901335}],
            row_count=3,
        )

        mock_payload = _LLMResponsePayload(
            answer="Retrieved 3 platform IDs: 2901333, 2901334, 2901335.",
            citations=[],
        )
        self.mock_llm.generate_structured.return_value = mock_payload

        response = self.agent.respond(query=query, intent=intent, db_result=db_result)

        self.assertIsNone(response.visualization_spec)

    def test_10_visualization_map_grounding(self):
        """Verify map visualization generated when latitude and longitude columns are present."""
        query = "Show profile locations in the Arabian Sea."
        db_result = DatabaseExecutionResult(
            status=ExecutionStatus.SUCCESS,
            columns=["latitude", "longitude", "platform_number"],
            rows=[
                {"latitude": 12.5, "longitude": 65.2, "platform_number": 2901333},
                {"latitude": 13.0, "longitude": 66.0, "platform_number": 2901333},
                {"latitude": 14.1, "longitude": 67.5, "platform_number": 2901334},
            ],
            row_count=3,
        )

        mock_payload = _LLMResponsePayload(
            answer="Profile locations in the Arabian Sea are displayed on the map.",
            citations=[],
        )
        self.mock_llm.generate_structured.return_value = mock_payload

        response = self.agent.respond(query=query, db_result=db_result)

        self.assertIsNotNone(response.visualization_spec)
        self.assertIsNotNone(response.visualization_spec.data)
        self.assertTrue(len(response.visualization_spec.data) > 0)
        self.assertEqual(response.visualization_spec.chart_type, ChartType.MAP)
        self.assertEqual(response.visualization_spec.x_axis, "longitude")
        self.assertEqual(response.visualization_spec.y_axis, "latitude")
        self.assertFalse(response.visualization_spec.invert_y)

    def test_11_visualization_salinity_profile_grounding(self):
        """Verify vertical salinity profile visualization with inverted pressure axis."""
        query = "Plot salinity profile for cycle 5."
        db_result = DatabaseExecutionResult(
            status=ExecutionStatus.SUCCESS,
            columns=["pres", "psal"],
            rows=[
                {"pres": 5.0, "psal": 35.2},
                {"pres": 100.0, "psal": 35.8},
                {"pres": 1000.0, "psal": 34.9},
            ],
            row_count=3,
        )

        mock_payload = _LLMResponsePayload(
            answer="Salinity profile shows maximum salinity of 35.8 at 100 dbar.",
            citations=[],
        )
        self.mock_llm.generate_structured.return_value = mock_payload

        response = self.agent.respond(query=query, db_result=db_result)

        self.assertIsNotNone(response.visualization_spec)
        self.assertIsNotNone(response.visualization_spec.data)
        self.assertTrue(len(response.visualization_spec.data) > 0)
        self.assertEqual(response.visualization_spec.chart_type, ChartType.LINE)
        self.assertEqual(response.visualization_spec.x_axis, "psal")
        self.assertEqual(response.visualization_spec.y_axis, "pres")
        self.assertTrue(response.visualization_spec.invert_y)

    # ===================================================================
    # 8. Graceful Handling of Model Errors (Deterministic Fallback)
    # ===================================================================

    def test_12_llm_timeout_triggers_deterministic_fallback(self):
        """Verify agent falls back to deterministic summary when LLM times out."""
        query = "What are the temperature observations?"
        intent = QueryIntent(intent_type=IntentType.DATA_ONLY, intent_category=IntentCategory.FILTERING)

        db_result = DatabaseExecutionResult(
            status=ExecutionStatus.SUCCESS,
            columns=["pres", "temp"],
            rows=[
                {"pres": 10.0, "temp": 28.5},
                {"pres": 100.0, "temp": 22.0},
            ],
            row_count=2,
        )

        # Simulate LLM timeout error
        self.mock_llm.generate_structured.side_effect = LLMTimeoutError("Ollama inference timed out after 30s")

        response = self.agent.respond(query=query, intent=intent, db_result=db_result)

        self.assertEqual(response.status, ResponseStatus.DEGRADED)
        self.assertTrue(any("fallback" in w.lower() for w in response.warnings))
        self.assertIn("Observational Data Results", response.answer)
        self.assertIn("28.5", response.answer)
        self.assertIsNotNone(response.data_summary)
        self.assertIsNotNone(response.visualization_spec)
        self.assertIsNotNone(response.visualization_spec.data)
        self.assertTrue(len(response.visualization_spec.data) > 0)

    def test_13_empty_query_returns_error_status(self):
        """Verify empty query string yields immediate clean error response."""
        response = self.agent.respond(query="")
        self.assertEqual(response.status, ResponseStatus.ERROR)
        self.assertIn("No query provided", response.answer)

    # ===================================================================
    # 9. Deterministic Data Summary Accuracy
    # ===================================================================

    def test_14_deterministic_data_summary_statistics(self):
        """Verify exact deterministic calculations for min, max, mean and spatial/temporal bounds."""
        db_result = DatabaseExecutionResult(
            status=ExecutionStatus.SUCCESS,
            columns=["pres", "temp", "latitude", "longitude", "timestamp"],
            rows=[
                {"pres": 10.0, "temp": 20.0, "latitude": 10.0, "longitude": 60.0, "timestamp": "2024-01-10T12:00:00Z"},
                {"pres": 50.0, "temp": 30.0, "latitude": 15.0, "longitude": 65.0, "timestamp": "2024-01-20T12:00:00Z"},
            ],
            row_count=2,
        )

        summary = self.agent._build_data_summary(db_result)

        self.assertEqual(summary.total_records, 2)
        # Check temp min/max/mean
        temp_hl = next(h for h in summary.highlights if "temp:" in h)
        self.assertIn("min=20.00", temp_hl)
        self.assertIn("max=30.00", temp_hl)
        self.assertIn("mean=25.00", temp_hl)
        self.assertEqual(summary.spatial_coverage, "Lat: [10.00, 15.00], Lon: [60.00, 65.00]")
        self.assertEqual(summary.temporal_coverage, "2024-01-10 to 2024-01-20")

    def test_15_visualization_single_row_rejected(self):
        """Verify visualization is rejected when database result contains only 1 row."""
        query = "Get single observation."
        db_result = DatabaseExecutionResult(
            status=ExecutionStatus.SUCCESS,
            columns=["pres", "temp"],
            rows=[{"pres": 10.0, "temp": 25.0}],
            row_count=1,
        )

        mock_payload = _LLMResponsePayload(
            answer="Single measurement: 25.0°C at 10 dbar.",
            citations=[],
        )
        self.mock_llm.generate_structured.return_value = mock_payload

        response = self.agent.respond(query=query, db_result=db_result)
        self.assertIsNone(response.visualization_spec)

    def test_16_time_series_visualization_grounding(self):
        """Verify time-series visualization generated with timestamp and temperature."""
        query = "Plot temperature trend over time."
        db_result = DatabaseExecutionResult(
            status=ExecutionStatus.SUCCESS,
            columns=["timestamp", "temp"],
            rows=[
                {"timestamp": "2024-01-01", "temp": 28.0},
                {"timestamp": "2024-01-05", "temp": 27.5},
                {"timestamp": "2024-01-10", "temp": 27.0},
            ],
            row_count=3,
        )

        mock_payload = _LLMResponsePayload(
            answer="Temperature trend shows a slight cooling from 28.0°C to 27.0°C.",
            citations=[],
        )
        self.mock_llm.generate_structured.return_value = mock_payload

        response = self.agent.respond(query=query, db_result=db_result)

        self.assertIsNotNone(response.visualization_spec)
        self.assertIsNotNone(response.visualization_spec.data)
        self.assertTrue(len(response.visualization_spec.data) > 0)
        self.assertEqual(response.visualization_spec.chart_type, ChartType.LINE)
        self.assertEqual(response.visualization_spec.x_axis, "timestamp")
        self.assertEqual(response.visualization_spec.y_axis, "temp")
        self.assertFalse(response.visualization_spec.invert_y)

    def test_17_bar_chart_distribution_grounding(self):
        """Verify bar chart visualization generated for categorical distributions."""
        query = "Count profiles per platform."
        db_result = DatabaseExecutionResult(
            status=ExecutionStatus.SUCCESS,
            columns=["platform_number", "profile_count"],
            rows=[
                {"platform_number": 2901333, "profile_count": 15},
                {"platform_number": 2901334, "profile_count": 22},
            ],
            row_count=2,
        )

        mock_payload = _LLMResponsePayload(
            answer="Float 2901333 has 15 profiles and float 2901334 has 22 profiles.",
            citations=[],
        )
        self.mock_llm.generate_structured.return_value = mock_payload

        response = self.agent.respond(query=query, db_result=db_result)

        self.assertIsNotNone(response.visualization_spec)
        self.assertIsNotNone(response.visualization_spec.data)
        self.assertTrue(len(response.visualization_spec.data) > 0)
        self.assertEqual(response.visualization_spec.chart_type, ChartType.BAR)
        self.assertEqual(response.visualization_spec.x_axis, "platform_number")
        self.assertEqual(response.visualization_spec.y_axis, "profile_count")

    def test_18_custom_top_k_and_similarity_threshold_passed_to_retriever(self):
        """Verify custom top_k and similarity_threshold parameters are passed to retriever."""
        query = "Explain CTD calibration standards."
        intent = QueryIntent(intent_type=IntentType.KNOWLEDGE_ONLY, intent_category=IntentCategory.RETRIEVAL)

        self.mock_retriever.retrieve.return_value = RetrievalResult(
            query=query,
            chunks=[
                RetrievedChunk(
                    chunk_id=1,
                    document_title="ARGO User Manual",
                    section_title="Calibration",
                    chunk_content="Sensor calibration occurs before deployment.",
                    similarity_score=0.92,
                )
            ],
            total_found=1,
            status="success",
        )

        mock_payload = _LLMResponsePayload(
            answer="CTD calibration is performed prior to deployment [ARGO User Manual, Calibration].",
            citations=[Citation(document_title="ARGO User Manual", section_title="Calibration")],
        )
        self.mock_llm.generate_structured.return_value = mock_payload

        self.agent.respond(query=query, intent=intent, top_k=6, similarity_threshold=0.82)

        self.mock_retriever.retrieve.assert_called_once_with(
            query=query,
            top_k=6,
            similarity_threshold=0.82,
            raise_on_error=False,
        )

    def test_19_truncated_result_set_reflected_in_summary(self):
        """Verify truncated result set is properly reflected in DataSummary."""
        db_result = DatabaseExecutionResult(
            status=ExecutionStatus.SUCCESS,
            columns=["pres", "temp"],
            rows=[{"pres": 10.0, "temp": 28.0}, {"pres": 20.0, "temp": 27.5}],
            row_count=2,
            is_truncated=True,
        )

        mock_payload = _LLMResponsePayload(
            answer="Truncated data showing first 2 measurements.",
            citations=[],
        )
        self.mock_llm.generate_structured.return_value = mock_payload

        response = self.agent.respond(query="Show temp", db_result=db_result)
        self.assertEqual(response.data_summary.total_records, 2)

    # ===================================================================
    # 8. Salinity Visualization Spec Grounding & NULL Handling Tests
    # ===================================================================

    def test_20_salinity_visualization_with_psal_column(self):
        """Verify candidate visualization is generated when column is named 'psal'."""
        db_result = DatabaseExecutionResult(
            status=ExecutionStatus.SUCCESS,
            columns=["pressure_dbar", "psal", "platform_number"],
            rows=[
                {"pressure_dbar": 10.0, "psal": 35.2, "platform_number": "2901333"},
                {"pressure_dbar": 50.0, "psal": 35.4, "platform_number": "2901333"},
                {"pressure_dbar": 100.0, "psal": 35.8, "platform_number": "2901333"},
            ],
            row_count=3,
        )
        spec = self.agent._build_visualization_spec(db_result)
        self.assertIsNotNone(spec)
        self.assertEqual(spec.chart_type, ChartType.LINE)
        self.assertEqual(spec.x_axis, "psal")
        self.assertEqual(spec.y_axis, "pressure_dbar")
        self.assertTrue(spec.invert_y)
        self.assertEqual(spec.series_column, "platform_number")

    def test_21_salinity_visualization_with_salinity_column(self):
        """Verify candidate visualization is generated when column is named 'salinity'."""
        db_result = DatabaseExecutionResult(
            status=ExecutionStatus.SUCCESS,
            columns=["pressure_dbar", "salinity", "platform_number"],
            rows=[
                {"pressure_dbar": 15.0, "salinity": 36.1, "platform_number": "2901333"},
                {"pressure_dbar": 60.0, "salinity": 36.3, "platform_number": "2901333"},
            ],
            row_count=2,
        )
        spec = self.agent._build_visualization_spec(db_result)
        self.assertIsNotNone(spec)
        self.assertEqual(spec.chart_type, ChartType.LINE)
        self.assertEqual(spec.x_axis, "salinity")
        self.assertEqual(spec.y_axis, "pressure_dbar")
        self.assertTrue(spec.invert_y)

    def test_22_salinity_visualization_with_salinity_psu_column(self):
        """Verify candidate visualization is generated when column is canonical 'salinity_psu'."""
        db_result = DatabaseExecutionResult(
            status=ExecutionStatus.SUCCESS,
            columns=["pressure_dbar", "salinity_psu", "platform_number"],
            rows=[
                {"pressure_dbar": 20.0, "salinity_psu": 35.5, "platform_number": "1902672"},
                {"pressure_dbar": 80.0, "salinity_psu": 35.7, "platform_number": "1902672"},
            ],
            row_count=2,
        )
        spec = self.agent._build_visualization_spec(db_result)
        self.assertIsNotNone(spec)
        self.assertEqual(spec.chart_type, ChartType.LINE)
        self.assertEqual(spec.x_axis, "salinity_psu")
        self.assertEqual(spec.y_axis, "pressure_dbar")
        self.assertTrue(spec.invert_y)

    def test_23_salinity_visualization_null_handling(self):
        """Verify NULL salinity is preserved without converting to zero, and omitted when all are NULL."""
        # Case A: Partial NULLs -> usable values exist, trace is generated with column preserved (not zeroed)
        db_partial_null = DatabaseExecutionResult(
            status=ExecutionStatus.SUCCESS,
            columns=["pressure_dbar", "salinity_psu"],
            rows=[
                {"pressure_dbar": 10.0, "salinity_psu": 35.1},
                {"pressure_dbar": 50.0, "salinity_psu": None},  # Missing measurement
                {"pressure_dbar": 100.0, "salinity_psu": 35.6},
            ],
            row_count=3,
        )
        spec_partial = self.agent._build_visualization_spec(db_partial_null)
        self.assertIsNotNone(spec_partial)
        self.assertEqual(spec_partial.x_axis, "salinity_psu")

        # Verify data summary does NOT convert NULL into 0.0
        summary = self.agent._build_data_summary(db_partial_null)
        self.assertIsNotNone(summary)
        sal_hl = next(h for h in summary.highlights if "salinity_psu" in h)
        self.assertIn("min=35.10", sal_hl)
        self.assertNotIn("min=0.00", sal_hl)

        # Case B: 100% NULLs -> no usable salinity values, trace is omitted
        db_all_null = DatabaseExecutionResult(
            status=ExecutionStatus.SUCCESS,
            columns=["pressure_dbar", "salinity_psu"],
            rows=[
                {"pressure_dbar": 10.0, "salinity_psu": None},
                {"pressure_dbar": 50.0, "salinity_psu": None},
            ],
            row_count=2,
        )
        spec_all_null = self.agent._build_visualization_spec(db_all_null)
        self.assertIsNone(spec_all_null, "Trace should be omitted when no usable salinity values exist")

    def test_24_visualization_without_salinity_column(self):
        """Verify visualization behavior when salinity column is completely absent."""
        # With pressure and temperature -> produces temperature profile
        db_temp_only = DatabaseExecutionResult(
            status=ExecutionStatus.SUCCESS,
            columns=["pressure_dbar", "temperature_c"],
            rows=[
                {"pressure_dbar": 10.0, "temperature_c": 28.0},
                {"pressure_dbar": 50.0, "temperature_c": 24.5},
            ],
            row_count=2,
        )
        spec_temp = self.agent._build_visualization_spec(db_temp_only)
        self.assertIsNotNone(spec_temp)
        self.assertEqual(spec_temp.x_axis, "temperature_c")

        # Without any physical variable columns -> returns None
        db_no_var = DatabaseExecutionResult(
            status=ExecutionStatus.SUCCESS,
            columns=["measurement_id", "profile_id"],
            rows=[
                {"measurement_id": 1, "profile_id": "P1"},
                {"measurement_id": 2, "profile_id": "P2"},
            ],
            row_count=2,
        )
        spec_no_var = self.agent._build_visualization_spec(db_no_var)
        self.assertIsNone(spec_no_var)

    def test_25_deterministic_aggregate_fast_path(self):
        """Verify that simple aggregate counts on DATA_ONLY synthesize response without invoking LLM."""
        intent = QueryIntent(
            intent_type=IntentType.DATA_ONLY,
            intent_category=IntentCategory.AGGREGATION,
            aggregation_operation=AggregationOp.COUNT,
            target_entity="floats",
        )
        db_result = DatabaseExecutionResult(
            status=ExecutionStatus.SUCCESS,
            columns=["total_floats"],
            rows=[{"total_floats": 30}],
            row_count=1,
        )
        res = self.agent.respond("How many ARGO floats are currently stored in the database?", intent=intent, db_result=db_result)
        self.assertEqual(res.status, ResponseStatus.SUCCESS)
        self.assertIn("30 floats", res.answer)
        self.mock_llm.generate_structured.assert_not_called()

    def test_26_deterministic_aggregate_profile_count(self):
        """Verify profile count query produces 107 ocean profiles without LLM call."""
        intent = QueryIntent(
            intent_type=IntentType.DATA_ONLY,
            intent_category=IntentCategory.AGGREGATION,
            aggregation_operation=AggregationOp.COUNT,
            target_entity="profiles",
        )
        db_result = DatabaseExecutionResult(
            status=ExecutionStatus.SUCCESS,
            columns=["total_profiles"],
            rows=[{"total_profiles": 107}],
            row_count=1,
        )
        res = self.agent.respond("How many total profiles are in the database?", intent=intent, db_result=db_result)
        self.assertEqual(res.status, ResponseStatus.SUCCESS)
        self.assertIn("107 ocean profiles", res.answer)
        self.mock_llm.generate_structured.assert_not_called()

    def test_27_deterministic_aggregate_measurement_count(self):
        """Verify measurement count query produces 26,046 measurements with commas."""
        intent = QueryIntent(
            intent_type=IntentType.DATA_ONLY,
            intent_category=IntentCategory.AGGREGATION,
            aggregation_operation=AggregationOp.COUNT,
            target_entity="measurements",
        )
        db_result = DatabaseExecutionResult(
            status=ExecutionStatus.SUCCESS,
            columns=["total_measurements"],
            rows=[{"total_measurements": 26046}],
            row_count=1,
        )
        res = self.agent.respond("How many measurements are in the database?", intent=intent, db_result=db_result)
        self.assertEqual(res.status, ResponseStatus.SUCCESS)
        self.assertIn("26,046 measurements", res.answer)
        self.mock_llm.generate_structured.assert_not_called()

    def test_28_filtered_count_does_not_use_inventory_fast_path(self):
        """Verify that filtered count query does not produce unfiltered inventory text."""
        intent = QueryIntent(
            intent_type=IntentType.DATA_ONLY,
            intent_category=IntentCategory.AGGREGATION,
            aggregation_operation=AggregationOp.COUNT,
            target_entity="profiles",
            spatial_bounds=SpatialBounds(latitude_min=10.0, latitude_max=20.0),
        )
        db_result = DatabaseExecutionResult(
            status=ExecutionStatus.SUCCESS,
            columns=["profile_count"],
            rows=[{"profile_count": 15}],
            row_count=1,
        )
        self.mock_llm.generate_structured.return_value = _LLMResponsePayload(
            answer="There are 15 profiles in the northern latitude band.",
            citations=[],
        )
        res = self.agent.respond("How many profiles between latitude 10 and 20?", intent=intent, db_result=db_result)
        self.assertEqual(res.status, ResponseStatus.SUCCESS)
        self.mock_llm.generate_structured.assert_called_once()
        self.assertNotIn("The ARGO database currently stores", res.answer)

    def test_29_malformed_or_failed_aggregate_does_not_fabricate(self):
        """Verify that malformed or failed aggregate result does not produce fabricated inventory count."""
        intent = QueryIntent(
            intent_type=IntentType.DATA_ONLY,
            intent_category=IntentCategory.AGGREGATION,
            aggregation_operation=AggregationOp.COUNT,
            target_entity="floats",
        )
        # 1. Failed db_result
        self.mock_llm.generate_structured.return_value = _LLMResponsePayload(
            answer="Database query failed to execute.",
            citations=[],
        )
        db_failed = DatabaseExecutionResult(
            status=ExecutionStatus.EXECUTION_FAILED,
            error_message="Query timed out",
            columns=[],
            rows=[],
            row_count=0,
        )
        res_failed = self.agent.respond("How many floats are in the database?", intent=intent, db_result=db_failed)
        self.assertNotIn("The ARGO database currently stores", res_failed.answer)

        # 2. Malformed non-numeric count row
        db_malformed = DatabaseExecutionResult(
            status=ExecutionStatus.SUCCESS,
            columns=["total_floats"],
            rows=[{"total_floats": "not_a_number"}],
            row_count=1,
        )
        self.mock_llm.generate_structured.return_value = _LLMResponsePayload(
            answer="The query returned an unformatted non-numeric response.",
            citations=[],
        )
        res_malformed = self.agent.respond("How many floats?", intent=intent, db_result=db_malformed)
        self.assertNotIn("The ARGO database currently stores not_a_number", res_malformed.answer)

    # ===================================================================
    # Stage 5B: Pre-Retrieved Chunks & Graph Compatibility Tests
    # ===================================================================

    def test_30_pre_retrieved_chunks_prevents_duplicate_retrieval(self):
        """Verify that supplying pre_retrieved_chunks skips internal retriever invocation."""
        intent = QueryIntent(
            intent_type=IntentType.HYBRID,
            intent_category=IntentCategory.COMBINED,
        )
        pre_chunk = RetrievedChunk(
            chunk_id=101,
            document_title="ARGO User Manual",
            section_title="Data Processing",
            chunk_content="ARGO floats measure ocean parameters using automated CTD sensors.",
            similarity_score=0.91,
        )
        self.mock_llm.generate_structured.return_value = _LLMResponsePayload(
            answer="CTD sensors record automated ocean measurements [ARGO User Manual, Data Processing].",
            citations=[{"document_title": "ARGO User Manual", "section_title": "Data Processing"}],
        )

        res = self.agent.respond(
            query="Explain ARGO CTD sensors",
            intent=intent,
            pre_retrieved_chunks=[pre_chunk],
        )

        # CRITICAL: Verify retriever.retrieve was NOT called
        self.mock_retriever.retrieve.assert_not_called()
        self.assertEqual(res.status, ResponseStatus.SUCCESS)
        self.assertEqual(len(res.citations), 1)
        self.assertEqual(res.citations[0].document_title, "ARGO User Manual")

    def test_31_explicit_empty_pre_retrieved_chunks_does_not_trigger_retrieval(self):
        """Verify that an explicitly supplied empty list of pre_retrieved_chunks does NOT trigger retriever."""
        intent = QueryIntent(
            intent_type=IntentType.HYBRID,
            intent_category=IntentCategory.COMBINED,
        )
        self.mock_llm.generate_structured.return_value = _LLMResponsePayload(
            answer="General response without specific document citations.",
            citations=[],
        )

        res = self.agent.respond(
            query="Explain ARGO CTD sensors",
            intent=intent,
            pre_retrieved_chunks=[],
        )

        # CRITICAL: Verify retriever.retrieve was NOT called despite empty list
        self.mock_retriever.retrieve.assert_not_called()
        self.assertIn("No scientific documents met the similarity threshold.", res.warnings)

    def test_32_standalone_call_without_pre_retrieved_chunks_preserves_retrieval(self):
        """Verify that omitting pre_retrieved_chunks (None) preserves standard retriever invocation."""
        intent = QueryIntent(
            intent_type=IntentType.KNOWLEDGE_ONLY,
            intent_category=IntentCategory.RETRIEVAL,
        )
        retrieved_chunk = RetrievedChunk(
            chunk_id=202,
            document_title="CTD Principles",
            section_title="Salinity",
            chunk_content="Salinity is computed from conductivity and temperature.",
            similarity_score=0.88,
        )
        self.mock_retriever.retrieve.return_value = RetrievalResult(
            query="How is salinity computed?",
            chunks=[retrieved_chunk],
            total_found=1,
            status="success",
        )
        self.mock_llm.generate_structured.return_value = _LLMResponsePayload(
            answer="Salinity is derived from conductivity and temperature [CTD Principles, Salinity].",
            citations=[{"document_title": "CTD Principles", "section_title": "Salinity"}],
        )

        res = self.agent.respond(
            query="How is salinity computed?",
            intent=intent,
            pre_retrieved_chunks=None,
        )

        # Retriever must be called when pre_retrieved_chunks is None
        self.mock_retriever.retrieve.assert_called_once()
        self.assertEqual(res.status, ResponseStatus.SUCCESS)
        self.assertEqual(len(res.citations), 1)

    def test_33_citations_grounded_in_pre_retrieved_chunks(self):
        """Verify anti-hallucination citation filtering against supplied pre-retrieved chunks."""
        intent = QueryIntent(
            intent_type=IntentType.HYBRID,
            intent_category=IntentCategory.COMBINED,
        )
        valid_chunk = RetrievedChunk(
            chunk_id=303,
            document_title="Authoritative Ocean Manual",
            section_title="Section 1",
            chunk_content="Valid scientific documentation content.",
            similarity_score=0.95,
        )
        # LLM returns one valid citation and one fabricated citation
        self.mock_llm.generate_structured.return_value = _LLMResponsePayload(
            answer="Documented content [Authoritative Ocean Manual, Section 1] and hallucinated claim [Fake Source, Page 99].",
            citations=[
                {"document_title": "Authoritative Ocean Manual", "section_title": "Section 1"},
                {"document_title": "Fake Source", "section_title": "Page 99"},
            ],
        )

        res = self.agent.respond(
            query="Authoritative topic query",
            intent=intent,
            pre_retrieved_chunks=[valid_chunk],
        )

        # Fake citation must be filtered out
        self.assertEqual(len(res.citations), 1)
        self.assertEqual(res.citations[0].document_title, "Authoritative Ocean Manual")

    # ===================================================================
    # 10. Stage 8B Phase 4: Deterministic Summary & Calculation Tests
    # ===================================================================

    def test_34_zero_versus_none_handling(self):
        """Verify 0.0 is treated as a valid numeric measurement and None is counted as missing."""
        db_result = DatabaseExecutionResult(
            status=ExecutionStatus.SUCCESS,
            columns=["temperature_c"],
            rows=[
                {"temperature_c": 0.0},
                {"temperature_c": None},
                {"temperature_c": 10.0},
            ],
            row_count=3,
        )
        summary = self.agent._build_data_summary(db_result)
        self.assertEqual(summary.null_counts.get("temperature_c"), 1)
        temp_hl = next(h for h in summary.highlights if "temperature_c:" in h)
        self.assertIn("min=0.00", temp_hl)
        self.assertIn("max=10.00", temp_hl)
        self.assertIn("mean=5.00", temp_hl)
        self.assertTrue(any("Missing values for temperature_c: 1 of 3 records null" in h for h in summary.highlights))

    def test_35_non_finite_and_invalid_numeric_exclusion(self):
        """Verify NaN, infinity, booleans, and non-numeric strings are excluded from calculations."""
        db_result = DatabaseExecutionResult(
            status=ExecutionStatus.SUCCESS,
            columns=["temperature_c"],
            rows=[
                {"temperature_c": float("nan")},
                {"temperature_c": float("inf")},
                {"temperature_c": float("-inf")},
                {"temperature_c": True},
                {"temperature_c": "invalid"},
                {"temperature_c": 25.0},
            ],
            row_count=6,
        )
        summary = self.agent._build_data_summary(db_result)
        temp_hl = next(h for h in summary.highlights if "temperature_c:" in h)
        self.assertIn("min=25.00", temp_hl)
        self.assertIn("max=25.00", temp_hl)
        self.assertIn("mean=25.00", temp_hl)
        self.assertIn("median=25.00", temp_hl)
        # Verify non-None invalid values are not mistakenly added to null_counts
        self.assertEqual(summary.null_counts.get("temperature_c", 0), 0)

    def test_36_median_calculation(self):
        """Verify median calculation for odd and even observation sample counts."""
        # Odd count: median is the middle value (20.0)
        db_odd = DatabaseExecutionResult(
            status=ExecutionStatus.SUCCESS,
            columns=["temperature_c"],
            rows=[{"temperature_c": 10.0}, {"temperature_c": 20.0}, {"temperature_c": 30.0}],
            row_count=3,
        )
        summary_odd = self.agent._build_data_summary(db_odd)
        temp_hl_odd = next(h for h in summary_odd.highlights if "temperature_c:" in h)
        self.assertIn("median=20.00", temp_hl_odd)

        # Even count: median is the mean of two middle values (25.0)
        db_even = DatabaseExecutionResult(
            status=ExecutionStatus.SUCCESS,
            columns=["temperature_c"],
            rows=[{"temperature_c": 10.0}, {"temperature_c": 20.0}, {"temperature_c": 30.0}, {"temperature_c": 40.0}],
            row_count=4,
        )
        summary_even = self.agent._build_data_summary(db_even)
        temp_hl_even = next(h for h in summary_even.highlights if "temperature_c:" in h)
        self.assertIn("median=25.00", temp_hl_even)

    def test_37_sample_standard_deviation_and_variance_accuracy(self):
        """Verify exact sample standard deviation and variance for sample sizes >= 2."""
        # Population: [10.0, 20.0, 30.0] -> mean=20.0, variance=100.0, stdev=10.0
        db_result = DatabaseExecutionResult(
            status=ExecutionStatus.SUCCESS,
            columns=["temperature_c"],
            rows=[{"temperature_c": 10.0}, {"temperature_c": 20.0}, {"temperature_c": 30.0}],
            row_count=3,
        )
        summary = self.agent._build_data_summary(db_result)
        temp_hl = next(h for h in summary.highlights if "temperature_c:" in h)
        self.assertIn("stddev=10.00 °C", temp_hl)
        self.assertIn("var=100.00", temp_hl)

    def test_38_single_observation_standard_deviation_and_variance_handling(self):
        """Verify sample standard deviation and variance are omitted for single-observation datasets."""
        db_result = DatabaseExecutionResult(
            status=ExecutionStatus.SUCCESS,
            columns=["temperature_c"],
            rows=[{"temperature_c": 25.0}],
            row_count=1,
        )
        summary = self.agent._build_data_summary(db_result)
        temp_hl = next(h for h in summary.highlights if "temperature_c:" in h)
        self.assertIn("min=25.00", temp_hl)
        self.assertIn("max=25.00", temp_hl)
        self.assertIn("mean=25.00", temp_hl)
        self.assertIn("median=25.00", temp_hl)
        self.assertNotIn("stddev=", temp_hl)
        self.assertNotIn("var=", temp_hl)

    def test_39_physical_units_attached_to_temperature_salinity_pressure(self):
        """Verify oceanographic units are correctly attached to supported variables only."""
        db_result = DatabaseExecutionResult(
            status=ExecutionStatus.SUCCESS,
            columns=["temperature_c", "salinity_psu", "pressure_dbar", "platform_number"],
            rows=[
                {"temperature_c": 22.0, "salinity_psu": 35.5, "pressure_dbar": 100.0, "platform_number": "1902671"},
                {"temperature_c": 24.0, "salinity_psu": 35.7, "pressure_dbar": 200.0, "platform_number": "1902671"},
            ],
            row_count=2,
        )
        summary = self.agent._build_data_summary(db_result)
        temp_hl = next(h for h in summary.highlights if "temperature_c:" in h)
        sal_hl = next(h for h in summary.highlights if "salinity_psu:" in h)
        pres_hl = next(h for h in summary.highlights if "pressure_dbar:" in h)

        self.assertIn("°C", temp_hl)
        self.assertIn("PSU", sal_hl)
        self.assertIn("dbar", pres_hl)

    def test_40_null_counts_populated_for_relevant_measurements(self):
        """Verify null counts are accurately populated and disclosed in summary highlights."""
        db_result = DatabaseExecutionResult(
            status=ExecutionStatus.SUCCESS,
            columns=["salinity_psu"],
            rows=[
                {"salinity_psu": 35.0},
                {"salinity_psu": None},
                {"salinity_psu": 35.2},
                {"salinity_psu": None},
                {"salinity_psu": 35.4},
            ],
            row_count=5,
        )
        summary = self.agent._build_data_summary(db_result)
        self.assertEqual(summary.null_counts.get("salinity_psu"), 2)
        self.assertTrue(any("Missing values for salinity_psu: 2 of 5 records null" in h for h in summary.highlights))

    def test_41_truncated_result_sample_disclosure(self):
        """Verify is_truncated=True results are clearly disclosed as sample subsets."""
        db_result = DatabaseExecutionResult(
            status=ExecutionStatus.SUCCESS,
            columns=["temperature_c"],
            rows=[{"temperature_c": 20.0 + i} for i in range(100)],
            row_count=100,
            is_truncated=True,
        )
        summary = self.agent._build_data_summary(db_result)
        self.assertTrue(summary.is_truncated)
        self.assertEqual(summary.sample_size, 100)
        self.assertTrue(
            any("Analyzed sample size: 100 records (truncated query result; total matching observation count in database is unknown)." in h for h in summary.highlights)
        )

        # Also verify deterministic fallback wording
        fallback_text, _ = self.agent._build_deterministic_fallback("Show temp", [], db_result, summary)
        self.assertIn("A sample of **100** observation records was analyzed", fallback_text)
        self.assertIn("total database matches unknown", fallback_text)

    def test_42_complete_result_disclosure(self):
        """Verify non-truncated results report total observation count accurately."""
        db_result = DatabaseExecutionResult(
            status=ExecutionStatus.SUCCESS,
            columns=["temperature_c"],
            rows=[{"temperature_c": 22.0}, {"temperature_c": 24.0}],
            row_count=2,
            is_truncated=False,
        )
        summary = self.agent._build_data_summary(db_result)
        self.assertFalse(summary.is_truncated)
        self.assertIsNone(summary.sample_size)
        self.assertIn("Total matching observation rows: 2", summary.highlights)

        fallback_text, _ = self.agent._build_deterministic_fallback("Show temp", [], db_result, summary)
        self.assertIn("A total of **2** observation records were retrieved", fallback_text)

    def test_43_exact_limit_sized_non_truncated_result(self):
        """Verify exactly 500 rows with is_truncated=False is not falsely marked truncated."""
        db_result = DatabaseExecutionResult(
            status=ExecutionStatus.SUCCESS,
            columns=["temperature_c"],
            rows=[{"temperature_c": 25.0}] * 500,
            row_count=500,
            is_truncated=False,
        )
        summary = self.agent._build_data_summary(db_result)
        self.assertFalse(summary.is_truncated)
        self.assertIsNone(summary.sample_size)
        self.assertIn("Total matching observation rows: 500", summary.highlights)

    def test_44_epipelagic_boundary_values_0_and_200_dbar(self):
        """Verify boundary pressures 0.0 and 200.0 dbar are mapped to epipelagic stratum."""
        db_result = DatabaseExecutionResult(
            status=ExecutionStatus.SUCCESS,
            columns=["pressure_dbar", "temperature_c"],
            rows=[
                {"pressure_dbar": 0.0, "temperature_c": 28.0},
                {"pressure_dbar": 200.0, "temperature_c": 20.0},
            ],
            row_count=2,
        )
        summary = self.agent._build_data_summary(db_result)
        self.assertIsNotNone(summary.depth_strata)
        epi = summary.depth_strata["epipelagic"]
        meso = summary.depth_strata["mesopelagic"]
        bathy = summary.depth_strata["bathypelagic"]

        self.assertEqual(epi["observation_count"], 2)
        self.assertEqual(epi["temperature_count"], 2)
        self.assertEqual(epi["temperature_mean_c"], 24.0)
        self.assertEqual(meso["observation_count"], 0)
        self.assertEqual(bathy["observation_count"], 0)

    def test_45_mesopelagic_boundary_values_just_above_200_and_1000_dbar(self):
        """Verify boundary pressures 200.1 and 1000.0 dbar are mapped to mesopelagic stratum."""
        db_result = DatabaseExecutionResult(
            status=ExecutionStatus.SUCCESS,
            columns=["pressure_dbar", "temperature_c"],
            rows=[
                {"pressure_dbar": 200.1, "temperature_c": 19.0},
                {"pressure_dbar": 1000.0, "temperature_c": 7.0},
            ],
            row_count=2,
        )
        summary = self.agent._build_data_summary(db_result)
        self.assertIsNotNone(summary.depth_strata)
        meso = summary.depth_strata["mesopelagic"]
        self.assertEqual(meso["observation_count"], 2)
        self.assertEqual(meso["temperature_count"], 2)
        self.assertEqual(meso["temperature_mean_c"], 13.0)

    def test_46_bathypelagic_values_above_1000_dbar(self):
        """Verify pressures strictly greater than 1000.0 dbar are mapped to bathypelagic stratum."""
        db_result = DatabaseExecutionResult(
            status=ExecutionStatus.SUCCESS,
            columns=["pressure_dbar", "temperature_c"],
            rows=[
                {"pressure_dbar": 1000.1, "temperature_c": 6.9},
                {"pressure_dbar": 1950.0, "temperature_c": 2.5},
            ],
            row_count=2,
        )
        summary = self.agent._build_data_summary(db_result)
        self.assertIsNotNone(summary.depth_strata)
        bathy = summary.depth_strata["bathypelagic"]
        self.assertEqual(bathy["observation_count"], 2)
        self.assertEqual(bathy["temperature_count"], 2)
        self.assertEqual(bathy["temperature_mean_c"], 4.7)

    def test_47_independent_temperature_and_salinity_counts_within_strata(self):
        """Verify temperature and salinity counts and means within depth strata are tracked independently."""
        db_result = DatabaseExecutionResult(
            status=ExecutionStatus.SUCCESS,
            columns=["pressure_dbar", "temperature_c", "salinity_psu"],
            rows=[
                {"pressure_dbar": 50.0, "temperature_c": 26.0, "salinity_psu": 35.5},  # Both present
                {"pressure_dbar": 100.0, "temperature_c": 24.0, "salinity_psu": None}, # Temp only
                {"pressure_dbar": 150.0, "temperature_c": None, "salinity_psu": 35.7}, # Sal only
            ],
            row_count=3,
        )
        summary = self.agent._build_data_summary(db_result)
        self.assertIsNotNone(summary.depth_strata)
        epi = summary.depth_strata["epipelagic"]

        self.assertEqual(epi["observation_count"], 3)
        self.assertEqual(epi["temperature_count"], 2)
        self.assertEqual(epi["temperature_mean_c"], 25.0)
        self.assertEqual(epi["salinity_count"], 2)
        self.assertEqual(epi["salinity_mean_psu"], 35.6)

    def test_48_pre_aggregated_sql_result_handling(self):
        """Verify pre-aggregated SQL results display directly without redundant min/max/mean loops."""
        db_result = DatabaseExecutionResult(
            status=ExecutionStatus.SUCCESS,
            columns=["avg_temperature_c", "std_temperature_c", "observation_count"],
            rows=[{"avg_temperature_c": 24.5, "std_temperature_c": 1.2, "observation_count": 450}],
            row_count=1,
        )
        intent = QueryIntent(
            intent_type=IntentType.DATA_ONLY,
            intent_category=IntentCategory.STATISTICS,
            aggregation_operation=AggregationOp.AVERAGE,
        )
        summary = self.agent._build_data_summary(db_result, intent=intent)
        self.assertEqual(summary.total_records, 1)
        self.assertIsNone(summary.depth_strata)
        self.assertTrue(any("avg_temperature_c: 24.50 °C" in h for h in summary.highlights))
        self.assertTrue(any("std_temperature_c: 1.20 °C" in h for h in summary.highlights))
        self.assertTrue(any("observation_count: 450" in h for h in summary.highlights))
        # Ensure redundant min=..., max=..., mean=... was NOT added
        self.assertFalse(any("min=24.50" in h and "max=24.50" in h for h in summary.highlights))

    def test_49_preservation_of_existing_count_fast_path_and_fallback(self):
        """Verify existing total inventory count fast-path and fallback remain fully operational."""
        db_result = DatabaseExecutionResult(
            status=ExecutionStatus.SUCCESS,
            columns=["total_floats"],
            rows=[{"total_floats": 45}],
            row_count=1,
        )
        intent = QueryIntent(
            intent_type=IntentType.DATA_ONLY,
            intent_category=IntentCategory.AGGREGATION,
            aggregation_operation=AggregationOp.COUNT,
            target_entity="floats",
        )
        response = self.agent.respond(
            query="How many floats in total?",
            intent=intent,
            db_result=db_result,
        )
        self.assertEqual(response.status, ResponseStatus.SUCCESS)
        self.assertIn("The ARGO database currently stores 45 floats.", response.answer)
        self.assertIsNotNone(response.data_summary)
        self.assertTrue(any("total_floats: 45" in h for h in response.data_summary.highlights))

    # 13. Competition Fix 1: Visualization Alias Resolution and Grounding Tests

    def test_50_visualization_aggregate_alias_avg_temperature_profile(self):
        """Verify avg_temperature_c is recognized as physical temperature for vertical profile."""
        db_result = DatabaseExecutionResult(
            status=ExecutionStatus.SUCCESS,
            columns=["pressure_dbar", "avg_temperature_c"],
            rows=[
                {"pressure_dbar": 10.0, "avg_temperature_c": 28.5},
                {"pressure_dbar": 100.0, "avg_temperature_c": 22.1},
            ],
            row_count=2,
        )
        spec = self.agent._build_visualization_spec(db_result)
        self.assertIsNotNone(spec)
        self.assertEqual(spec.chart_type, ChartType.LINE)
        self.assertEqual(spec.x_axis, "avg_temperature_c")
        self.assertEqual(spec.y_axis, "pressure_dbar")
        self.assertTrue(spec.invert_y)
        self.assertEqual(len(spec.data), 2)

    def test_51_visualization_aggregate_alias_time_series(self):
        """Verify mean_temperature_c is recognized as physical temperature for time-series."""
        db_result = DatabaseExecutionResult(
            status=ExecutionStatus.SUCCESS,
            columns=["time", "mean_temperature_c"],
            rows=[
                {"time": "2024-01-01T00:00:00Z", "mean_temperature_c": 24.2},
                {"time": "2024-01-02T00:00:00Z", "mean_temperature_c": 24.8},
            ],
            row_count=2,
        )
        spec = self.agent._build_visualization_spec(db_result)
        self.assertIsNotNone(spec)
        self.assertEqual(spec.chart_type, ChartType.LINE)
        self.assertEqual(spec.x_axis, "time")
        self.assertEqual(spec.y_axis, "mean_temperature_c")
        self.assertFalse(spec.invert_y)

    def test_52_visualization_aggregate_alias_salinity_profile_with_series(self):
        """Verify avg_salinity and mean_pressure generate vertical profile preserving series column."""
        db_result = DatabaseExecutionResult(
            status=ExecutionStatus.SUCCESS,
            columns=["mean_pressure", "avg_salinity", "platform_number"],
            rows=[
                {"mean_pressure": 20.0, "avg_salinity": 35.1, "platform_number": "6901234"},
                {"mean_pressure": 80.0, "avg_salinity": 35.8, "platform_number": "6901234"},
                {"mean_pressure": 20.0, "avg_salinity": 35.0, "platform_number": "6901235"},
            ],
            row_count=3,
        )
        spec = self.agent._build_visualization_spec(db_result)
        self.assertIsNotNone(spec)
        self.assertEqual(spec.chart_type, ChartType.LINE)
        self.assertEqual(spec.x_axis, "avg_salinity")
        self.assertEqual(spec.y_axis, "mean_pressure")
        self.assertTrue(spec.invert_y)
        self.assertEqual(spec.series_column, "platform_number")

    def test_53_visualization_rejects_invalid_count_or_qc_aliases(self):
        """Verify columns with 'count' or 'qc' are not resolved as physical measurement columns."""
        db_result = DatabaseExecutionResult(
            status=ExecutionStatus.SUCCESS,
            columns=["pressure_dbar", "temperature_count", "salinity_qc"],
            rows=[
                {"pressure_dbar": 10.0, "temperature_count": 50, "salinity_qc": 1},
                {"pressure_dbar": 20.0, "temperature_count": 48, "salinity_qc": 1},
            ],
            row_count=2,
        )
        spec = self.agent._build_visualization_spec(db_result)
        # Should not produce a vertical LINE profile because neither temperature_count
        # nor salinity_qc is a valid physical variable column
        self.assertIsNone(spec)

    def test_54_single_row_scalar_aggregate_omits_viz_cleanly(self):
        """Verify single-row scalar aggregate query omits chart cleanly without degrading response."""
        db_result = DatabaseExecutionResult(
            status=ExecutionStatus.SUCCESS,
            columns=["avg_temperature_c"],
            rows=[{"avg_temperature_c": 21.4}],
            row_count=1,
        )
        intent = QueryIntent(
            intent_type=IntentType.DATA_ONLY,
            intent_category=IntentCategory.AGGREGATION,
            aggregation_operation=AggregationOp.AVERAGE,
            target_entity="measurements",
        )
        spec = self.agent._build_visualization_spec(db_result)
        self.assertIsNone(spec)

        self.mock_llm.generate_structured.return_value = _LLMResponsePayload(
            answer="The average ocean temperature is 21.40 °C across all measurements.",
            citations=[],
        )
        response = self.agent.respond(
            query="What is the average temperature?",
            intent=intent,
            db_result=db_result,
        )
        self.assertEqual(response.status, ResponseStatus.SUCCESS)
        self.assertIsNone(response.visualization_spec)
        self.assertTrue(any("avg_temperature_c: 21.40 °C" in h for h in response.data_summary.highlights))
        self.assertTrue(any("Visualization omitted" in h for h in response.data_summary.highlights))

    def test_55_single_row_map_and_bar_allowed(self):
        """Verify single-row results are permitted for map coordinates and categorical bars."""
        # 1. Single row map
        db_map = DatabaseExecutionResult(
            status=ExecutionStatus.SUCCESS,
            columns=["latitude", "longitude", "platform_number"],
            rows=[{"latitude": 15.2, "longitude": 68.4, "platform_number": "6901234"}],
            row_count=1,
        )
        spec_map = self.agent._build_visualization_spec(db_map)
        self.assertIsNotNone(spec_map)
        self.assertEqual(spec_map.chart_type, ChartType.MAP)
        self.assertEqual(spec_map.x_axis, "longitude")
        self.assertEqual(spec_map.y_axis, "latitude")

        # 2. Single row bar with categorical dimension
        db_bar = DatabaseExecutionResult(
            status=ExecutionStatus.SUCCESS,
            columns=["platform_number", "profile_count"],
            rows=[{"platform_number": "6901234", "profile_count": 82}],
            row_count=1,
        )
        spec_bar = self.agent._build_visualization_spec(db_bar)
        self.assertIsNotNone(spec_bar)
        self.assertEqual(spec_bar.chart_type, ChartType.BAR)
        self.assertEqual(spec_bar.x_axis, "platform_number")
        self.assertEqual(spec_bar.y_axis, "profile_count")

    def test_56_preservation_of_basic_canonical_aliases(self):
        """Verify basic physical aliases (temp, psal, pres, lat, lon) continue to resolve correctly."""
        db_result = DatabaseExecutionResult(
            status=ExecutionStatus.SUCCESS,
            columns=["pres", "temp", "psal", "lat", "lon"],
            rows=[
                {"pres": 10.0, "temp": 26.5, "psal": 35.2, "lat": 10.1, "lon": 60.2},
                {"pres": 50.0, "temp": 23.0, "psal": 35.5, "lat": 10.2, "lon": 60.3},
            ],
            row_count=2,
        )
        # Profile preference defaults to temperature profile when both temp & psal are present
        spec = self.agent._build_visualization_spec(db_result)
        self.assertIsNotNone(spec)
        self.assertEqual(spec.chart_type, ChartType.LINE)
        self.assertEqual(spec.x_axis, "temp")
        self.assertEqual(spec.y_axis, "pres")
        self.assertTrue(spec.invert_y)

    def test_57_structured_error_with_recoverable_answer_recovers_without_second_call(self):
        """Verify that when structured output raises an error with recoverable JSON answer, it is recovered without invoking generate()."""
        query = "What is the salinity of float 2901550?"
        intent = QueryIntent(intent_type=IntentType.DATA_ONLY, intent_category=IntentCategory.FILTERING)
        db_result = DatabaseExecutionResult(
            status=ExecutionStatus.SUCCESS,
            columns=["platform_number", "salinity_psu"],
            rows=[{"platform_number": "2901550", "salinity_psu": 35.1}],
            row_count=1,
        )

        from src.llm.exceptions import LLMStructuredOutputError
        raw_output = '{"answer": "Float 2901550 recorded a salinity of 35.1 PSU in the Arabian Sea.", "citations": [{"invalid_key": 123}]}'
        self.mock_llm.generate_structured.side_effect = LLMStructuredOutputError(
            "Validation error on citations",
            raw_text=raw_output,
            finish_reason="stop",
            response_model_name="_LLMResponsePayload",
        )

        response = self.agent.respond(query=query, intent=intent, db_result=db_result)

        self.assertEqual(response.status, ResponseStatus.SUCCESS)
        self.assertIn("Float 2901550 recorded a salinity of 35.1 PSU", response.answer)
        self.mock_llm.generate.assert_not_called()

    def test_58_structured_error_with_truncated_answer_recovers_without_second_call(self):
        """Verify that when structured output is truncated mid-stream, the answer string is recovered without calling generate()."""
        query = "Explain Argo temperature measurement methods."
        intent = QueryIntent(intent_type=IntentType.KNOWLEDGE_ONLY, intent_category=IntentCategory.RETRIEVAL)
        retrieved_chunk = RetrievedChunk(
            chunk_id=1,
            document_title="Argo Float User Manual",
            section_title="Sensors",
            chunk_content="CTD sensors measure conductivity, temperature, and depth.",
            similarity_score=0.92,
        )

        from src.llm.exceptions import LLMStructuredOutputError
        raw_truncated = '{"answer": "Argo floats use high-precision CTD sensors mounted on top of the float hull to record in-situ temperature as they ascend to the surface.'
        self.mock_llm.generate_structured.side_effect = LLMStructuredOutputError(
            "JSON decode error due to truncation",
            raw_text=raw_truncated,
            finish_reason="length",
            response_model_name="_LLMResponsePayload",
        )

        response = self.agent.respond(
            query=query,
            intent=intent,
            pre_retrieved_chunks=[retrieved_chunk],
        )

        self.assertEqual(response.status, ResponseStatus.SUCCESS)
        self.assertIn("Argo floats use high-precision CTD sensors", response.answer)
        self.mock_llm.generate.assert_not_called()

    def test_59_structured_error_finish_reason_length_skips_second_call_and_uses_deterministic_fallback(self):
        """Verify that when structured output hits token limit with unrecoverable answer, it NEVER calls generate() and uses deterministic fallback."""
        query = "What are the latest temperatures?"
        intent = QueryIntent(intent_type=IntentType.DATA_ONLY, intent_category=IntentCategory.FILTERING)
        db_result = DatabaseExecutionResult(
            status=ExecutionStatus.SUCCESS,
            columns=["pres", "temp"],
            rows=[{"pres": 10.0, "temp": 28.5}, {"pres": 50.0, "temp": 24.2}],
            row_count=2,
        )

        from src.llm.exceptions import LLMStructuredOutputError
        self.mock_llm.generate_structured.side_effect = LLMStructuredOutputError(
            "Token limit reached",
            raw_text='{"other_field": 123',
            finish_reason="length",
            response_model_name="_LLMResponsePayload",
        )

        response = self.agent.respond(query=query, intent=intent, db_result=db_result)

        self.assertEqual(response.status, ResponseStatus.DEGRADED)
        self.assertTrue(any("fallback" in w.lower() for w in response.warnings))
        self.assertIn("Observational Data Results", response.answer)
        self.mock_llm.generate.assert_not_called()

    def test_60_structured_error_substantial_raw_text_skips_second_call(self):
        """Verify that when raw_text has >= 100 characters but no valid JSON answer, it does not re-invoke generate()."""
        query = "What are the observations?"
        intent = QueryIntent(intent_type=IntentType.DATA_ONLY, intent_category=IntentCategory.FILTERING)
        db_result = DatabaseExecutionResult(
            status=ExecutionStatus.SUCCESS,
            columns=["pres", "temp"],
            rows=[{"pres": 10.0, "temp": 28.5}],
            row_count=1,
        )

        from src.llm.exceptions import LLMStructuredOutputError
        raw_text_120 = "{" + ("x" * 120)
        self.mock_llm.generate_structured.side_effect = LLMStructuredOutputError(
            "Malformed output",
            raw_text=raw_text_120,
            finish_reason="stop",
            response_model_name="_LLMResponsePayload",
        )

        response = self.agent.respond(query=query, intent=intent, db_result=db_result)

        self.assertEqual(response.status, ResponseStatus.DEGRADED)
        self.mock_llm.generate.assert_not_called()

    def test_61_empty_structured_error_uses_free_form_fallback_if_available(self):
        """Verify that when raw_text is completely empty and finish_reason is not length, free-form fallback is attempted."""
        query = "What are the observations?"
        intent = QueryIntent(intent_type=IntentType.DATA_ONLY, intent_category=IntentCategory.FILTERING)
        db_result = DatabaseExecutionResult(
            status=ExecutionStatus.SUCCESS,
            columns=["pres", "temp"],
            rows=[{"pres": 10.0, "temp": 28.5}],
            row_count=1,
        )

        from src.llm.exceptions import LLMStructuredOutputError
        from src.llm.base import GenerationResult
        self.mock_llm.generate_structured.side_effect = LLMStructuredOutputError(
            "Empty output",
            raw_text="",
            finish_reason="stop",
            response_model_name="_LLMResponsePayload",
        )
        self.mock_llm.generate.return_value = GenerationResult(
            text="Free-form fallback generated answer for Argo measurements.",
            finish_reason="stop",
            model="qwen2.5:1.5b-instruct",
        )

        response = self.agent.respond(query=query, intent=intent, db_result=db_result)

        self.mock_llm.generate.assert_called_once()
        self.assertIn("Free-form fallback generated answer", response.answer)

    def test_62_dynamic_visualization_selection_tests_a_to_e(self):
        """Verify dynamic visualization selection for Tests A through E as required by Fix 6."""
        db_result = DatabaseExecutionResult(
            status=ExecutionStatus.SUCCESS,
            columns=["platform_number", "profile_time", "latitude", "longitude", "pressure_dbar", "temperature_c", "salinity_psu"],
            rows=[
                {"platform_number": "1902671", "profile_time": "2024-01-01T00:00:00Z", "latitude": 15.1, "longitude": 68.2, "pressure_dbar": 5.0, "temperature_c": 28.2, "salinity_psu": 36.2},
                {"platform_number": "1902671", "profile_time": "2024-01-01T00:00:00Z", "latitude": 15.1, "longitude": 68.2, "pressure_dbar": 50.0, "temperature_c": 24.5, "salinity_psu": 35.8},
                {"platform_number": "1902671", "profile_time": "2024-01-01T00:00:00Z", "latitude": 15.1, "longitude": 68.2, "pressure_dbar": 150.0, "temperature_c": 18.0, "salinity_psu": 35.5},
                {"platform_number": "1902671", "profile_time": "2024-01-10T00:00:00Z", "latitude": 15.3, "longitude": 68.4, "pressure_dbar": 5.0, "temperature_c": 27.8, "salinity_psu": 36.1},
                {"platform_number": "1902671", "profile_time": "2024-01-10T00:00:00Z", "latitude": 15.3, "longitude": 68.4, "pressure_dbar": 100.0, "temperature_c": 20.1, "salinity_psu": 35.6},
                {"platform_number": "1902671", "profile_time": "2024-01-20T00:00:00Z", "latitude": 15.5, "longitude": 68.6, "pressure_dbar": 5.0, "temperature_c": 27.2, "salinity_psu": 36.0},
            ],
            row_count=6,
        )

        # Test A: Vertical temperature profile
        q_a = "Plot the vertical temperature profile for float 1902671."
        intent_a = QueryIntent(intent_type=IntentType.DATA_ONLY, intent_category=IntentCategory.PRESSURE_DEPTH, physical_variables=[PhysicalVariable.TEMP], wmo_ids=["1902671"])
        spec_a = self.agent._build_visualization_spec(db_result, intent=intent_a, query=q_a)
        self.assertIsNotNone(spec_a)
        self.assertEqual(spec_a.chart_type, ChartType.LINE)
        self.assertEqual(spec_a.x_axis, "temperature_c")
        self.assertEqual(spec_a.y_axis, "pressure_dbar")
        self.assertTrue(spec_a.invert_y)
        self.assertIn("Vertical Temperature Profile", spec_a.title)

        # Test B: Temperature distribution
        q_b = "Analyze the distribution of temperature measurements for float 1902671 and visualize the distribution using appropriate temperature intervals."
        intent_b = QueryIntent(intent_type=IntentType.DATA_ONLY, intent_category=IntentCategory.COMPARISON, physical_variables=[PhysicalVariable.TEMP], wmo_ids=["1902671"])
        spec_b = self.agent._build_visualization_spec(db_result, intent=intent_b, query=q_b)
        self.assertIsNotNone(spec_b)
        self.assertEqual(spec_b.chart_type, ChartType.HISTOGRAM)
        self.assertEqual(spec_b.x_axis, "interval")
        self.assertEqual(spec_b.y_axis, "count")
        self.assertFalse(spec_b.invert_y)
        self.assertIn("Temperature Measurement Distribution", spec_b.title)
        self.assertGreater(len(spec_b.data), 0)
        self.assertEqual(sum(r["count"] for r in spec_b.data), 6)

        # Test C: Salinity distribution
        q_c = "Visualize the distribution of salinity measurements for float 1902671 using appropriate salinity intervals."
        intent_c = QueryIntent(intent_type=IntentType.DATA_ONLY, intent_category=IntentCategory.COMPARISON, physical_variables=[PhysicalVariable.PSAL], wmo_ids=["1902671"])
        spec_c = self.agent._build_visualization_spec(db_result, intent=intent_c, query=q_c)
        self.assertIsNotNone(spec_c)
        self.assertEqual(spec_c.chart_type, ChartType.HISTOGRAM)
        self.assertEqual(spec_c.x_axis, "interval")
        self.assertEqual(spec_c.y_axis, "count")
        self.assertFalse(spec_c.invert_y)
        self.assertIn("Salinity Measurement Distribution", spec_c.title)
        self.assertGreater(len(spec_c.data), 0)
        self.assertEqual(sum(r["count"] for r in spec_c.data), 6)

        # Test D: Temperature and salinity relationship (scatter plot)
        q_d = "Create a scatter plot showing temperature versus salinity for float 1902671."
        intent_d = QueryIntent(intent_type=IntentType.DATA_ONLY, intent_category=IntentCategory.COMPARISON, physical_variables=[PhysicalVariable.TEMP, PhysicalVariable.PSAL], wmo_ids=["1902671"])
        spec_d = self.agent._build_visualization_spec(db_result, intent=intent_d, query=q_d)
        self.assertIsNotNone(spec_d)
        self.assertEqual(spec_d.chart_type, ChartType.SCATTER)
        self.assertEqual(spec_d.x_axis, "temperature_c")
        self.assertEqual(spec_d.y_axis, "salinity_psu")
        self.assertFalse(spec_d.invert_y)
        self.assertIn("Temperature vs Salinity", spec_d.title)
        self.assertEqual(len(spec_d.data), 6)

        # Test E: Temperature over time
        q_e = "Plot the average temperature for float 1902671 over time, grouped by profile date."
        intent_e = QueryIntent(intent_type=IntentType.DATA_ONLY, intent_category=IntentCategory.AGGREGATION, aggregation_operation=AggregationOp.AVERAGE, physical_variables=[PhysicalVariable.TEMP], wmo_ids=["1902671"])
        spec_e = self.agent._build_visualization_spec(db_result, intent=intent_e, query=q_e)
        self.assertIsNotNone(spec_e)
        self.assertEqual(spec_e.chart_type, ChartType.LINE)
        self.assertEqual(spec_e.x_axis, "profile_time")
        self.assertEqual(spec_e.y_axis, "temperature_c")
        self.assertFalse(spec_e.invert_y)
        self.assertIn("Temperature Over Time", spec_e.title)
        # 3 distinct timestamps in rows -> 3 grouped points
        self.assertEqual(len(spec_e.data), 3)



if __name__ == "__main__":
    unittest.main()

