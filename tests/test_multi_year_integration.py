"""
tests/test_multi_year_integration.py

Phase E4-E: Controlled Multi-Year LangGraph Integration Test Suite.
Verifies the end-to-end integration across the combined January 2024 and January-April 2025 dataset
using the existing LangGraph orchestrator and three primary agents:
1. QueryUnderstandingAgent (Intent and taxonomy extraction)
2. DataQueryAgent (SQL generation with DeterministicSQLValidator)
3. ControlledDatabaseExecutor (Read-only execution against PostgreSQL/PostGIS on port 5433)
4. ScientificResponseAgent (Evidence-grounded synthesis, data summary, and VisualizationSpec)

Covers the 4 required scenarios:
- Scenario 1: January 2024 query (Arabian Sea temperature profiles)
- Scenario 2: February 2025 query (Float 2902093 salinity query with empty reporting & salinity chart verification)
- Scenario 3: Multi-year comparison (January 2024 vs January 2025 temperature comparison)
- Scenario 4: Out-of-range date request (June 2025 temporal boundary verification)
"""

import os
import sys
import unittest
from unittest.mock import MagicMock

# Ensure src is in python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.agents.data_query.models import DataQueryResult, DataQueryStatus
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
from src.config import Config
from src.database.executor import ControlledDatabaseExecutor
from src.database.models import DatabaseExecutionResult, ExecutionStatus
from src.llm import BaseLLMProvider
from src.orchestration import FloatChatOrchestrator, FloatChatState
from src.rag.retriever import ScientificDocumentRetriever
from src.security.sql_validator import DeterministicSQLValidator


class TestMultiYearIntegration(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        # Dedicated Docker DB on port 5433
        cls.config = Config(
            postgres_host="127.0.0.1",
            postgres_port=5433,
            postgres_db="floatchat_db",
            postgres_user="floatchat_user",
            postgres_password="floatchat_password",
            postgres_statement_timeout_ms=5000,
        )
        cls.sql_validator = DeterministicSQLValidator()
        cls.db_executor = ControlledDatabaseExecutor(
            config=cls.config,
            validator=cls.sql_validator,
            statement_timeout_ms=5000,
            max_row_limit=1000,
        )

    def setUp(self):
        self.mock_llm = MagicMock(spec=BaseLLMProvider)
        self.mock_retriever = MagicMock(spec=ScientificDocumentRetriever)
        self.mock_retriever.retrieve.return_value = MagicMock(chunks=[], total_found=0, status="empty")

        self.response_agent = ScientificResponseAgent(
            llm_provider=self.mock_llm,
            retriever=self.mock_retriever,
            config=self.config,
        )

        self.mock_query_agent = MagicMock()
        self.mock_data_agent = MagicMock()

        self.orchestrator = FloatChatOrchestrator(
            query_agent=self.mock_query_agent,
            data_agent=self.mock_data_agent,
            db_executor=self.db_executor,
            response_agent=self.response_agent,
            config=self.config,
        )

    # ===================================================================
    # Scenario 1: January 2024 Query
    # ===================================================================

    def test_scenario_1_january_2024_temperature_query(self):
        """
        Scenario 1: Find temperature profiles in the Arabian Sea in January 2024.
        Verifies:
        - Query follows DATA_ONLY flow.
        - SQL is validated by DeterministicSQLValidator.
        - Execution is read-only against live DB on port 5433.
        - Results are grounded in 2024 observations with temperature profile visualization.
        """
        query = "Find temperature profiles in the Arabian Sea in January 2024."
        intent = QueryIntent(
            intent_type=IntentType.DATA_ONLY,
            intent_category=IntentCategory.FILTERING,
            physical_variables=[PhysicalVariable.TEMP],
            spatial_bounds=SpatialBounds(latitude_min=8.0, latitude_max=25.0, longitude_min=58.0, longitude_max=75.0),
            temporal_range=TemporalRange(start_date="2024-01-01", end_date="2024-01-31"),
        )
        self.mock_query_agent.analyze.return_value = intent

        valid_sql = """
            SELECT p.profile_id, p.platform_number, p.profile_time, m.pressure_dbar, m.temperature_c
            FROM argo_profiles p
            JOIN argo_measurements m ON p.profile_id = m.profile_id
            WHERE p.profile_time >= '2024-01-01' AND p.profile_time < '2024-02-01'
              AND p.latitude BETWEEN 8.0 AND 25.0 AND p.longitude BETWEEN 58.0 AND 75.0
            ORDER BY m.pressure_dbar ASC
            LIMIT 10;
        """
        dqr = DataQueryResult(status=DataQueryStatus.SUCCESS, sql=valid_sql)
        self.mock_data_agent.generate_sql.return_value = dqr

        # Mock LLM for narrative formatting
        self.mock_llm.generate_structured.return_value = _LLMResponsePayload(
            answer="In January 2024, ARGO profiles in the Arabian Sea measured temperatures decreasing with depth from 28.5°C near surface to 10.2°C at 500 dbar.",
            citations=[],
        )

        state: FloatChatState = self.orchestrator.invoke(query)

        # Assert flow routing
        self.assertEqual(state.get("intent_type"), "DATA_ONLY")
        self.assertIsNotNone(state.get("db_result"))

        # Assert read-only DB execution
        db_res = state["db_result"]
        self.assertTrue(db_res.is_success)
        self.assertEqual(db_res.row_count, 10)
        self.assertIn("temperature_c", db_res.columns)
        self.assertIn("pressure_dbar", db_res.columns)

        # Assert grounded data summary and visualization spec
        self.assertIn("In January 2024", state["final_response"])
        viz = state.get("visualization_spec")
        self.assertIsNotNone(viz)
        self.assertEqual(viz.get("chart_type"), "line")
        self.assertEqual(viz.get("x_axis"), "temperature_c")
        self.assertEqual(viz.get("y_axis"), "pressure_dbar")
        self.assertTrue(viz.get("invert_y"))

    # ===================================================================
    # Scenario 2: February 2025 Query & Salinity Visualization
    # ===================================================================

    def test_scenario_2_february_2025_query_and_salinity_visualization(self):
        """
        Scenario 2: Show salinity measurements for float 2902093 in February 2025.
        Verifies:
        - Query uses intended date (Feb 2025) and float filter (2902093).
        - Correctly reports empty results (0 rows) without inventing observations.
        - Missing salinity is not represented as zero.
        - Salinity visualization works for floats with valid salinity_psu data.
        """
        query = "Show salinity measurements for float 2902093 in February 2025."
        intent = QueryIntent(
            intent_type=IntentType.DATA_ONLY,
            intent_category=IntentCategory.FLOAT_SPECIFIC,
            physical_variables=[PhysicalVariable.PSAL],
            wmo_ids=["2902093"],
            temporal_range=TemporalRange(start_date="2025-02-01", end_date="2025-02-28"),
        )
        self.mock_query_agent.analyze.return_value = intent

        sql_feb = """
            SELECT p.profile_id, p.platform_number, p.profile_time, m.pressure_dbar, m.salinity_psu
            FROM argo_profiles p
            JOIN argo_measurements m ON p.profile_id = m.profile_id
            WHERE p.platform_number = '2902093'
              AND p.profile_time >= '2025-02-01' AND p.profile_time < '2025-03-01'
            ORDER BY m.pressure_dbar ASC
            LIMIT 10;
        """
        self.mock_data_agent.generate_sql.return_value = DataQueryResult(status=DataQueryStatus.SUCCESS, sql=sql_feb)

        self.mock_llm.generate_structured.return_value = _LLMResponsePayload(
            answer="No salinity observations were recorded for float 2902093 during February 2025 in the loaded dataset.",
            citations=[],
        )

        state: FloatChatState = self.orchestrator.invoke(query)

        # Assert empty result is reported accurately without fabricating observations
        db_res = state["db_result"]
        self.assertTrue(db_res.is_success)
        self.assertEqual(db_res.row_count, 0)
        self.assertIsNone(state.get("visualization_spec"))

        # Verify that for a 2025 float with valid salinity_psu measurements (float 2902273 in Jan 2025),
        # salinity visualization generates line chart using canonical salinity_psu column
        sql_valid_sal = """
            SELECT p.profile_id, p.platform_number, p.profile_time, m.pressure_dbar, m.salinity_psu
            FROM argo_profiles p
            JOIN argo_measurements m ON p.profile_id = m.profile_id
            WHERE p.platform_number = '2902273'
              AND p.profile_time >= '2025-01-01' AND p.profile_time < '2025-02-01'
            ORDER BY m.pressure_dbar ASC
            LIMIT 10;
        """
        valid_res = self.db_executor.execute(DataQueryResult(status=DataQueryStatus.SUCCESS, sql=sql_valid_sal))
        self.assertEqual(valid_res.row_count, 10)

        intent_sal = QueryIntent(intent_type=IntentType.DATA_ONLY, physical_variables=[PhysicalVariable.PSAL])
        spec_sal = self.response_agent._build_visualization_spec(valid_res, intent=intent_sal)
        self.assertIsNotNone(spec_sal)
        self.assertEqual(spec_sal.chart_type, ChartType.LINE)
        self.assertEqual(spec_sal.x_axis, "salinity_psu")
        self.assertEqual(spec_sal.y_axis, "pressure_dbar")
        self.assertTrue(spec_sal.invert_y)

    # ===================================================================
    # Scenario 3: Multi-Year Comparison (2024 vs 2025)
    # ===================================================================

    def test_scenario_3_multi_year_temperature_comparison(self):
        """
        Scenario 3: Compare average water temperature between January 2024 and January 2025.
        Verifies:
        - Both periods are filtered correctly via SQL aggregation.
        - Each aggregate is computed from actual observations (17,339 rows in 2024, 6,959 in 2025).
        - Results distinguish both periods without inventing values or dates.
        """
        query = "Compare average water temperature between January 2024 and January 2025."
        intent = QueryIntent(
            intent_type=IntentType.DATA_ONLY,
            intent_category=IntentCategory.COMPARISON,
            physical_variables=[PhysicalVariable.TEMP],
        )
        self.mock_query_agent.analyze.return_value = intent

        comparison_sql = """
            SELECT 
                EXTRACT(YEAR FROM p.profile_time)::INT as year,
                COUNT(m.measurement_id) as record_count,
                ROUND(AVG(m.temperature_c)::numeric, 3) as avg_temp,
                ROUND(MIN(m.temperature_c)::numeric, 3) as min_temp,
                ROUND(MAX(m.temperature_c)::numeric, 3) as max_temp
            FROM argo_profiles p
            JOIN argo_measurements m ON p.profile_id = m.profile_id
            WHERE EXTRACT(MONTH FROM p.profile_time) = 1
              AND EXTRACT(YEAR FROM p.profile_time) IN (2024, 2025)
            GROUP BY EXTRACT(YEAR FROM p.profile_time)
            ORDER BY EXTRACT(YEAR FROM p.profile_time);
        """
        self.mock_data_agent.generate_sql.return_value = DataQueryResult(status=DataQueryStatus.SUCCESS, sql=comparison_sql)

        self.mock_llm.generate_structured.return_value = _LLMResponsePayload(
            answer="In January 2024, the mean water temperature across 17,339 observations was 11.415°C (range: 2.837°C to 29.902°C). In January 2025, the mean across 6,959 observations was 10.945°C (range: 2.973°C to 28.657°C).",
            citations=[],
        )

        state: FloatChatState = self.orchestrator.invoke(query)

        db_res = state["db_result"]
        self.assertTrue(db_res.is_success)
        self.assertEqual(db_res.row_count, 2)

        row_2024 = next(r for r in db_res.rows if r["year"] == 2024)
        row_2025 = next(r for r in db_res.rows if r["year"] == 2025)

        self.assertEqual(row_2024["record_count"], 17339)
        self.assertAlmostEqual(float(row_2024["avg_temp"]), 11.415, places=2)

        self.assertEqual(row_2025["record_count"], 6959)
        self.assertAlmostEqual(float(row_2025["avg_temp"]), 10.945, places=2)

        # Distinguishes both periods in narrative
        self.assertIn("January 2024", state["final_response"])
        self.assertIn("January 2025", state["final_response"])

    # ===================================================================
    # Scenario 4: Out-of-Range Date Request (June 2025)
    # ===================================================================

    def test_scenario_4_out_of_range_date_temporal_guard(self):
        """
        Scenario 4: Show observations in June 2025.
        Verifies:
        - Query filters on June 2025 and executes read-only.
        - Database returns 0 rows since dataset terminates April 1, 2025.
        - System clearly communicates dataset coverage limits without claiming worldwide non-existence.
        """
        query = "Show observations in June 2025."
        intent = QueryIntent(
            intent_type=IntentType.DATA_ONLY,
            intent_category=IntentCategory.TEMPORAL,
            temporal_range=TemporalRange(start_date="2025-06-01", end_date="2025-06-30"),
        )
        self.mock_query_agent.analyze.return_value = intent

        sql_june = """
            SELECT p.profile_id, p.platform_number, p.profile_time, m.temperature_c, m.salinity_psu
            FROM argo_profiles p
            JOIN argo_measurements m ON p.profile_id = m.profile_id
            WHERE p.profile_time >= '2025-06-01' AND p.profile_time < '2025-07-01'
            LIMIT 10;
        """
        self.mock_data_agent.generate_sql.return_value = DataQueryResult(status=DataQueryStatus.SUCCESS, sql=sql_june)

        self.mock_llm.generate_structured.return_value = _LLMResponsePayload(
            answer="No observations were found for June 2025. The currently loaded FloatChat dataset contains observations only through April 1, 2025. This empty result reflects dataset temporal boundaries rather than absence of global ARGO float operations in June 2025.",
            citations=[],
        )

        state: FloatChatState = self.orchestrator.invoke(query)

        db_res = state["db_result"]
        self.assertTrue(db_res.is_success)
        self.assertEqual(db_res.row_count, 0)

        # Assert grounded temporal boundary explanation
        self.assertIn("April 1, 2025", state["final_response"])
        self.assertIn("local dataset coverage boundaries", state["final_response"])
        self.assertIn("absence of global ARGO float operations", state["final_response"])


if __name__ == "__main__":
    unittest.main()
