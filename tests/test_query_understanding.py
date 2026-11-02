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

from pydantic import ValidationError
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


    # ===================================================================
    # 6. WMO IDs Validation & Null Coercion Tests (DEF-E5-02)
    # ===================================================================

    def test_23_wmo_ids_missing_defaults_to_empty_list(self):
        """Verify omitting wmo_ids defaults to an empty list."""
        intent = QueryIntent()
        self.assertEqual(intent.wmo_ids, [])
        self.assertIsInstance(intent.wmo_ids, list)

        # Also verify when constructed from dict without wmo_ids
        intent_from_dict = QueryIntent.model_validate({"intent_type": "DATA_ONLY"})
        self.assertEqual(intent_from_dict.wmo_ids, [])

    def test_24_wmo_ids_explicit_null_coerced_to_empty_list(self):
        """Verify explicit null/None for wmo_ids is cleanly coerced into an empty list."""
        intent_direct = QueryIntent(wmo_ids=None)
        self.assertEqual(intent_direct.wmo_ids, [])
        self.assertIsInstance(intent_direct.wmo_ids, list)

        # Verify JSON/dict deserialization with explicit null (simulating local LLM output)
        intent_from_json = QueryIntent.model_validate({
            "intent_type": "DATA_ONLY",
            "intent_category": "filtering",
            "wmo_ids": None,
        })
        self.assertEqual(intent_from_json.wmo_ids, [])
        self.assertIsInstance(intent_from_json.wmo_ids, list)

    def test_25_wmo_ids_valid_platform_list_preserved(self):
        """Verify valid list of platform identifiers is preserved exactly."""
        valid_ids = ["2901333", "1902672", "4903783"]
        intent = QueryIntent(wmo_ids=valid_ids)
        self.assertEqual(intent.wmo_ids, valid_ids)

        intent_from_dict = QueryIntent.model_validate({
            "intent_type": "DATA_ONLY",
            "wmo_ids": ["2902093"],
        })
        self.assertEqual(intent_from_dict.wmo_ids, ["2902093"])

    def test_26_wmo_ids_invalid_type_rejected(self):
        """Verify non-list / invalid types are not silently converted and raise ValidationError."""
        # Non-iterable numeric type
        with self.assertRaises(ValidationError) as ctx:
            QueryIntent(wmo_ids=12345)
        self.assertIn("wmo_ids", str(ctx.exception))

        # Dict type
        with self.assertRaises(ValidationError) as ctx:
            QueryIntent.model_validate({"wmo_ids": {"id": "2901333"}})
        self.assertIn("wmo_ids", str(ctx.exception))

    # ===================================================================
    # 7. Regional Gazetteer Tests (Stage 8B Phase 2B)
    # ===================================================================

    def test_27_arabian_sea_parent_bounds(self):
        """Verify Arabian Sea resolves deterministically to approved parent bounding box."""
        mock_intent = QueryIntent(intent_type=IntentType.DATA_ONLY)
        self.mock_provider.generate_structured.return_value = mock_intent

        res = self.agent.analyze("What is the average temperature in the Arabian Sea?")
        self.assertIsNotNone(res.spatial_bounds)
        self.assertEqual(res.spatial_bounds.latitude_min, 8.0)
        self.assertEqual(res.spatial_bounds.latitude_max, 24.0)
        self.assertEqual(res.spatial_bounds.longitude_min, 55.0)
        self.assertEqual(res.spatial_bounds.longitude_max, 75.0)

    def test_28_northern_arabian_sea_subregion_bounds(self):
        """Verify Northern Arabian Sea resolves to northern subregion bounding box."""
        mock_intent = QueryIntent(intent_type=IntentType.DATA_ONLY)
        self.mock_provider.generate_structured.return_value = mock_intent

        res = self.agent.analyze("Find salinity in the Northern Arabian Sea.")
        self.assertIsNotNone(res.spatial_bounds)
        self.assertEqual(res.spatial_bounds.latitude_min, 18.0)
        self.assertEqual(res.spatial_bounds.latitude_max, 24.0)
        self.assertEqual(res.spatial_bounds.longitude_min, 58.0)
        self.assertEqual(res.spatial_bounds.longitude_max, 74.0)

    def test_29_central_arabian_sea_subregion_bounds(self):
        """Verify Central Arabian Sea resolves to central subregion bounding box."""
        mock_intent = QueryIntent(intent_type=IntentType.DATA_ONLY)
        self.mock_provider.generate_structured.return_value = mock_intent

        res = self.agent.analyze("Show observations in the Central Arabian Sea.")
        self.assertIsNotNone(res.spatial_bounds)
        self.assertEqual(res.spatial_bounds.latitude_min, 14.0)
        self.assertEqual(res.spatial_bounds.latitude_max, 18.0)
        self.assertEqual(res.spatial_bounds.longitude_min, 62.0)
        self.assertEqual(res.spatial_bounds.longitude_max, 72.0)

    def test_30_southern_arabian_sea_subregion_bounds(self):
        """Verify Southern Arabian Sea resolves to southern subregion bounding box."""
        mock_intent = QueryIntent(intent_type=IntentType.DATA_ONLY)
        self.mock_provider.generate_structured.return_value = mock_intent

        res = self.agent.analyze("Show temperature profiles in the Southern Arabian Sea.")
        self.assertIsNotNone(res.spatial_bounds)
        self.assertEqual(res.spatial_bounds.latitude_min, 8.0)
        self.assertEqual(res.spatial_bounds.latitude_max, 14.0)
        self.assertEqual(res.spatial_bounds.longitude_min, 60.0)
        self.assertEqual(res.spatial_bounds.longitude_max, 75.0)

    def test_31_gazetteer_case_insensitivity(self):
        """Verify gazetteer matches case-insensitively across upper, lower, and mixed case."""
        mock_intent = QueryIntent(intent_type=IntentType.DATA_ONLY)
        self.mock_provider.generate_structured.return_value = mock_intent

        res = self.agent.analyze("temperature in the aRaBiAn SeA")
        self.assertIsNotNone(res.spatial_bounds)
        self.assertEqual(res.spatial_bounds.latitude_min, 8.0)
        self.assertEqual(res.spatial_bounds.latitude_max, 24.0)

    def test_32_subregion_longest_match_precedence(self):
        """Verify subregion name takes precedence over parent name in matching."""
        mock_intent = QueryIntent(intent_type=IntentType.DATA_ONLY)
        self.mock_provider.generate_structured.return_value = mock_intent

        res = self.agent.analyze("Water temperature in the northern Arabian Sea basin.")
        self.assertIsNotNone(res.spatial_bounds)
        # Must match Northern (18-24), NOT parent Arabian Sea (8-24)
        self.assertEqual(res.spatial_bounds.latitude_min, 18.0)
        self.assertEqual(res.spatial_bounds.latitude_max, 24.0)

    def test_33_unknown_region_no_invented_bounds(self):
        """Verify unknown or unapproved regions do not receive invented coordinates."""
        mock_intent = QueryIntent(intent_type=IntentType.DATA_ONLY)
        self.mock_provider.generate_structured.return_value = mock_intent

        res = self.agent.analyze("Show salinity profiles in the Gulf of Oman.")
        self.assertIsNone(res.spatial_bounds)

    # ===================================================================
    # 8. Coordinate Precedence & Hallucination Discarding Tests
    # ===================================================================

    def test_34_explicit_coordinates_preserved_with_named_region(self):
        """Verify explicit user-supplied coordinates are not overwritten by gazetteer."""
        # Simulated LLM output capturing user's explicit coordinates 12N-16N
        mock_intent = QueryIntent(
            intent_type=IntentType.DATA_ONLY,
            spatial_bounds=SpatialBounds(latitude_min=12.0, latitude_max=16.0),
        )
        self.mock_provider.generate_structured.return_value = mock_intent

        res = self.agent.analyze("Arabian Sea temperature between latitude 12 and 16.")
        self.assertIsNotNone(res.spatial_bounds)
        # Must preserve user coordinates (12-16), NOT overwrite with Arabian Sea (8-24)
        self.assertEqual(res.spatial_bounds.latitude_min, 12.0)
        self.assertEqual(res.spatial_bounds.latitude_max, 16.0)

    def test_35_recognized_region_without_coordinates_receives_gazetteer_bounds(self):
        """Verify single recognized region without user coordinates receives gazetteer bounds."""
        mock_intent = QueryIntent(intent_type=IntentType.DATA_ONLY, spatial_bounds=None)
        self.mock_provider.generate_structured.return_value = mock_intent

        res = self.agent.analyze("Show profiles in Central Arabian Sea.")
        self.assertIsNotNone(res.spatial_bounds)
        self.assertEqual(res.spatial_bounds.latitude_min, 14.0)
        self.assertEqual(res.spatial_bounds.latitude_max, 18.0)

    def test_36_unsupported_hallucinated_coordinates_discarded_when_query_has_no_coords(self):
        """Verify hallucinated coordinates from LLM are discarded when query supplies no coordinates."""
        # Simulating LLM returning arbitrary hallucinated coordinates for a query without numbers
        mock_intent = QueryIntent(
            intent_type=IntentType.DATA_ONLY,
            spatial_bounds=SpatialBounds(latitude_min=-10.0, latitude_max=10.0, longitude_min=-50.0, longitude_max=50.0),
        )
        self.mock_provider.generate_structured.return_value = mock_intent

        res = self.agent.analyze("Tell me about water.")
        self.assertIsNone(res.spatial_bounds)

    def test_37_multiple_regions_in_comparison_not_collapsed(self):
        """Verify multiple distinct regions in a comparison query are not merged into one box."""
        mock_intent = QueryIntent(
            intent_type=IntentType.DATA_ONLY,
            intent_category=IntentCategory.COMPARISON,
            comparison_target=ComparisonTarget(
                is_comparison=True,
                comparison_targets=["Northern Arabian Sea", "Southern Arabian Sea"],
            ),
        )
        self.mock_provider.generate_structured.return_value = mock_intent

        res = self.agent.analyze("Compare temperature between Northern Arabian Sea and Southern Arabian Sea.")
        # spatial_bounds must NOT be a collapsed single bounding box
        self.assertIsNone(res.spatial_bounds)
        self.assertTrue(res.comparison_target.is_comparison)
        self.assertEqual(len(res.comparison_target.comparison_targets), 2)

    def test_38_multiple_regions_without_comparison_not_merged(self):
        """Verify multiple distinct regions without comparison intent are not merged into an overbroad box."""
        mock_intent = QueryIntent(intent_type=IntentType.DATA_ONLY)
        self.mock_provider.generate_structured.return_value = mock_intent

        res = self.agent.analyze("Show observations from Northern Arabian Sea and Southern Arabian Sea.")
        self.assertIsNone(res.spatial_bounds)

    # ===================================================================
    # 9. Aggregation Operation Normalization Tests
    # ===================================================================

    def test_39_aggregation_operation_json_null_remains_none(self):
        """Verify Python None / JSON null produces None for aggregation_operation."""
        intent = QueryIntent.model_validate({"intent_type": "DATA_ONLY", "aggregation_operation": None})
        self.assertIsNone(intent.aggregation_operation)

    def test_40_aggregation_operation_string_null_and_none_coerced(self):
        """Verify string 'null', 'None', and 'none' normalize cleanly to Python None."""
        for val in ("null", "NULL", "None", "none"):
            intent = QueryIntent.model_validate({"intent_type": "DATA_ONLY", "aggregation_operation": val})
            self.assertIsNone(intent.aggregation_operation, f"Failed for input: {val!r}")

    def test_41_aggregation_operation_whitespace_coerced_to_none(self):
        """Verify empty and whitespace-only strings normalize to Python None."""
        for val in ("", "   ", "\t\n"):
            intent = QueryIntent.model_validate({"intent_type": "DATA_ONLY", "aggregation_operation": val})
            self.assertIsNone(intent.aggregation_operation, f"Failed for input: {val!r}")

    def test_42_aggregation_operation_valid_enum_preserved(self):
        """Verify valid AggregationOp enum values are preserved."""
        for op in ("average", "minimum", "maximum", "count", "sum"):
            intent = QueryIntent.model_validate({"intent_type": "DATA_ONLY", "aggregation_operation": op})
            self.assertEqual(intent.aggregation_operation.value, op)

    def test_43_aggregation_operation_invalid_value_rejected(self):
        """Verify unsupported aggregation values continue to be rejected by Pydantic."""
        with self.assertRaises(ValidationError) as ctx:
            QueryIntent.model_validate({"intent_type": "DATA_ONLY", "aggregation_operation": "median"})
        self.assertIn("aggregation_operation", str(ctx.exception))

    # ===================================================================
    # 10. Comparison Target Platform ID Synchronization Tests
    # ===================================================================

    def test_44_two_valid_float_ids_synchronized_to_wmo_ids(self):
        """Verify valid seven-digit float identifiers in comparison_targets synchronize into wmo_ids."""
        mock_intent = QueryIntent(
            intent_type=IntentType.DATA_ONLY,
            intent_category=IntentCategory.COMPARISON,
            comparison_target=ComparisonTarget(
                is_comparison=True,
                comparison_targets=["1902671", "1902672"],
            ),
            wmo_ids=[],
        )
        self.mock_provider.generate_structured.return_value = mock_intent

        res = self.agent.analyze("Compare float 1902671 with float 1902672.")
        self.assertEqual(res.wmo_ids, ["1902671", "1902672"])
        # Original comparison targets must remain preserved
        self.assertEqual(res.comparison_target.comparison_targets, ["1902671", "1902672"])

    def test_45_existing_wmo_ids_preserved_and_not_duplicated(self):
        """Verify existing wmo_ids are preserved without creating duplicate entries."""
        mock_intent = QueryIntent(
            intent_type=IntentType.DATA_ONLY,
            intent_category=IntentCategory.COMPARISON,
            comparison_target=ComparisonTarget(
                is_comparison=True,
                comparison_targets=["WMO 1902671", "1902672"],
            ),
            wmo_ids=["1902671"],
        )
        self.mock_provider.generate_structured.return_value = mock_intent

        res = self.agent.analyze("Compare float 1902671 with float 1902672.")
        self.assertEqual(res.wmo_ids, ["1902671", "1902672"])

    def test_46_non_numeric_region_names_not_converted_to_float_ids(self):
        """Verify non-numeric comparison target strings are not converted to float IDs."""
        mock_intent = QueryIntent(
            intent_type=IntentType.DATA_ONLY,
            intent_category=IntentCategory.COMPARISON,
            comparison_target=ComparisonTarget(
                is_comparison=True,
                comparison_targets=["Northern Arabian Sea", "Southern Arabian Sea"],
            ),
            wmo_ids=[],
        )
        self.mock_provider.generate_structured.return_value = mock_intent

        res = self.agent.analyze("Compare Northern Arabian Sea and Southern Arabian Sea.")
        self.assertEqual(res.wmo_ids, [])
        self.assertEqual(res.comparison_target.comparison_targets, ["Northern Arabian Sea", "Southern Arabian Sea"])

    def test_47_non_7_digit_numbers_not_converted_to_float_ids(self):
        """Verify arbitrary 4-digit years or depths in comparison targets are not added to wmo_ids."""
        mock_intent = QueryIntent(
            intent_type=IntentType.DATA_ONLY,
            intent_category=IntentCategory.COMPARISON,
            comparison_target=ComparisonTarget(
                is_comparison=True,
                comparison_targets=["2024", "2025"],
            ),
            wmo_ids=[],
        )
        self.mock_provider.generate_structured.return_value = mock_intent

        res = self.agent.analyze("Compare temperature between 2024 and 2025.")
        self.assertEqual(res.wmo_ids, [])

    def test_48_comparison_targets_preserved_unchanged(self):
        """Verify comparison targets list is preserved exactly as extracted."""
        original_targets = ["surface", "deep-water"]
        mock_intent = QueryIntent(
            intent_type=IntentType.DATA_ONLY,
            intent_category=IntentCategory.COMPARISON,
            comparison_target=ComparisonTarget(
                is_comparison=True,
                comparison_targets=original_targets,
            ),
        )
        self.mock_provider.generate_structured.return_value = mock_intent

        res = self.agent.analyze("Compare surface and deep-water temperature.")
        self.assertEqual(res.comparison_target.comparison_targets, original_targets)

    # ===================================================================
    # 7. Competition Fix 5: Mixed-Intent Routing Regression Tests
    # ===================================================================

    def test_49_hybrid_mixed_observational_and_ctd_explanation(self):
        """Verify mixed question with observations request and CTD sensor explanation routes to HYBRID."""
        mock_intent = QueryIntent(
            intent_type=IntentType.DATA_ONLY,  # Simulate LLM returning DATA_ONLY initially
            intent_category=IntentCategory.FILTERING,
            physical_variables=[PhysicalVariable.TEMP, PhysicalVariable.PSAL],
            wmo_ids=["1902671"],
        )
        self.mock_provider.generate_structured.return_value = mock_intent

        res = self.agent.analyze(
            "Show temperature observations for float 1902671 and explain how the CTD sensor measures temperature and salinity."
        )
        self.assertEqual(res.intent_type, IntentType.HYBRID)
        self.assertEqual(res.intent_category, IntentCategory.COMBINED)
        self.assertEqual(res.wmo_ids, ["1902671"])

    def test_50_hybrid_mixed_salinity_comparison_and_pss78_scale(self):
        """Verify mixed question with salinity comparison and PSS-78 scale explanation routes to HYBRID."""
        mock_intent = QueryIntent(
            intent_type=IntentType.DATA_ONLY,
            intent_category=IntentCategory.COMPARISON,
            physical_variables=[PhysicalVariable.PSAL],
            wmo_ids=["1902671"],
        )
        self.mock_provider.generate_structured.return_value = mock_intent

        res = self.agent.analyze(
            "Compare salinity measurements for float 1902671 and explain the PSS-78 scale."
        )
        self.assertEqual(res.intent_type, IntentType.HYBRID)
        self.assertEqual(res.intent_category, IntentCategory.COMBINED)

    def test_51_hybrid_mixed_profile_plot_and_depth_explanation(self):
        """Verify mixed question with vertical profile plot and depth variation explanation routes to HYBRID."""
        mock_intent = QueryIntent(
            intent_type=IntentType.DATA_ONLY,
            intent_category=IntentCategory.PRESSURE_DEPTH,
            physical_variables=[PhysicalVariable.TEMP],
            wmo_ids=["1902671"],
        )
        self.mock_provider.generate_structured.return_value = mock_intent

        res = self.agent.analyze(
            "Plot the temperature profile for float 1902671 and explain why temperature changes with depth."
        )
        self.assertEqual(res.intent_type, IntentType.HYBRID)
        self.assertEqual(res.intent_category, IntentCategory.COMBINED)

    def test_52_data_only_classification_preserves_pure_observational_query(self):
        """Verify pure observational database queries retain DATA_ONLY classification."""
        mock_intent = QueryIntent(
            intent_type=IntentType.DATA_ONLY,
            intent_category=IntentCategory.AGGREGATION,
            physical_variables=[PhysicalVariable.TEMP, PhysicalVariable.PSAL],
            wmo_ids=["1902671"],
            aggregation_operation=AggregationOp.AVERAGE,
        )
        self.mock_provider.generate_structured.return_value = mock_intent

        res = self.agent.analyze(
            "Show the average temperature and salinity observations for float 1902671."
        )
        self.assertEqual(res.intent_type, IntentType.DATA_ONLY)
        self.assertEqual(res.intent_category, IntentCategory.AGGREGATION)

    def test_53_knowledge_only_classification_preserves_pure_conceptual_query(self):
        """Verify pure conceptual/documentation questions retain KNOWLEDGE_ONLY classification."""
        mock_intent = QueryIntent(
            intent_type=IntentType.KNOWLEDGE_ONLY,
            intent_category=IntentCategory.RETRIEVAL,
            physical_variables=[],
            wmo_ids=[],
        )
        self.mock_provider.generate_structured.return_value = mock_intent

        res = self.agent.analyze(
            "Explain the PSS-78 practical salinity scale and its relevance to ARGO floats."
        )
        self.assertEqual(res.intent_type, IntentType.KNOWLEDGE_ONLY)
        self.assertEqual(res.intent_category, IntentCategory.RETRIEVAL)

    def test_54_explain_observations_without_conceptual_theory_remains_data_only(self):
        """Verify 'explain the observations' without scientific concept retains DATA_ONLY."""
        mock_intent = QueryIntent(
            intent_type=IntentType.DATA_ONLY,
            intent_category=IntentCategory.FILTERING,
            physical_variables=[PhysicalVariable.TEMP],
            wmo_ids=["1902671"],
        )
        self.mock_provider.generate_structured.return_value = mock_intent

        res = self.agent.analyze(
            "Explain the temperature observations for float 1902671."
        )
        self.assertEqual(res.intent_type, IntentType.DATA_ONLY)


if __name__ == "__main__":
    unittest.main()
