"""
tests/test_query_understanding.py

Phase 5 — Query Understanding Agent Test Suite.
Verifies natural-language query intent extraction, spatial-temporal slot parsing,
pressure/depth distinction, model validation rules, ambiguity handling, error propagation,
and BaseLLMProvider contract isolation.

All unit tests run completely offline using unittest.mock.
"""

import os
import sys
import unittest
from unittest.mock import MagicMock

# Ensure src is in python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.agents.query_understanding import (
    AggregationOp,
    ComparisonTarget,
    IntentCategory,
    IntentType,
    PhysicalVariable,
    PressureRange,
    QueryIntent,
    QueryUnderstandingAgent,
    SpatialBounds,
    TemporalRange,
)
from src.llm import BaseLLMProvider, LLMResponseError, LLMStructuredOutputError


class TestQueryUnderstandingAgent(unittest.TestCase):

    def setUp(self):
        self.mock_provider = MagicMock(spec=BaseLLMProvider)
        self.agent = QueryUnderstandingAgent(llm_provider=self.mock_provider)

    # ===================================================================
    # 1. Physical Metric Intent Tests (Temperature, Salinity, Pressure)
    # ===================================================================

    def test_01_simple_temperature_retrieval(self):
        """Verify extraction of simple water temperature query intent."""
        mock_intent = QueryIntent(
            intent_type=IntentType.DATA_ONLY,
            intent_category=IntentCategory.FILTERING,
            physical_variables=[PhysicalVariable.TEMP],
        )
        self.mock_provider.generate_structured.return_value = mock_intent

        res = self.agent.analyze("Show water temperature readings.")
        self.assertEqual(res.intent_type, IntentType.DATA_ONLY)
        self.assertIn(PhysicalVariable.TEMP, res.physical_variables)
        self.mock_provider.generate_structured.assert_called_once()

    def test_02_salinity_retrieval(self):
        """Verify extraction of salinity query intent."""
        mock_intent = QueryIntent(
            intent_type=IntentType.DATA_ONLY,
            intent_category=IntentCategory.FILTERING,
            physical_variables=[PhysicalVariable.PSAL],
        )
        self.mock_provider.generate_structured.return_value = mock_intent

        res = self.agent.analyze("Find profiles with high salinity.")
        self.assertIn(PhysicalVariable.PSAL, res.physical_variables)

    def test_03_pressure_retrieval(self):
        """Verify extraction of pressure query intent."""
        mock_intent = QueryIntent(
            intent_type=IntentType.DATA_ONLY,
            intent_category=IntentCategory.PRESSURE_DEPTH,
            physical_variables=[PhysicalVariable.PRES],
        )
        self.mock_provider.generate_structured.return_value = mock_intent

        res = self.agent.analyze("List ocean pressure levels.")
        self.assertIn(PhysicalVariable.PRES, res.physical_variables)

    # ===================================================================
    # 2. Aggregation & Statistics Intent Tests
    # ===================================================================

    def test_04_average_temperature(self):
        """Verify extraction of average temperature aggregation intent."""
        mock_intent = QueryIntent(
            intent_type=IntentType.DATA_ONLY,
            intent_category=IntentCategory.STATISTICS,
            physical_variables=[PhysicalVariable.TEMP],
            aggregation_operation=AggregationOp.AVERAGE,
        )
        self.mock_provider.generate_structured.return_value = mock_intent

        res = self.agent.analyze("What is the average water temperature?")
        self.assertEqual(res.aggregation_operation, AggregationOp.AVERAGE)

    def test_05_minimum_maximum(self):
        """Verify extraction of min/max statistics query intent."""
        mock_intent = QueryIntent(
            intent_type=IntentType.DATA_ONLY,
            intent_category=IntentCategory.STATISTICS,
            physical_variables=[PhysicalVariable.PSAL],
            aggregation_operation=AggregationOp.MAXIMUM,
        )
        self.mock_provider.generate_structured.return_value = mock_intent

        res = self.agent.analyze("Find the maximum salinity recorded.")
        self.assertEqual(res.aggregation_operation, AggregationOp.MAXIMUM)

    def test_06_count_query(self):
        """Verify extraction of count aggregation intent."""
        mock_intent = QueryIntent(
            intent_type=IntentType.DATA_ONLY,
            intent_category=IntentCategory.AGGREGATION,
            aggregation_operation=AggregationOp.COUNT,
        )
        self.mock_provider.generate_structured.return_value = mock_intent

        res = self.agent.analyze("How many profiles were recorded in 2024?")
        self.assertEqual(res.aggregation_operation, AggregationOp.COUNT)

    # ===================================================================
    # 3. Spatial, Temporal, Platform & Pressure Filter Slot Tests
    # ===================================================================

    def test_07_date_time_filtering(self):
        """Verify extraction of start and end date temporal range bounds."""
        mock_intent = QueryIntent(
            intent_type=IntentType.DATA_ONLY,
            intent_category=IntentCategory.TEMPORAL,
            temporal_range=TemporalRange(start_date="2024-01-01", end_date="2024-01-31"),
        )
        self.mock_provider.generate_structured.return_value = mock_intent

        res = self.agent.analyze("Show profiles recorded between Jan 1 2024 and Jan 31 2024.")
        self.assertIsNotNone(res.temporal_range)
        self.assertEqual(res.temporal_range.start_date, "2024-01-01")
        self.assertEqual(res.temporal_range.end_date, "2024-01-31")

    def test_08_latitude_filtering(self):
        """Verify extraction of latitude bounds."""
        mock_intent = QueryIntent(
            intent_type=IntentType.DATA_ONLY,
            intent_category=IntentCategory.SPATIAL,
            spatial_bounds=SpatialBounds(latitude_min=-10.0, latitude_max=10.0),
        )
        self.mock_provider.generate_structured.return_value = mock_intent

        res = self.agent.analyze("Find profiles between 10 degrees south and 10 degrees north.")
        self.assertEqual(res.spatial_bounds.latitude_min, -10.0)
        self.assertEqual(res.spatial_bounds.latitude_max, 10.0)

    def test_09_longitude_filtering(self):
        """Verify extraction of longitude bounds."""
        mock_intent = QueryIntent(
            intent_type=IntentType.DATA_ONLY,
            intent_category=IntentCategory.SPATIAL,
            spatial_bounds=SpatialBounds(longitude_min=60.0, longitude_max=80.0),
        )
        self.mock_provider.generate_structured.return_value = mock_intent

        res = self.agent.analyze("Show data between longitude 60E and 80E.")
        self.assertEqual(res.spatial_bounds.longitude_min, 60.0)
        self.assertEqual(res.spatial_bounds.longitude_max, 80.0)

    def test_10_platform_wmo_filtering(self):
        """Verify extraction of WMO float platform identifier."""
        mock_intent = QueryIntent(
            intent_type=IntentType.DATA_ONLY,
            intent_category=IntentCategory.FLOAT_SPECIFIC,
            wmo_ids=["2901550"],
        )
        self.mock_provider.generate_structured.return_value = mock_intent

        res = self.agent.analyze("Show profiles recorded by float WMO 2901550.")
        self.assertEqual(res.wmo_ids, ["2901550"])

    def test_11_pressure_range(self):
        """Verify extraction of ocean pressure range bounds in dbar."""
        mock_intent = QueryIntent(
            intent_type=IntentType.DATA_ONLY,
            intent_category=IntentCategory.PRESSURE_DEPTH,
            pressure_range=PressureRange(pressure_min=10.0, pressure_max=500.0, is_depth_requested=False),
        )
        self.mock_provider.generate_structured.return_value = mock_intent

        res = self.agent.analyze("Find salinity values between 10 and 500 dbar pressure.")
        self.assertEqual(res.pressure_range.pressure_min, 10.0)
        self.assertEqual(res.pressure_range.pressure_max, 500.0)
        self.assertFalse(res.pressure_range.is_depth_requested)

    def test_12_explicit_depth_request(self):
        """Verify explicit depth request sets is_depth_requested=True."""
        mock_intent = QueryIntent(
            intent_type=IntentType.DATA_ONLY,
            intent_category=IntentCategory.PRESSURE_DEPTH,
            pressure_range=PressureRange(pressure_min=0.0, pressure_max=100.0, is_depth_requested=True),
        )
        self.mock_provider.generate_structured.return_value = mock_intent

        res = self.agent.analyze("Show water temperature from surface down to 100 meters depth.")
        self.assertTrue(res.pressure_range.is_depth_requested)
        self.assertEqual(res.pressure_range.pressure_max, 100.0)

    def test_13_combined_query(self):
        """Verify extraction of combined spatial, temporal, pressure, and metric constraints."""
        mock_intent = QueryIntent(
            intent_type=IntentType.DATA_ONLY,
            intent_category=IntentCategory.COMBINED,
            physical_variables=[PhysicalVariable.TEMP, PhysicalVariable.PSAL],
            aggregation_operation=AggregationOp.AVERAGE,
            spatial_bounds=SpatialBounds(latitude_min=0.0, latitude_max=15.0, longitude_min=65.0, longitude_max=75.0),
            temporal_range=TemporalRange(start_date="2024-01-01", end_date="2024-01-31"),
            pressure_range=PressureRange(pressure_min=0.0, pressure_max=200.0),
        )
        self.mock_provider.generate_structured.return_value = mock_intent

        res = self.agent.analyze(
            "What is the average temperature and salinity in January 2024 "
            "between 0 and 15 N, 65 and 75 E down to 200 dbar?"
        )
        self.assertEqual(len(res.physical_variables), 2)
        self.assertEqual(res.spatial_bounds.latitude_max, 15.0)
        self.assertEqual(res.temporal_range.start_date, "2024-01-01")

    def test_14_comparison_query(self):
        """Verify extraction of comparison intent targets."""
        mock_intent = QueryIntent(
            intent_type=IntentType.DATA_ONLY,
            intent_category=IntentCategory.COMPARISON,
            physical_variables=[PhysicalVariable.TEMP],
            comparison_target=ComparisonTarget(
                is_comparison=True,
                comparison_targets=["WMO 2901550", "WMO 2901551"],
                comparison_aspect="temperature",
            ),
        )
        self.mock_provider.generate_structured.return_value = mock_intent

        res = self.agent.analyze("Compare temperature readings between float WMO 2901550 and float WMO 2901551.")
        self.assertTrue(res.comparison_target.is_comparison)
        self.assertEqual(len(res.comparison_target.comparison_targets), 2)

    # ===================================================================
    # 4. Ambiguity, Unsupported Queries & Validation Failure Tests
    # ===================================================================

    def test_15_ambiguous_query(self):
        """Verify vague user query sets needs_clarification=True."""
        mock_intent = QueryIntent(
            intent_type=IntentType.DATA_ONLY,
            is_supported=True,
            needs_clarification=True,
            clarification_question="Which ocean parameter (temperature, salinity, pressure) are you interested in?",
        )
        self.mock_provider.generate_structured.return_value = mock_intent

        res = self.agent.analyze("Tell me about the ocean data.")
        self.assertTrue(res.needs_clarification)
        self.assertIsNotNone(res.clarification_question)

    def test_16_unsupported_variable_request(self):
        """Verify request for unsupported variable sets is_supported=False."""
        mock_intent = QueryIntent(
            intent_type=IntentType.DATA_ONLY,
            is_supported=False,
            unsupported_reason="Dissolved oxygen measurements are not available in FloatChat V1 dataset.",
        )
        self.mock_provider.generate_structured.return_value = mock_intent

        res = self.agent.analyze("Show dissolved oxygen profiles.")
        self.assertFalse(res.is_supported)
        self.assertIn("Dissolved oxygen", res.unsupported_reason)

    def test_17_invalid_latitude_range(self):
        """Verify model validation fails if latitude_min > latitude_max."""
        with self.assertRaises(ValueError) as ctx:
            SpatialBounds(latitude_min=20.0, latitude_max=10.0)
        self.assertIn("latitude_min (20.0) cannot be greater than latitude_max (10.0)", str(ctx.exception))

    def test_18_invalid_longitude_range(self):
        """Verify model validation fails if longitude_min > longitude_max."""
        with self.assertRaises(ValueError) as ctx:
            SpatialBounds(longitude_min=90.0, longitude_max=80.0)
        self.assertIn("longitude_min (90.0) cannot be greater than longitude_max (80.0)", str(ctx.exception))

    def test_19_invalid_time_range(self):
        """Verify model validation fails if start_date > end_date."""
        with self.assertRaises(ValueError) as ctx:
            TemporalRange(start_date="2024-02-01", end_date="2024-01-01")
        self.assertIn("start_date (2024-02-01) cannot be after end_date (2024-01-01)", str(ctx.exception))

    def test_20_empty_query(self):
        """Verify passing empty query string raises ValueError."""
        with self.assertRaises(ValueError) as ctx:
            self.agent.analyze("   ")
        self.assertIn("Query string cannot be empty", str(ctx.exception))

    def test_21_provider_error_propagation(self):
        """Verify LLM provider exceptions are propagated cleanly."""
        self.mock_provider.generate_structured.side_effect = LLMResponseError("API Unavailable")

        with self.assertRaises(LLMResponseError) as ctx:
            self.agent.analyze("What is the water temperature?")
        self.assertIn("API Unavailable", str(ctx.exception))

    def test_22_structured_output_validation_failure(self):
        """Verify LLM structured output parsing error raises LLMStructuredOutputError."""
        self.mock_provider.generate_structured.side_effect = LLMStructuredOutputError("JSON validation failed")

        with self.assertRaises(LLMStructuredOutputError) as ctx:
            self.agent.analyze("Get salinity data")
        self.assertIn("JSON validation failed", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
