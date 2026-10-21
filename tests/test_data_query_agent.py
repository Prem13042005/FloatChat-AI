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


if __name__ == "__main__":
    unittest.main()
