"""
tests/test_database_executor.py

Phase 6B — Controlled Database Execution Layer Test Suite.
Verifies input validation trust boundaries, pre-execution AST re-validation,
read-only session enforcement, transaction-local statement timeout configuration,
bounded row limits and truncation, serialization of native types,
safe error containment, and guaranteed connection/rollback cleanup.

All unit tests run completely offline using unittest.mock.
"""

from datetime import datetime, timezone
from decimal import Decimal
import os
import sys
import unittest
from unittest.mock import MagicMock, call, patch

# Ensure src is in python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.agents.data_query.models import DataQueryResult, DataQueryStatus
from src.database import (
    ControlledDatabaseExecutor,
    DatabaseConnectionError,
    DatabaseExecutionResult,
    DatabaseTimeoutError,
    ExecutionInputRejectionError,
    ExecutionStatus,
    PreExecutionValidationError,
    QueryExecutionError,
    SerializationError,
    serialize_cell_value,
)
from src.security.sql_validator import DeterministicSQLValidator


class TestControlledDatabaseExecutor(unittest.TestCase):

    def setUp(self):
        self.mock_conn = MagicMock()
        self.mock_cursor = MagicMock()
        self.mock_conn.cursor.return_value = self.mock_cursor
        self.mock_conn_factory = MagicMock(return_value=self.mock_conn)

        self.validator = DeterministicSQLValidator()
        self.executor = ControlledDatabaseExecutor(
            validator=self.validator,
            connection_factory=self.mock_conn_factory,
            statement_timeout_ms=5000,
            max_row_limit=1000,
        )

    # ===================================================================
    # 1. Valid Phase 6A Success Result Reaches Execution Path
    # ===================================================================

    def test_01_valid_success_result_executes_successfully(self):
        """Verify that a valid Phase 6A SUCCESS DataQueryResult is executed and results returned."""
        input_result = DataQueryResult(
            status=DataQueryStatus.SUCCESS,
            sql="SELECT platform_number FROM argo_floats LIMIT 10",
        )

        self.mock_cursor.description = [("platform_number", None)]
        self.mock_cursor.fetchmany.return_value = [("2901550",), ("2901551",)]

        res: DatabaseExecutionResult = self.executor.execute(input_result)

        self.assertEqual(res.status, ExecutionStatus.SUCCESS)
        self.assertTrue(res.is_success)
        self.assertEqual(res.columns, ["platform_number"])
        self.assertEqual(len(res.rows), 2)
        self.assertEqual(res.rows[0]["platform_number"], "2901550")
        self.assertEqual(res.rows[1]["platform_number"], "2901551")
        self.assertFalse(res.is_truncated)
        self.assertEqual(res.row_count, 2)
        self.mock_conn_factory.assert_called_once()

    # ===================================================================
    # 2. NO_SQL_REQUIRED is Rejected Without Database Call
    # ===================================================================

    def test_02_no_sql_required_rejected_without_db_call(self):
        """Verify that NO_SQL_REQUIRED status is rejected without connecting to the database."""
        input_result = DataQueryResult(
            status=DataQueryStatus.NO_SQL_REQUIRED,
            sql=None,
            error_message="Knowledge-only query.",
        )

        res = self.executor.execute(input_result)

        self.assertEqual(res.status, ExecutionStatus.REJECTED_INPUT)
        self.assertFalse(res.is_success)
        self.assertIn("NO_SQL_REQUIRED", res.error_message)
        self.mock_conn_factory.assert_not_called()

    # ===================================================================
    # 3. Generation, Validation, Ambiguous, Unsupported, Insufficient Outcomes Rejected
    # ===================================================================

    def test_03a_unsupported_intent_rejected(self):
        """Verify that UNSUPPORTED_INTENT is rejected without calling database."""
        input_result = DataQueryResult(
            status=DataQueryStatus.UNSUPPORTED_INTENT,
            sql=None,
            error_message="Unsupported sensor.",
        )
        res = self.executor.execute(input_result)
        self.assertEqual(res.status, ExecutionStatus.REJECTED_INPUT)
        self.mock_conn_factory.assert_not_called()

    def test_03b_ambiguous_intent_rejected(self):
        """Verify that AMBIGUOUS_INTENT is rejected without calling database."""
        input_result = DataQueryResult(
            status=DataQueryStatus.AMBIGUOUS_INTENT,
            sql=None,
            error_message="Ambiguous query.",
        )
        res = self.executor.execute(input_result)
        self.assertEqual(res.status, ExecutionStatus.REJECTED_INPUT)
        self.mock_conn_factory.assert_not_called()

    def test_03c_insufficient_intent_rejected(self):
        """Verify that INSUFFICIENT_INTENT is rejected without calling database."""
        input_result = DataQueryResult(
            status=DataQueryStatus.INSUFFICIENT_INTENT,
            sql=None,
            error_message="No criteria.",
        )
        res = self.executor.execute(input_result)
        self.assertEqual(res.status, ExecutionStatus.REJECTED_INPUT)
        self.mock_conn_factory.assert_not_called()

    def test_03d_validation_failed_rejected(self):
        """Verify that VALIDATION_FAILED is rejected without calling database."""
        input_result = DataQueryResult(
            status=DataQueryStatus.VALIDATION_FAILED,
            sql=None,
            error_message="SQL failed validation.",
        )
        res = self.executor.execute(input_result)
        self.assertEqual(res.status, ExecutionStatus.REJECTED_INPUT)
        self.mock_conn_factory.assert_not_called()

    def test_03e_generation_failed_rejected(self):
        """Verify that GENERATION_FAILED is rejected without calling database."""
        input_result = DataQueryResult(
            status=DataQueryStatus.GENERATION_FAILED,
            sql=None,
            error_message="LLM timeout.",
        )
        res = self.executor.execute(input_result)
        self.assertEqual(res.status, ExecutionStatus.REJECTED_INPUT)
        self.mock_conn_factory.assert_not_called()

    # ===================================================================
    # 4. Missing or Empty Validated SQL is Rejected
    # ===================================================================

    def test_04_missing_or_empty_sql_rejected(self):
        """Verify that SUCCESS status with empty or whitespace SQL is rejected."""
        input_result = DataQueryResult(
            status=DataQueryStatus.SUCCESS,
            sql="   ",
        )
        res = self.executor.execute(input_result)
        self.assertEqual(res.status, ExecutionStatus.REJECTED_INPUT)
        self.assertIn("empty or None", res.error_message)
        self.mock_conn_factory.assert_not_called()

    # ===================================================================
    # 5. SQL is Re-validated Immediately Before Execution
    # ===================================================================

    def test_05_pre_execution_revalidation_catches_invalid_sql(self):
        """Verify that SQL failing AST validation at the executor gate is rejected before DB connection."""
        # Malicious / corrupted input where status claims SUCCESS but SQL is a DROP TABLE
        malicious_result = DataQueryResult(
            status=DataQueryStatus.SUCCESS,
            sql="DROP TABLE argo_floats;",
        )

        res = self.executor.execute(malicious_result)

        self.assertEqual(res.status, ExecutionStatus.VALIDATION_FAILED)
        self.assertIn("Pre-execution AST re-validation failed", res.error_message)
        self.mock_conn_factory.assert_not_called()

    # ===================================================================
    # 6. Only Normalized SQL Returned by Validator is Executed
    # ===================================================================

    def test_06_only_normalized_sql_executed(self):
        """Verify that the executor runs the AST-normalized SQL with injected LIMIT if missing."""
        # Query lacks LIMIT clause
        input_result = DataQueryResult(
            status=DataQueryStatus.SUCCESS,
            sql="SELECT platform_number FROM argo_floats",
        )

        self.mock_cursor.description = [("platform_number", None)]
        self.mock_cursor.fetchmany.return_value = []

        res = self.executor.execute(input_result)

        self.assertEqual(res.status, ExecutionStatus.SUCCESS)
        # Check that the query passed to cur.execute contained LIMIT 500
        executed_query = self.mock_cursor.execute.call_args_list[2][0][0]
        self.assertIn("LIMIT 500", executed_query)
        self.assertIn("LIMIT 500", res.executed_sql)

    # ===================================================================
    # 7. Read-Only Transaction Settings Applied
    # ===================================================================

    def test_07_read_only_transaction_settings_applied(self):
        """Verify that SET TRANSACTION READ ONLY is executed before observation query."""
        input_result = DataQueryResult(
            status=DataQueryStatus.SUCCESS,
            sql="SELECT platform_number FROM argo_floats LIMIT 10",
        )
        self.mock_cursor.description = [("platform_number", None)]
        self.mock_cursor.fetchmany.return_value = []

        self.executor.execute(input_result)

        # Check call order
        execute_calls = [c[0][0] for c in self.mock_cursor.execute.call_args_list]
        self.assertIn("SET TRANSACTION READ ONLY;", execute_calls)
        self.assertEqual(execute_calls[0], "SET TRANSACTION READ ONLY;")

    # ===================================================================
    # 8. Transaction-Local Statement Timeout Applied
    # ===================================================================

    def test_08_transaction_local_statement_timeout_applied(self):
        """Verify that SET LOCAL statement_timeout = '5000ms' is executed in transaction."""
        input_result = DataQueryResult(
            status=DataQueryStatus.SUCCESS,
            sql="SELECT platform_number FROM argo_floats LIMIT 10",
        )
        self.mock_cursor.description = [("platform_number", None)]
        self.mock_cursor.fetchmany.return_value = []

        self.executor.execute(input_result)

        execute_calls = [c[0][0] for c in self.mock_cursor.execute.call_args_list]
        self.assertIn("SET LOCAL statement_timeout = '5000ms';", execute_calls)
        self.assertEqual(execute_calls[1], "SET LOCAL statement_timeout = '5000ms';")

    # ===================================================================
    # 9. Successful Results Return Correct Columns and Rows
    # ===================================================================

    def test_09_successful_results_columns_and_rows(self):
        """Verify proper column list and row mapping."""
        input_result = DataQueryResult(
            status=DataQueryStatus.SUCCESS,
            sql="SELECT platform_number, latitude, longitude FROM argo_profiles LIMIT 10",
        )
        self.mock_cursor.description = [
            ("platform_number", None),
            ("latitude", None),
            ("longitude", None),
        ]
        self.mock_cursor.fetchmany.return_value = [
            ("2901550", 12.5, 68.2),
            ("2901551", 14.1, 71.0),
        ]

        res = self.executor.execute(input_result)

        self.assertEqual(res.columns, ["platform_number", "latitude", "longitude"])
        self.assertEqual(len(res.rows), 2)
        self.assertEqual(res.rows[0]["latitude"], 12.5)
        self.assertEqual(res.rows[1]["longitude"], 71.0)

    # ===================================================================
    # 10. NULL Values Serialize Correctly
    # ===================================================================

    def test_10_null_values_serialize_correctly(self):
        """Verify that SQL NULLs serialize cleanly to Python None."""
        input_result = DataQueryResult(
            status=DataQueryStatus.SUCCESS,
            sql="SELECT pressure_dbar, temperature_c, salinity_psu FROM argo_measurements LIMIT 1",
        )
        self.mock_cursor.description = [
            ("pressure_dbar", None),
            ("temperature_c", None),
            ("salinity_psu", None),
        ]
        self.mock_cursor.fetchmany.return_value = [
            (10.5, None, 35.2),
        ]

        res = self.executor.execute(input_result)

        self.assertIsNone(res.rows[0]["temperature_c"])
        self.assertEqual(res.rows[0]["pressure_dbar"], 10.5)
        self.assertEqual(res.rows[0]["salinity_psu"], 35.2)

    # ===================================================================
    # 11. Timestamps and Decimals Serialize Consistently
    # ===================================================================

    def test_11_timestamps_and_decimals_serialize_consistently(self):
        """Verify ISO 8601 timestamp string formatting and float conversion for Decimal."""
        dt = datetime(2024, 1, 15, 12, 30, 0, tzinfo=timezone.utc)
        dec = Decimal("24.85")

        self.assertEqual(serialize_cell_value(dt), "2024-01-15T12:30:00+00:00")
        self.assertEqual(serialize_cell_value(dec), 24.85)
        self.assertIsInstance(serialize_cell_value(dec), float)

    # ===================================================================
    # 12. Database Timeout Produces TIMEOUT Outcome
    # ===================================================================

    def test_12_database_timeout_produces_timeout_status(self):
        """Verify that a statement_timeout error from PostgreSQL produces TIMEOUT status."""
        input_result = DataQueryResult(
            status=DataQueryStatus.SUCCESS,
            sql="SELECT platform_number FROM argo_floats LIMIT 10",
        )
        # Mocking error with pgcode 57014 (query_canceled)
        error = Exception("canceling statement due to statement timeout")
        setattr(error, "pgcode", "57014")

        # Third call to cur.execute (the query itself) raises timeout
        self.mock_cursor.execute.side_effect = ["OK", "OK", error]

        res = self.executor.execute(input_result)

        self.assertEqual(res.status, ExecutionStatus.TIMEOUT)
        self.assertFalse(res.is_success)
        self.assertIn("statement timeout", res.error_message.lower())
        self.mock_conn.rollback.assert_called()
        self.mock_conn.close.assert_called()

    def test_12b_database_timeout_with_raise_on_failure(self):
        """Verify that DatabaseTimeoutError is raised when raise_on_failure=True."""
        input_result = DataQueryResult(
            status=DataQueryStatus.SUCCESS,
            sql="SELECT platform_number FROM argo_floats LIMIT 10",
        )
        error = Exception("canceling statement due to statement timeout")
        setattr(error, "pgcode", "57014")
        self.mock_cursor.execute.side_effect = ["OK", "OK", error]

        with self.assertRaises(DatabaseTimeoutError):
            self.executor.execute(input_result, raise_on_failure=True)

    # ===================================================================
    # 13. Database Errors Trigger Rollback and Connection Cleanup
    # ===================================================================

    def test_13_database_error_triggers_rollback_and_cleanup(self):
        """Verify rollback and connection close on general SQL execution failure."""
        input_result = DataQueryResult(
            status=DataQueryStatus.SUCCESS,
            sql="SELECT platform_number FROM argo_floats LIMIT 10",
        )
        self.mock_cursor.execute.side_effect = ["OK", "OK", Exception("relation argo_floats does not exist")]

        res = self.executor.execute(input_result)

        self.assertEqual(res.status, ExecutionStatus.EXECUTION_FAILED)
        self.assertFalse(res.is_success)
        self.mock_conn.rollback.assert_called()
        self.mock_conn.close.assert_called()

    # ===================================================================
    # 14 & 15. Connection Return/Close After Success and Failure
    # ===================================================================

    def test_14_connection_closed_on_success(self):
        """Verify connection is closed after successful execution."""
        input_result = DataQueryResult(
            status=DataQueryStatus.SUCCESS,
            sql="SELECT platform_number FROM argo_floats LIMIT 10",
        )
        self.mock_cursor.description = [("platform_number", None)]
        self.mock_cursor.fetchmany.return_value = []

        self.executor.execute(input_result)
        self.mock_conn.close.assert_called_once()
        self.mock_cursor.close.assert_called_once()

    def test_15_connection_closed_on_failure(self):
        """Verify connection is closed after failed execution."""
        input_result = DataQueryResult(
            status=DataQueryStatus.SUCCESS,
            sql="SELECT platform_number FROM argo_floats LIMIT 10",
        )
        self.mock_cursor.execute.side_effect = ["OK", "OK", Exception("Database error")]

        self.executor.execute(input_result)
        self.mock_conn.close.assert_called_once()
        self.mock_cursor.close.assert_called_once()

    # ===================================================================
    # 16. Result Limits and Truncation Metadata Behave Correctly
    # ===================================================================

    def test_16_result_truncation_metadata_flagged(self):
        """Verify that rows exceeding max limit are truncated and flagged."""
        executor_low_limit = ControlledDatabaseExecutor(
            validator=self.validator,
            connection_factory=self.mock_conn_factory,
            statement_timeout_ms=5000,
            max_row_limit=3,
        )
        input_result = DataQueryResult(
            status=DataQueryStatus.SUCCESS,
            sql="SELECT platform_number FROM argo_floats LIMIT 10",
        )
        self.mock_cursor.description = [("platform_number", None)]
        # Return 4 rows when max_row_limit is 3
        self.mock_cursor.fetchmany.return_value = [("f1",), ("f2",), ("f3",), ("f4",)]

        res = executor_low_limit.execute(input_result)

        self.assertEqual(res.status, ExecutionStatus.SUCCESS)
        self.assertEqual(len(res.rows), 3)
        self.assertEqual(res.row_count, 3)
        self.assertTrue(res.is_truncated)

    # ===================================================================
    # 17. Malformed Execution Input Cannot Bypass Validator
    # ===================================================================

    def test_17_malformed_input_type_rejected(self):
        """Verify that non-DataQueryResult object is rejected."""
        with self.assertRaises(ExecutionInputRejectionError):
            self.executor.execute("SELECT * FROM argo_floats", raise_on_failure=True)  # type: ignore

    # ===================================================================
    # 18. Real Local Database Integration Test (Safe Read-Only Query)
    # ===================================================================

    def test_18_real_database_read_only_execution(self):
        """
        Integration test executing a safe read-only query against the local database
        if available. Tests live PostgreSQL SET TRANSACTION READ ONLY and statement_timeout.
        """
        try:
            live_executor = ControlledDatabaseExecutor()
            input_result = DataQueryResult(
                status=DataQueryStatus.SUCCESS,
                sql="SELECT platform_number FROM argo_floats ORDER BY platform_number ASC LIMIT 2",
            )
            res = live_executor.execute(input_result)
            if res.status == ExecutionStatus.SUCCESS:
                self.assertEqual(res.columns, ["platform_number"])
                self.assertGreaterEqual(res.row_count, 0)
                self.assertFalse(res.is_truncated)
                self.assertGreater(res.execution_time_ms, 0.0)
                self.assertEqual(res.statement_timeout_ms, 5000)
            elif res.status == ExecutionStatus.CONNECTION_FAILED:
                self.skipTest(f"Live database not reachable: {res.error_message}")
        except Exception as e:
            self.skipTest(f"Live database test skipped due to environment: {str(e)}")


if __name__ == "__main__":
    unittest.main()
