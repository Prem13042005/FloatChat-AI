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


if __name__ == "__main__":
    unittest.main()

