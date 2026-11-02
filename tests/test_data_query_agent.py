"""
tests/test_data_query_agent.py

Phase 6A — Data Query Agent Unit Test Suite.
Verifies QueryIntent to candidate SQL generation, deterministic AST validation enforcement,
intent routing (DATA_ONLY, HYBRID, KNOWLEDGE_ONLY), error handling, bounded retry logic,
and rejection of obsolete schema names (wmo_id, pres, temp, psal) or unsafe SQL.

All unit tests run completely offline using unittest.mock.
Zero active database connections or external network dependencies.
"""

import os
import sys
import unittest
from unittest.mock import MagicMock

# Ensure src is in python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.agents.data_query import (
    AmbiguousIntentError,
    DataQueryAgent,
    DataQueryResult,
    DataQueryStatus,
    InsufficientIntentError,
    SQLCandidate,
    SQLGenerationError,
    SQLValidationError,
    UnsupportedIntentError,
)
from src.agents.data_query.prompts import (
    DATA_QUERY_SYSTEM_PROMPT,
    build_data_query_prompt,
    build_sql_retry_prompt,
)
from src.agents.query_understanding import (
    AggregationOp,
    ComparisonTarget,
    IntentCategory,
    IntentType,
    PhysicalVariable,
    PressureRange,
    QueryIntent,
    SpatialBounds,
    TemporalRange,
)
from src.llm import BaseLLMProvider, GenerationResult, LLMResponseError, LLMTimeoutError
from src.security.sql_validator import DeterministicSQLValidator


class TestDataQueryAgent(unittest.TestCase):

    def setUp(self):
        self.mock_provider = MagicMock(spec=BaseLLMProvider)
        self.validator = DeterministicSQLValidator()
        self.agent = DataQueryAgent(
            llm_provider=self.mock_provider,
            validator=self.validator,
            enable_retry=True,
        )

    # ===================================================================
    # 1. Valid DATA_ONLY Intent & Validation Pass
    # ===================================================================

    def test_01_valid_data_only_intent_passes_validation(self):
        """Verify that a valid DATA_ONLY intent generates SQL and passes validation."""
        intent = QueryIntent(
            intent_type=IntentType.DATA_ONLY,
            intent_category=IntentCategory.FILTERING,
            physical_variables=[PhysicalVariable.TEMP],
            spatial_bounds=SpatialBounds(latitude_min=10.0, latitude_max=20.0),
        )
        candidate = SQLCandidate(
            sql="SELECT p.platform_number, p.latitude, p.longitude, m.pressure_dbar, m.temperature_c "
                "FROM argo_profiles p JOIN argo_measurements m ON p.profile_id = m.profile_id "
                "WHERE p.latitude BETWEEN 10.0 AND 20.0 LIMIT 100",
            explanation="Filtered by latitude bounds and temperature."
        )
        self.mock_provider.generate_structured.return_value = candidate

        result: DataQueryResult = self.agent.generate_sql(intent)

        self.assertEqual(result.status, DataQueryStatus.SUCCESS)
        self.assertTrue(result.is_success)
        self.assertIsNotNone(result.sql)
        self.assertIn("argo_profiles", result.sql)
        self.assertIn("argo_measurements", result.sql)
        self.assertEqual(result.retry_count, 0)
        self.mock_provider.generate_structured.assert_called_once()

    # ===================================================================
    # 2. HYBRID Intent Follows Supported Data-Query Path
    # ===================================================================

    def test_02_hybrid_intent_follows_data_query_path(self):
        """Verify that HYBRID intent triggers SQL generation for the observation data portion."""
        intent = QueryIntent(
            intent_type=IntentType.HYBRID,
            intent_category=IntentCategory.COMBINED,
            physical_variables=[PhysicalVariable.PSAL],
            wmo_ids=["2901550"],
        )
        candidate = SQLCandidate(
            sql="SELECT p.platform_number, m.pressure_dbar, m.salinity_psu "
                "FROM argo_profiles p JOIN argo_measurements m ON p.profile_id = m.profile_id "
                "WHERE p.platform_number = '2901550' LIMIT 50",
            explanation="Observation query for float 2901550 salinity."
        )
        self.mock_provider.generate_structured.return_value = candidate

        result: DataQueryResult = self.agent.generate_sql(intent)

        self.assertEqual(result.status, DataQueryStatus.SUCCESS)
        self.assertIn("2901550", result.sql)
        self.mock_provider.generate_structured.assert_called_once()

    # ===================================================================
    # 3. KNOWLEDGE_ONLY Does Not Call LLM Provider
    # ===================================================================

    def test_03_knowledge_only_returns_no_sql_without_calling_llm(self):
        """Verify that KNOWLEDGE_ONLY intent returns NO_SQL_REQUIRED without calling LLM."""
        intent = QueryIntent(
            intent_type=IntentType.KNOWLEDGE_ONLY,
            intent_category=IntentCategory.RETRIEVAL,
        )

        result: DataQueryResult = self.agent.generate_sql(intent)

        self.assertEqual(result.status, DataQueryStatus.NO_SQL_REQUIRED)
        self.assertIsNone(result.sql)
        self.assertFalse(result.is_success)
        self.mock_provider.generate_structured.assert_not_called()
        self.mock_provider.generate.assert_not_called()

    # ===================================================================
    # 4. LLM Generation Failure Handled Safely
    # ===================================================================

    def test_04_llm_generation_failure_handled_safely(self):
        """Verify that LLM timeout or connection failure returns GENERATION_FAILED."""
        intent = QueryIntent(
            intent_type=IntentType.DATA_ONLY,
            intent_category=IntentCategory.FILTERING,
            physical_variables=[PhysicalVariable.TEMP],
        )
        self.mock_provider.generate_structured.side_effect = LLMTimeoutError("Ollama request timed out.")
        self.mock_provider.generate.side_effect = LLMTimeoutError("Fallback also timed out.")

        result: DataQueryResult = self.agent.generate_sql(intent)

        self.assertEqual(result.status, DataQueryStatus.GENERATION_FAILED)
        self.assertIsNone(result.sql)
        self.assertIn("timed out", result.error_message.lower())

    def test_04b_llm_generation_failure_with_raise_on_failure(self):
        """Verify that SQLGenerationError is raised when raise_on_failure=True."""
        intent = QueryIntent(
            intent_type=IntentType.DATA_ONLY,
            intent_category=IntentCategory.FILTERING,
            physical_variables=[PhysicalVariable.TEMP],
        )
        self.mock_provider.generate_structured.side_effect = LLMResponseError("HTTP 500 error")
        self.mock_provider.generate.side_effect = LLMResponseError("HTTP 500 error")

        with self.assertRaises(SQLGenerationError):
            self.agent.generate_sql(intent, raise_on_failure=True)

    # ===================================================================
    # 5. Invalid SQL Syntax Rejected
    # ===================================================================

    def test_05_invalid_sql_syntax_rejected(self):
        """Verify that syntactically malformed SQL is rejected by the validator."""
        agent_no_retry = DataQueryAgent(
            llm_provider=self.mock_provider,
            validator=self.validator,
            enable_retry=False,
        )
        intent = QueryIntent(
            intent_type=IntentType.DATA_ONLY,
            intent_category=IntentCategory.FILTERING,
            physical_variables=[PhysicalVariable.TEMP],
        )
        candidate = SQLCandidate(
            sql="SELECT FROM WHERE argo_profiles",
            explanation="Malformed SQL statement."
        )
        self.mock_provider.generate_structured.return_value = candidate

        result: DataQueryResult = agent_no_retry.generate_sql(intent)

        self.assertEqual(result.status, DataQueryStatus.VALIDATION_FAILED)
        self.assertIsNone(result.sql)
        self.assertTrue(len(result.validation_errors) > 0)

    # ===================================================================
    # 6. Disallowed Table or Column Cannot Be Returned as Validated SQL
    # ===================================================================

    def test_06a_disallowed_table_rejected(self):
        """Verify that SQL targeting an unapproved table is rejected."""
        agent_no_retry = DataQueryAgent(
            llm_provider=self.mock_provider,
            validator=self.validator,
            enable_retry=False,
        )
        intent = QueryIntent(
            intent_type=IntentType.DATA_ONLY,
            intent_category=IntentCategory.FILTERING,
            physical_variables=[PhysicalVariable.TEMP],
        )
        candidate = SQLCandidate(
            sql="SELECT * FROM ocean_observations LIMIT 10",
            explanation="Targeting nonexistent table."
        )
        self.mock_provider.generate_structured.return_value = candidate

        result = agent_no_retry.generate_sql(intent)

        self.assertEqual(result.status, DataQueryStatus.VALIDATION_FAILED)
        self.assertIsNone(result.sql)
        self.assertTrue(any("unauthorized table" in err.lower() for err in result.validation_errors))

    def test_06b_disallowed_column_rejected(self):
        """Verify that SQL referencing unauthorized columns is rejected."""
        agent_no_retry = DataQueryAgent(
            llm_provider=self.mock_provider,
            validator=self.validator,
            enable_retry=False,
        )
        intent = QueryIntent(
            intent_type=IntentType.DATA_ONLY,
            intent_category=IntentCategory.FILTERING,
            physical_variables=[PhysicalVariable.TEMP],
        )
        candidate = SQLCandidate(
            sql="SELECT secret_token, password FROM argo_floats LIMIT 10",
            explanation="Targeting unauthorized columns."
        )
        self.mock_provider.generate_structured.return_value = candidate

        result = agent_no_retry.generate_sql(intent)

        self.assertEqual(result.status, DataQueryStatus.VALIDATION_FAILED)
        self.assertIsNone(result.sql)
        self.assertTrue(any("unauthorized column" in err.lower() for err in result.validation_errors))

    # ===================================================================
    # 7. Multi-Statement or Unsafe Candidate Cannot Bypass Validation
    # ===================================================================

    def test_07a_multi_statement_injection_rejected(self):
        """Verify that multi-statement SQL injection attempts are caught and rejected."""
        agent_no_retry = DataQueryAgent(
            llm_provider=self.mock_provider,
            validator=self.validator,
            enable_retry=False,
        )
        intent = QueryIntent(
            intent_type=IntentType.DATA_ONLY,
            intent_category=IntentCategory.FILTERING,
            physical_variables=[PhysicalVariable.TEMP],
        )
        candidate = SQLCandidate(
            sql="SELECT platform_number FROM argo_floats; DROP TABLE argo_floats;",
            explanation="Injection attempt."
        )
        self.mock_provider.generate_structured.return_value = candidate

        result = agent_no_retry.generate_sql(intent)

        self.assertEqual(result.status, DataQueryStatus.VALIDATION_FAILED)
        self.assertIsNone(result.sql)
        self.assertTrue(any("multiple" in err.lower() for err in result.validation_errors))

    def test_07b_non_select_statement_rejected(self):
        """Verify that non-SELECT statements (DELETE, INSERT, UPDATE) are rejected."""
        agent_no_retry = DataQueryAgent(
            llm_provider=self.mock_provider,
            validator=self.validator,
            enable_retry=False,
        )
        intent = QueryIntent(
            intent_type=IntentType.DATA_ONLY,
            intent_category=IntentCategory.FILTERING,
            physical_variables=[PhysicalVariable.TEMP],
        )
        candidate = SQLCandidate(
            sql="DELETE FROM argo_measurements WHERE pressure_dbar < 10.0",
            explanation="Destructive operation."
        )
        self.mock_provider.generate_structured.return_value = candidate

        result = agent_no_retry.generate_sql(intent)

        self.assertEqual(result.status, DataQueryStatus.VALIDATION_FAILED)
        self.assertIsNone(result.sql)
        self.assertTrue(any("only select" in err.lower() for err in result.validation_errors))

    # ===================================================================
    # 8. Unsupported or Insufficient Intent Handled Explicitly
    # ===================================================================

    def test_08a_unsupported_intent_rejected_without_llm_call(self):
        """Verify that unsupported intent (is_supported=False) returns UNSUPPORTED_INTENT."""
        intent = QueryIntent(
            intent_type=IntentType.DATA_ONLY,
            intent_category=IntentCategory.FILTERING,
            is_supported=False,
            unsupported_reason="Oxygen sensors are not supported in V1 dataset.",
        )

        result = self.agent.generate_sql(intent)

        self.assertEqual(result.status, DataQueryStatus.UNSUPPORTED_INTENT)
        self.assertIsNone(result.sql)
        self.assertIn("Oxygen", result.error_message)
        self.mock_provider.generate_structured.assert_not_called()

    def test_08b_ambiguous_intent_rejected_without_llm_call(self):
        """Verify that ambiguous intent (needs_clarification=True) returns AMBIGUOUS_INTENT."""
        intent = QueryIntent(
            intent_type=IntentType.DATA_ONLY,
            intent_category=IntentCategory.FILTERING,
            needs_clarification=True,
            clarification_question="Did you mean temperature or salinity?",
        )

        result = self.agent.generate_sql(intent)

        self.assertEqual(result.status, DataQueryStatus.AMBIGUOUS_INTENT)
        self.assertIsNone(result.sql)
        self.assertIn("temperature or salinity", result.error_message)
        self.mock_provider.generate_structured.assert_not_called()

    def test_08c_insufficient_intent_rejected_without_llm_call(self):
        """Verify that empty intent with no filters/variables returns INSUFFICIENT_INTENT."""
        intent = QueryIntent(
            intent_type=IntentType.DATA_ONLY,
            intent_category=IntentCategory.FILTERING,
            # No physical variables, no spatial bounds, no temporal range, no WMO IDs
        )

        result = self.agent.generate_sql(intent)

        self.assertEqual(result.status, DataQueryStatus.INSUFFICIENT_INTENT)
        self.assertIsNone(result.sql)
        self.assertIn("insufficient criteria", result.error_message.lower())
        self.mock_provider.generate_structured.assert_not_called()

    # ===================================================================
    # 9. Schema Column Naming: Rejection of Obsolete Column Names
    # ===================================================================

    def test_09a_obsolete_wmo_id_column_rejected_by_validator(self):
        """Verify that SQL containing obsolete 'wmo_id' column fails validation."""
        agent_no_retry = DataQueryAgent(
            llm_provider=self.mock_provider,
            validator=self.validator,
            enable_retry=False,
        )
        intent = QueryIntent(
            intent_type=IntentType.DATA_ONLY,
            intent_category=IntentCategory.FLOAT_SPECIFIC,
            wmo_ids=["2901550"],
        )
        candidate = SQLCandidate(
            sql="SELECT wmo_id FROM argo_floats WHERE wmo_id = '2901550'",
            explanation="Using obsolete column wmo_id."
        )
        self.mock_provider.generate_structured.return_value = candidate

        result = agent_no_retry.generate_sql(intent)

        self.assertEqual(result.status, DataQueryStatus.VALIDATION_FAILED)
        self.assertTrue(any("wmo_id" in err for err in result.validation_errors))

    def test_09b_obsolete_pres_temp_psal_columns_rejected_by_validator(self):
        """Verify that SQL containing obsolete 'pres', 'temp', 'psal' columns fails validation."""
        agent_no_retry = DataQueryAgent(
            llm_provider=self.mock_provider,
            validator=self.validator,
            enable_retry=False,
        )
        intent = QueryIntent(
            intent_type=IntentType.DATA_ONLY,
            intent_category=IntentCategory.FILTERING,
            physical_variables=[PhysicalVariable.TEMP, PhysicalVariable.PSAL],
        )
        candidate = SQLCandidate(
            sql="SELECT pres, temp, psal FROM argo_measurements",
            explanation="Using obsolete column names pres, temp, psal."
        )
        self.mock_provider.generate_structured.return_value = candidate

        result = agent_no_retry.generate_sql(intent)

        self.assertEqual(result.status, DataQueryStatus.VALIDATION_FAILED)
        self.assertTrue(any("pres" in err for err in result.validation_errors))

    def test_09c_physical_column_names_accepted_by_validator(self):
        """Verify that SQL using physical column names passes validation."""
        intent = QueryIntent(
            intent_type=IntentType.DATA_ONLY,
            intent_category=IntentCategory.FILTERING,
            physical_variables=[PhysicalVariable.PRES, PhysicalVariable.TEMP, PhysicalVariable.PSAL],
            wmo_ids=["2901550"],
        )
        candidate = SQLCandidate(
            sql="SELECT p.platform_number, m.pressure_dbar, m.temperature_c, m.salinity_psu "
                "FROM argo_profiles p JOIN argo_measurements m ON p.profile_id = m.profile_id "
                "WHERE p.platform_number = '2901550' LIMIT 100",
            explanation="Using correct physical schema names."
        )
        self.mock_provider.generate_structured.return_value = candidate

        result = self.agent.generate_sql(intent)

        self.assertEqual(result.status, DataQueryStatus.SUCCESS)
        self.assertIn("platform_number", result.sql)
        self.assertIn("pressure_dbar", result.sql)
        self.assertIn("temperature_c", result.sql)
        self.assertIn("salinity_psu", result.sql)

    # ===================================================================
    # 10. Existing Validator Behavior Preserved
    # ===================================================================

    def test_10_validator_limit_policy_preservation(self):
        """Verify that the agent preserves validator's automatic LIMIT injection and capping."""
        intent = QueryIntent(
            intent_type=IntentType.DATA_ONLY,
            intent_category=IntentCategory.FILTERING,
            physical_variables=[PhysicalVariable.TEMP],
        )
        # Query has no LIMIT clause
        candidate = SQLCandidate(
            sql="SELECT p.platform_number, m.temperature_c "
                "FROM argo_profiles p JOIN argo_measurements m ON p.profile_id = m.profile_id",
            explanation="No limit specified."
        )
        self.mock_provider.generate_structured.return_value = candidate

        result = self.agent.generate_sql(intent)

        self.assertEqual(result.status, DataQueryStatus.SUCCESS)
        # Validator must have injected default safety LIMIT (500)
        self.assertIn("LIMIT 500", result.sql)
        self.assertTrue(len(result.validation_warnings) > 0)

    # ===================================================================
    # 11. Bounded Single Regeneration on Validation Failure
    # ===================================================================

    def test_11a_bounded_retry_succeeds_on_second_attempt(self):
        """Verify that a single recoverable validation failure triggers bounded retry and succeeds."""
        intent = QueryIntent(
            intent_type=IntentType.DATA_ONLY,
            intent_category=IntentCategory.FILTERING,
            physical_variables=[PhysicalVariable.TEMP],
        )
        # Attempt 1: Uses invalid column 'temp'
        bad_candidate = SQLCandidate(
            sql="SELECT p.platform_number, m.temp FROM argo_profiles p JOIN argo_measurements m ON p.profile_id = m.profile_id",
            explanation="Used temp."
        )
        # Attempt 2: Fixes to 'temperature_c'
        good_candidate = SQLCandidate(
            sql="SELECT p.platform_number, m.temperature_c FROM argo_profiles p JOIN argo_measurements m ON p.profile_id = m.profile_id LIMIT 100",
            explanation="Corrected to temperature_c."
        )
        self.mock_provider.generate_structured.side_effect = [bad_candidate, good_candidate]

        result = self.agent.generate_sql(intent)

        self.assertEqual(result.status, DataQueryStatus.SUCCESS)
        self.assertEqual(result.retry_count, 1)
        self.assertIn("temperature_c", result.sql)
        self.assertEqual(self.mock_provider.generate_structured.call_count, 2)

    def test_11b_bounded_retry_stops_after_single_attempt_if_still_failing(self):
        """Verify that retry stops after exactly 1 attempt if the candidate still fails validation."""
        intent = QueryIntent(
            intent_type=IntentType.DATA_ONLY,
            intent_category=IntentCategory.FILTERING,
            physical_variables=[PhysicalVariable.TEMP],
        )
        # Both attempts use invalid column
        bad_candidate = SQLCandidate(
            sql="SELECT temp FROM argo_measurements",
            explanation="Still invalid."
        )
        self.mock_provider.generate_structured.return_value = bad_candidate

        result = self.agent.generate_sql(intent)

        self.assertEqual(result.status, DataQueryStatus.VALIDATION_FAILED)
        self.assertEqual(result.retry_count, 1)
        self.assertIsNone(result.sql)
        # Verify provider called exactly twice (1 initial + 1 retry)
        self.assertEqual(self.mock_provider.generate_structured.call_count, 2)

    # ===================================================================
    # 12. Text Generation Fallback & SQL Markdown Cleaning
    # ===================================================================

    def test_12_text_generation_fallback_cleans_markdown_fences(self):
        """Verify that if structured output is unavailable, text fallback extracts and cleans SQL."""
        intent = QueryIntent(
            intent_type=IntentType.DATA_ONLY,
            intent_category=IntentCategory.FILTERING,
            physical_variables=[PhysicalVariable.TEMP],
        )
        # generate_structured raises NotImplementedError
        self.mock_provider.generate_structured.side_effect = NotImplementedError()
        self.mock_provider.generate.return_value = GenerationResult(
            text="```sql\nSELECT platform_number FROM argo_floats LIMIT 20;\n```"
        )

        result = self.agent.generate_sql(intent)

        self.assertEqual(result.status, DataQueryStatus.SUCCESS)
        self.assertIn("argo_floats", result.sql)
        self.assertNotIn("```", result.sql)

    # ===================================================================
    # 13. Prompt Builder Unit Tests
    # ===================================================================

    def test_13_prompt_builder_includes_all_intent_slots(self):
        """Verify that build_data_query_prompt formats all slots correctly."""
        intent = QueryIntent(
            intent_type=IntentType.DATA_ONLY,
            intent_category=IntentCategory.STATISTICS,
            physical_variables=[PhysicalVariable.TEMP, PhysicalVariable.PSAL],
            aggregation_operation=AggregationOp.AVERAGE,
            spatial_bounds=SpatialBounds(latitude_min=0.0, latitude_max=15.0, longitude_min=60.0, longitude_max=80.0),
            temporal_range=TemporalRange(start_date="2024-01-01", end_date="2024-01-31"),
            pressure_range=PressureRange(pressure_min=0.0, pressure_max=500.0, is_depth_requested=True),
            wmo_ids=["2901550", "2901551"],
            comparison_target=ComparisonTarget(is_comparison=True, comparison_targets=["2901550", "2901551"]),
        )

        prompt = build_data_query_prompt(intent)
        self.assertIn("TEMP", prompt)
        self.assertIn("PSAL", prompt)
        self.assertIn("average", prompt)
        self.assertIn("2901550", prompt)
        self.assertIn("2024-01-01", prompt)
        self.assertIn("500.0", prompt)

        retry_prompt = build_sql_retry_prompt(intent, "SELECT wmo_id FROM argo_floats", ["Unauthorized column 'wmo_id'"])
        self.assertIn("Unauthorized column 'wmo_id'", retry_prompt)
        self.assertIn("SELECT wmo_id FROM argo_floats", retry_prompt)

    def test_14_deterministic_fast_path_for_float_count(self):
        """Verify that unambiguous float count queries bypass LLM generation and pass AST validation."""
        intent = QueryIntent(
            intent_type=IntentType.DATA_ONLY,
            intent_category=IntentCategory.AGGREGATION,
            aggregation_operation=AggregationOp.COUNT,
            target_entity="floats",
        )
        result: DataQueryResult = self.agent.generate_sql(intent, query="How many floats are in the database?")
        self.assertEqual(result.status, DataQueryStatus.SUCCESS)
        self.assertIn("argo_floats", result.sql)
        self.assertIn("COUNT(*)", result.sql)
        self.mock_provider.generate_structured.assert_not_called()

    def test_15_deterministic_fast_path_for_profile_count(self):
        """Verify that unambiguous profile count queries target argo_profiles and bypass LLM."""
        intent = QueryIntent(
            intent_type=IntentType.DATA_ONLY,
            intent_category=IntentCategory.AGGREGATION,
            aggregation_operation=AggregationOp.COUNT,
            target_entity="profiles",
        )
        result: DataQueryResult = self.agent.generate_sql(intent, query="How many total profiles are in the database?")
        self.assertEqual(result.status, DataQueryStatus.SUCCESS)
        self.assertIn("argo_profiles", result.sql)
        self.assertIn("total_profiles", result.sql)
        self.mock_provider.generate_structured.assert_not_called()

    def test_16_deterministic_fast_path_for_measurement_count(self):
        """Verify that unambiguous measurement count queries target argo_measurements and bypass LLM."""
        intent = QueryIntent(
            intent_type=IntentType.DATA_ONLY,
            intent_category=IntentCategory.AGGREGATION,
            aggregation_operation=AggregationOp.COUNT,
            target_entity="measurements",
        )
        result: DataQueryResult = self.agent.generate_sql(intent, query="How many measurements are in the database?")
        self.assertEqual(result.status, DataQueryStatus.SUCCESS)
        self.assertIn("argo_measurements", result.sql)
        self.assertIn("total_measurements", result.sql)
        self.mock_provider.generate_structured.assert_not_called()

    def test_17_filtered_count_does_not_use_fast_path(self):
        """Verify that filtered count queries do NOT use the unfiltered fast path."""
        intent = QueryIntent(
            intent_type=IntentType.DATA_ONLY,
            intent_category=IntentCategory.AGGREGATION,
            aggregation_operation=AggregationOp.COUNT,
            target_entity="profiles",
            spatial_bounds=SpatialBounds(latitude_min=10.0, latitude_max=20.0),
        )
        self.mock_provider.generate_structured.return_value = SQLCandidate(
            sql="SELECT COUNT(*) AS profile_count FROM argo_profiles WHERE latitude >= 10.0 AND latitude <= 20.0;",
            explanation="Filtered count of profiles in northern latitudes."
        )
        result: DataQueryResult = self.agent.generate_sql(intent, query="How many profiles between latitude 10 and 20?")
        self.assertEqual(result.status, DataQueryStatus.SUCCESS)
        self.mock_provider.generate_structured.assert_called_once()
        self.assertIn("latitude", result.sql)

    def test_18_observation_level_query_prompt_instructions(self):
        """Verify prompt guidance instructs observation rows when aggregation is null."""
        intent = QueryIntent(
            intent_type=IntentType.DATA_ONLY,
            intent_category=IntentCategory.FILTERING,
            physical_variables=[PhysicalVariable.TEMP, PhysicalVariable.PSAL],
            wmo_ids=["1902671"],
            aggregation_operation=None,
        )
        prompt = build_data_query_prompt(intent)
        self.assertIn("Observational queries", prompt)
        self.assertIn("pressure_dbar", prompt)
        self.assertIn("temperature_c", prompt)
        self.assertIn("salinity_psu", prompt)
        self.assertIn("Do NOT use AVG()", prompt)

    def test_19_explicit_statistical_query_prompt_instructions(self):
        """Verify prompt guidance instructs aggregate functions when aggregation operation is set."""
        intent = QueryIntent(
            intent_type=IntentType.DATA_ONLY,
            intent_category=IntentCategory.AGGREGATION,
            physical_variables=[PhysicalVariable.TEMP],
            aggregation_operation=AggregationOp.AVERAGE,
        )
        prompt = build_data_query_prompt(intent)
        self.assertIn("Statistical queries", prompt)
        self.assertIn("GROUP BY", prompt)

    # ===================================================================
    # 14. Stage 8B Phase 3: Statistical, Temporal, Comparison & Few-Shot Regression Tests
    # ===================================================================

    def test_20_system_prompt_contains_statistical_guidance(self):
        """Verify system prompt contains complete statistical functions guidance."""
        self.assertIn("STDDEV", DATA_QUERY_SYSTEM_PROMPT)
        self.assertIn("STDDEV_SAMP", DATA_QUERY_SYSTEM_PROMPT)
        self.assertIn("STDDEV_POP", DATA_QUERY_SYSTEM_PROMPT)
        self.assertIn("VARIANCE", DATA_QUERY_SYSTEM_PROMPT)
        self.assertIn("VAR_SAMP", DATA_QUERY_SYSTEM_PROMPT)
        self.assertIn("VAR_POP", DATA_QUERY_SYSTEM_PROMPT)
        self.assertIn("PERCENTILE_CONT", DATA_QUERY_SYSTEM_PROMPT)
        self.assertIn("WITHIN GROUP", DATA_QUERY_SYSTEM_PROMPT)
        self.assertIn("PostgreSQL does NOT support `MEDIAN()`", DATA_QUERY_SYSTEM_PROMPT)
        self.assertIn("IS NOT NULL", DATA_QUERY_SYSTEM_PROMPT)

    def test_21_system_prompt_forbids_window_functions(self):
        """Verify system prompt explicitly forbids window functions and OVER clauses."""
        self.assertIn("NEVER use window functions or `OVER (...)`", DATA_QUERY_SYSTEM_PROMPT)

    def test_22_system_prompt_temporal_extract_guidance(self):
        """Verify system prompt instructs EXTRACT and forbids DATE_TRUNC, TO_CHAR, and unapproved aliases."""
        self.assertIn("EXTRACT(month FROM p.profile_time)", DATA_QUERY_SYSTEM_PROMPT)
        self.assertIn("Do NOT use `DATE_TRUNC` or `TO_CHAR`", DATA_QUERY_SYSTEM_PROMPT)
        self.assertIn("NEVER reference unapproved SELECT aliases in `ORDER BY`", DATA_QUERY_SYSTEM_PROMPT)
        self.assertIn("ORDER BY 1 ASC", DATA_QUERY_SYSTEM_PROMPT)

    def test_23_system_prompt_multi_float_comparison_guidance(self):
        """Verify system prompt instructs IN clause and grouping for comparisons."""
        self.assertIn("p.platform_number IN ('id1', 'id2', ...)", DATA_QUERY_SYSTEM_PROMPT)
        self.assertIn("Group by `p.platform_number`", DATA_QUERY_SYSTEM_PROMPT)
        self.assertIn("ORDER BY p.platform_number, p.profile_time DESC, m.pressure_dbar ASC", DATA_QUERY_SYSTEM_PROMPT)

    def test_24_build_prompt_statistical_intent_reminder(self):
        """Verify build_data_query_prompt adds statistical reminder for STATISTICS category."""
        intent = QueryIntent(
            intent_type=IntentType.DATA_ONLY,
            intent_category=IntentCategory.STATISTICS,
            physical_variables=[PhysicalVariable.TEMP],
        )
        prompt = build_data_query_prompt(intent)
        self.assertIn("Statistical analysis:", prompt)
        self.assertIn("PERCENTILE_CONT(0.5) WITHIN GROUP", prompt)
        self.assertIn("NEVER use MEDIAN()", prompt)

    def test_25_build_prompt_comparison_intent_reminder(self):
        """Verify build_data_query_prompt adds comparison reminder when is_comparison is True."""
        intent = QueryIntent(
            intent_type=IntentType.DATA_ONLY,
            intent_category=IntentCategory.COMPARISON,
            physical_variables=[PhysicalVariable.TEMP],
            wmo_ids=["1902671", "1902672"],
            comparison_target=ComparisonTarget(
                is_comparison=True,
                comparison_targets=["1902671", "1902672"],
            ),
        )
        prompt = build_data_query_prompt(intent)
        self.assertIn("Comparison query:", prompt)
        self.assertIn("p.platform_number IN (...)", prompt)
        self.assertIn("group by `p.platform_number`", prompt)

    def test_26_build_prompt_temporal_intent_reminder(self):
        """Verify build_data_query_prompt adds temporal reminder when temporal_range is set."""
        intent = QueryIntent(
            intent_type=IntentType.DATA_ONLY,
            intent_category=IntentCategory.TEMPORAL,
            physical_variables=[PhysicalVariable.TEMP],
            temporal_range=TemporalRange(start_date="2024-01-01", end_date="2024-12-31"),
        )
        prompt = build_data_query_prompt(intent)
        self.assertIn("Temporal query:", prompt)
        self.assertIn("EXTRACT(month FROM p.profile_time)", prompt)
        self.assertIn("Do NOT use DATE_TRUNC", prompt)

    def test_27_build_prompt_spatial_intent_reminder(self):
        """Verify build_data_query_prompt adds spatial reminder when spatial_bounds are set."""
        intent = QueryIntent(
            intent_type=IntentType.DATA_ONLY,
            intent_category=IntentCategory.FILTERING,
            physical_variables=[PhysicalVariable.TEMP],
            spatial_bounds=SpatialBounds(latitude_min=18.0, latitude_max=24.0, longitude_min=58.0, longitude_max=74.0),
        )
        prompt = build_data_query_prompt(intent)
        self.assertIn("Spatial query:", prompt)
        self.assertIn("latitude BETWEEN", prompt)
        self.assertIn("Never invent coordinates", prompt)

    def test_28_representative_combined_statistics_sql_passes_validator(self):
        """Verify representative combined statistics candidate SQL passes AST validation."""
        sql = (
            "SELECT AVG(m.temperature_c) AS avg_temperature_c, "
            "STDDEV_SAMP(m.temperature_c) AS std_temperature_c, "
            "MIN(m.temperature_c) AS min_temperature_c, "
            "MAX(m.temperature_c) AS max_temperature_c, "
            "COUNT(*) AS observation_count "
            "FROM argo_profiles p "
            "JOIN argo_measurements m ON p.profile_id = m.profile_id "
            "WHERE p.latitude BETWEEN 18.0 AND 24.0 "
            "AND p.longitude BETWEEN 58.0 AND 74.0 "
            "AND m.temperature_c IS NOT NULL;"
        )
        res = self.validator.validate(sql)
        self.assertTrue(res.valid, f"Validation failed with errors: {res.errors}")

    def test_29_representative_median_percentile_cont_sql_passes_validator(self):
        """Verify representative median PERCENTILE_CONT candidate SQL passes AST validation."""
        sql = (
            "SELECT PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY m.temperature_c) AS median_temperature_c, "
            "COUNT(*) AS observation_count "
            "FROM argo_profiles p "
            "JOIN argo_measurements m ON p.profile_id = m.profile_id "
            "WHERE p.platform_number = '2901550' "
            "AND m.temperature_c IS NOT NULL;"
        )
        res = self.validator.validate(sql)
        self.assertTrue(res.valid, f"Validation failed with errors: {res.errors}")

    def test_30_representative_sample_variance_sql_passes_validator(self):
        """Verify representative sample variance candidate SQL passes AST validation."""
        sql = (
            "SELECT VAR_SAMP(m.salinity_psu) AS var_salinity_psu, "
            "AVG(m.salinity_psu) AS avg_salinity_psu, "
            "COUNT(*) AS observation_count "
            "FROM argo_profiles p "
            "JOIN argo_measurements m ON p.profile_id = m.profile_id "
            "WHERE m.pressure_dbar <= 200.0 "
            "AND m.salinity_psu IS NOT NULL;"
        )
        res = self.validator.validate(sql)
        self.assertTrue(res.valid, f"Validation failed with errors: {res.errors}")

    def test_31_representative_monthly_extract_sql_passes_validator(self):
        """Verify representative monthly grouping candidate SQL using EXTRACT passes AST validation."""
        sql = (
            "SELECT EXTRACT(month FROM p.profile_time) AS month_number, "
            "AVG(m.temperature_c) AS avg_temperature_c, "
            "COUNT(*) AS observation_count "
            "FROM argo_profiles p "
            "JOIN argo_measurements m ON p.profile_id = m.profile_id "
            "WHERE p.profile_time >= '2024-01-01' "
            "AND p.profile_time < '2025-01-01' "
            "AND m.temperature_c IS NOT NULL "
            "GROUP BY EXTRACT(month FROM p.profile_time) "
            "ORDER BY 1 ASC "
            "LIMIT 100;"
        )
        res = self.validator.validate(sql)
        self.assertTrue(res.valid, f"Validation failed with errors: {res.errors}")

    def test_32_representative_multi_float_statistical_comparison_passes_validator(self):
        """Verify representative multi-float statistical comparison candidate SQL passes AST validation."""
        sql = (
            "SELECT p.platform_number, "
            "AVG(m.temperature_c) AS avg_temperature_c, "
            "MIN(m.temperature_c) AS min_temperature_c, "
            "MAX(m.temperature_c) AS max_temperature_c, "
            "COUNT(*) AS observation_count "
            "FROM argo_profiles p "
            "JOIN argo_measurements m ON p.profile_id = m.profile_id "
            "WHERE p.platform_number IN ('1902671', '1902672') "
            "AND m.temperature_c IS NOT NULL "
            "GROUP BY p.platform_number "
            "LIMIT 100;"
        )
        res = self.validator.validate(sql)
        self.assertTrue(res.valid, f"Validation failed with errors: {res.errors}")

    def test_33_representative_multi_float_observational_comparison_passes_validator(self):
        """Verify representative multi-float observational comparison candidate SQL passes AST validation."""
        sql = (
            "SELECT p.platform_number, p.profile_time, p.latitude, p.longitude, "
            "m.pressure_dbar, m.temperature_c, m.salinity_psu "
            "FROM argo_profiles p "
            "JOIN argo_measurements m ON p.profile_id = m.profile_id "
            "WHERE p.platform_number IN ('1902671', '1902672') "
            "ORDER BY p.platform_number, p.profile_time DESC, m.pressure_dbar ASC "
            "LIMIT 500;"
        )
        res = self.validator.validate(sql)
        self.assertTrue(res.valid, f"Validation failed with errors: {res.errors}")

    def test_34_representative_regional_filtering_sql_passes_validator(self):
        """Verify representative regional filtering candidate SQL passes AST validation."""
        sql = (
            "SELECT p.platform_number, p.profile_time, p.latitude, p.longitude, "
            "m.pressure_dbar, m.temperature_c, m.salinity_psu "
            "FROM argo_profiles p "
            "JOIN argo_measurements m ON p.profile_id = m.profile_id "
            "WHERE p.latitude BETWEEN 18.0 AND 24.0 "
            "AND p.longitude BETWEEN 58.0 AND 74.0 "
            "ORDER BY p.profile_time DESC, m.pressure_dbar ASC "
            "LIMIT 500;"
        )
        res = self.validator.validate(sql)
        self.assertTrue(res.valid, f"Validation failed with errors: {res.errors}")

    def test_35_end_to_end_generate_sql_statistical_intent(self):
        """Verify DataQueryAgent end-to-end generate_sql succeeds for statistical intent."""
        intent = QueryIntent(
            intent_type=IntentType.DATA_ONLY,
            intent_category=IntentCategory.STATISTICS,
            physical_variables=[PhysicalVariable.TEMP],
            spatial_bounds=SpatialBounds(latitude_min=18.0, latitude_max=24.0, longitude_min=58.0, longitude_max=74.0),
        )
        candidate = SQLCandidate(
            sql=(
                "SELECT AVG(m.temperature_c) AS avg_temperature_c, "
                "STDDEV_SAMP(m.temperature_c) AS std_temperature_c "
                "FROM argo_profiles p "
                "JOIN argo_measurements m ON p.profile_id = m.profile_id "
                "WHERE p.latitude BETWEEN 18.0 AND 24.0 AND p.longitude BETWEEN 58.0 AND 74.0 "
                "AND m.temperature_c IS NOT NULL LIMIT 100;"
            ),
            explanation="Regional statistical analysis."
        )
        self.mock_provider.generate_structured.return_value = candidate

        result = self.agent.generate_sql(intent)
        self.assertEqual(result.status, DataQueryStatus.SUCCESS)
        self.assertEqual(result.retry_count, 0)
        self.assertIn("avg_temperature_c", result.sql)
        self.assertIn("std_temperature_c", result.sql)

    # ===================================================================
    # 8. Competition Fix 5: JOIN Reliability & ID Alignment Tests
    # ===================================================================

    def test_36_missing_measurements_join_automatically_added(self):
        """Verify candidate SQL lacking argo_measurements has the required join added when measurement cols present."""
        intent = QueryIntent(
            intent_type=IntentType.DATA_ONLY,
            intent_category=IntentCategory.FILTERING,
            physical_variables=[PhysicalVariable.TEMP, PhysicalVariable.PSAL],
            wmo_ids=["1902671"],
        )
        # LLM returns query omitting argo_measurements join
        candidate = SQLCandidate(
            sql=(
                "SELECT platform_number, profile_time, latitude, longitude, pressure_dbar, temperature_c, salinity_psu "
                "FROM argo_profiles "
                "WHERE platform_number = '1902671' "
                "ORDER BY profile_time DESC, pressure_dbar ASC LIMIT 500"
            ),
            explanation="Unjoined profile observations."
        )
        self.mock_provider.generate_structured.return_value = candidate

        result = self.agent.generate_sql(intent)
        self.assertEqual(result.status, DataQueryStatus.SUCCESS)
        self.assertIn("JOIN argo_measurements", result.sql)
        self.assertIn("argo_profiles.profile_id = m.profile_id", result.sql)

    def test_37_metadata_only_query_preserves_single_table_without_join(self):
        """Verify metadata-only queries do not have an unnecessary argo_measurements join added."""
        intent = QueryIntent(
            intent_type=IntentType.DATA_ONLY,
            intent_category=IntentCategory.FILTERING,
            physical_variables=[],
            wmo_ids=["1902671"],
        )
        candidate = SQLCandidate(
            sql=(
                "SELECT platform_number, profile_time, latitude, longitude "
                "FROM argo_profiles "
                "WHERE platform_number = '1902671' LIMIT 100"
            ),
            explanation="Metadata profile coordinates."
        )
        self.mock_provider.generate_structured.return_value = candidate

        result = self.agent.generate_sql(intent)
        self.assertEqual(result.status, DataQueryStatus.SUCCESS)
        self.assertNotIn("argo_measurements", result.sql)
        self.assertIn("FROM argo_profiles", result.sql)

    def test_38_requested_float_id_preserved_when_llm_leaks_example_ids(self):
        """Verify candidate SQL with leaked few-shot IDs ('1902671', '1902672') is corrected to requested ID ('2901550')."""
        intent = QueryIntent(
            intent_type=IntentType.DATA_ONLY,
            intent_category=IntentCategory.FILTERING,
            physical_variables=[PhysicalVariable.TEMP],
            wmo_ids=["2901550"],
        )
        # LLM erroneously copies example IDs 1902671 and 1902672 from few-shot prompt
        candidate = SQLCandidate(
            sql=(
                "SELECT p.platform_number, p.profile_time, m.pressure_dbar, m.temperature_c "
                "FROM argo_profiles p "
                "JOIN argo_measurements m ON p.profile_id = m.profile_id "
                "WHERE p.platform_number IN ('1902671', '1902672') "
                "ORDER BY p.profile_time DESC, m.pressure_dbar ASC LIMIT 100"
            ),
            explanation="Float profile."
        )
        self.mock_provider.generate_structured.return_value = candidate

        result = self.agent.generate_sql(intent)
        self.assertEqual(result.status, DataQueryStatus.SUCCESS)
        self.assertIn("2901550", result.sql)
        self.assertNotIn("1902671", result.sql)
        self.assertNotIn("1902672", result.sql)

    def test_39_multiple_float_query_preserves_all_requested_ids(self):
        """Verify multiple requested float IDs are preserved and replace leaked IDs."""
        intent = QueryIntent(
            intent_type=IntentType.DATA_ONLY,
            intent_category=IntentCategory.COMPARISON,
            physical_variables=[PhysicalVariable.TEMP],
            wmo_ids=["2901550", "2901551"],
        )
        candidate = SQLCandidate(
            sql=(
                "SELECT p.platform_number, AVG(m.temperature_c) AS avg_temperature_c "
                "FROM argo_profiles p "
                "JOIN argo_measurements m ON p.profile_id = m.profile_id "
                "WHERE p.platform_number IN ('1902671', '1902672') "
                "GROUP BY p.platform_number LIMIT 100"
            ),
            explanation="Multi-float comparison."
        )
        self.mock_provider.generate_structured.return_value = candidate

        result = self.agent.generate_sql(intent)
        self.assertEqual(result.status, DataQueryStatus.SUCCESS)
        self.assertIn("2901550", result.sql)
        self.assertIn("2901551", result.sql)
        self.assertNotIn("1902671", result.sql)

    def test_40_single_float_does_not_silently_include_second_float(self):
        """Verify single float query strictly isolates to single requested float."""
        intent = QueryIntent(
            intent_type=IntentType.DATA_ONLY,
            intent_category=IntentCategory.FILTERING,
            physical_variables=[PhysicalVariable.TEMP],
            wmo_ids=["2901550"],
        )
        candidate = SQLCandidate(
            sql=(
                "SELECT p.platform_number, m.temperature_c "
                "FROM argo_profiles p "
                "JOIN argo_measurements m ON p.profile_id = m.profile_id "
                "WHERE p.platform_number = '1902671' LIMIT 50"
            ),
            explanation="Single float query."
        )
        self.mock_provider.generate_structured.return_value = candidate

        result = self.agent.generate_sql(intent)
        self.assertEqual(result.status, DataQueryStatus.SUCCESS)
        self.assertIn("2901550", result.sql)
        self.assertNotIn("1902671", result.sql)


if __name__ == "__main__":
    unittest.main()
