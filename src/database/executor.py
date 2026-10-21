"""
src/database/executor.py

FloatChat Controlled Database Execution Layer.
Executes validated, read-only SQL queries from Phase 6A against PostgreSQL.
Enforces:
- Strict acceptance of validated DataQueryResult (never arbitrary SQL)
- Pre-execution AST re-validation using DeterministicSQLValidator
- Execution of only normalized SQL
- Read-only transaction enforcement (SET TRANSACTION READ ONLY)
- Database-side transaction-local statement timeout (SET LOCAL statement_timeout)
- Bounded row limits and truncation tracking
- JSON-safe serialization of oceanographic data types
- Guaranteed connection and transaction rollback cleanup
"""

import re
import time
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Callable, Dict, List, Optional

import psycopg2
from psycopg2 import extensions

from src.agents.data_query.models import DataQueryResult, DataQueryStatus
from src.config import Config, get_config
from src.database.connection import get_db_connection
from src.database.exceptions import (
    DatabaseConnectionError,
    DatabaseExecutionError,
    DatabaseTimeoutError,
    ExecutionInputRejectionError,
    PreExecutionValidationError,
    QueryExecutionError,
    SerializationError,
)
from src.database.models import DatabaseExecutionResult, ExecutionStatus
from src.security.sql_validator import (
    DeterministicSQLValidator,
    SQLValidationResult,
    validator as default_validator,
)

DEFAULT_STATEMENT_TIMEOUT_MS: int = 5000
MAX_ROW_LIMIT: int = 1000


def serialize_cell_value(val: Any) -> Any:
    """
    Serializes a single database cell value into a JSON-compatible Python primitive.
    """
    if val is None:
        return None
    if isinstance(val, (datetime, date)):
        return val.isoformat()
    if isinstance(val, Decimal):
        return float(val)
    if isinstance(val, memoryview):
        return val.tobytes().hex()
    if isinstance(val, (bytes, bytearray)):
        return val.hex()
    if isinstance(val, (int, float, str, bool)):
        return val
    return str(val)


def _sanitize_error(msg: str) -> str:
    """
    Sanitizes database error messages to ensure credentials, paths, and internal details are not exposed.
    """
    if not msg:
        return "Unknown database error"
    sanitized = re.sub(r"password=([^\s]+)", "password=***", msg, flags=re.IGNORECASE)
    sanitized = re.sub(r"://([^:]+):([^@]+)@", r"://\1:***@", sanitized)
    return sanitized.strip()


class ControlledDatabaseExecutor:
    """
    Secure database execution service for FloatChat.
    Accepts validated SQL from Phase 6A and safely executes it against PostgreSQL.
    """

    def __init__(
        self,
        config: Optional[Config] = None,
        validator: Optional[DeterministicSQLValidator] = None,
        connection_factory: Optional[Callable[[Config], extensions.connection]] = None,
        statement_timeout_ms: Optional[int] = None,
        max_row_limit: int = MAX_ROW_LIMIT,
    ):
        """
        Initializes the ControlledDatabaseExecutor.

        Args:
            config: Optional Config instance.
            validator: Optional DeterministicSQLValidator instance.
            connection_factory: Optional factory callable returning an open psycopg2 connection.
            statement_timeout_ms: Statement timeout in milliseconds.
            max_row_limit: Hard maximum row limit policy.
        """
        self.config = config or get_config()
        self.validator = validator or default_validator
        self.connection_factory = connection_factory or get_db_connection
        self.statement_timeout_ms = (
            statement_timeout_ms
            if statement_timeout_ms is not None
            else getattr(self.config, "postgres_statement_timeout_ms", DEFAULT_STATEMENT_TIMEOUT_MS)
        )
        self.max_row_limit = max_row_limit

    def execute(
        self,
        data_query_result: DataQueryResult,
        raise_on_failure: bool = False,
    ) -> DatabaseExecutionResult:
        """
        Validates the input DataQueryResult, re-validates the SQL AST, applies read-only
        session configurations and transaction-local statement timeout, executes the query,
        and returns structured, serialized observation results.

        Args:
            data_query_result: The validated result payload from Phase 6A Data Query Agent.
            raise_on_failure: If True, raises domain-specific exceptions on execution failure.

        Returns:
            DatabaseExecutionResult with execution status, columns, rows, and metadata.

        Raises:
            ExecutionInputRejectionError: If input result does not meet trust requirements.
            PreExecutionValidationError: If SQL fails AST re-validation immediately before execution.
            DatabaseConnectionError: If connection to PostgreSQL fails.
            DatabaseTimeoutError: If execution exceeds statement timeout.
            QueryExecutionError: If query execution fails on database side.
            SerializationError: If row value serialization fails.
        """
        # ===================================================================
        # Step 1: Input Trust Boundary Validation
        # ===================================================================
        if not isinstance(data_query_result, DataQueryResult):
            err_msg = (
                f"Execution rejected: Expected DataQueryResult instance, "
                f"got {type(data_query_result).__name__}."
            )
            if raise_on_failure:
                raise ExecutionInputRejectionError(err_msg)
            return DatabaseExecutionResult(
                status=ExecutionStatus.REJECTED_INPUT,
                error_message=err_msg,
                statement_timeout_ms=self.statement_timeout_ms,
            )

        if data_query_result.status != DataQueryStatus.SUCCESS:
            err_msg = (
                f"Execution rejected: DataQueryResult status is {data_query_result.status.value}, "
                f"expected SUCCESS. Cannot execute unvalidated or non-data queries."
            )
            if raise_on_failure:
                raise ExecutionInputRejectionError(err_msg)
            return DatabaseExecutionResult(
                status=ExecutionStatus.REJECTED_INPUT,
                error_message=err_msg,
                statement_timeout_ms=self.statement_timeout_ms,
            )

        candidate_sql = data_query_result.sql
        if not candidate_sql or not candidate_sql.strip():
            err_msg = "Execution rejected: Validated SQL query string is empty or None."
            if raise_on_failure:
                raise ExecutionInputRejectionError(err_msg)
            return DatabaseExecutionResult(
                status=ExecutionStatus.REJECTED_INPUT,
                error_message=err_msg,
                statement_timeout_ms=self.statement_timeout_ms,
            )

        # ===================================================================
        # Step 2: Mandatory Pre-Execution AST Re-validation
        # ===================================================================
        val_result: SQLValidationResult = self.validator.validate(candidate_sql)
        if not val_result.valid:
            err_msg = f"Pre-execution AST re-validation failed: {'; '.join(val_result.errors)}"
            if raise_on_failure:
                raise PreExecutionValidationError(err_msg, errors=val_result.errors)
            return DatabaseExecutionResult(
                status=ExecutionStatus.VALIDATION_FAILED,
                error_message=err_msg,
                executed_sql=candidate_sql,
                statement_timeout_ms=self.statement_timeout_ms,
            )

        # Strictly execute only the normalized SQL produced by the validator
        normalized_sql = val_result.normalized_sql
        if not normalized_sql:
            normalized_sql = candidate_sql

        # ===================================================================
        # Step 3: Database Connection Acquisition
        # ===================================================================
        try:
            conn = self.connection_factory(self.config)
        except Exception as conn_err:
            err_msg = _sanitize_error(str(conn_err))
            if raise_on_failure:
                raise DatabaseConnectionError(err_msg) from None
            return DatabaseExecutionResult(
                status=ExecutionStatus.CONNECTION_FAILED,
                error_message=err_msg,
                executed_sql=normalized_sql,
                statement_timeout_ms=self.statement_timeout_ms,
            )

        # ===================================================================
        # Step 4: Transaction Configuration & Controlled Execution
        # ===================================================================
        cur = None
        try:
            # Enforce non-autocommit to control transaction scope
            conn.autocommit = False

            # Set connection session read-only if supported by driver
            try:
                conn.set_session(readonly=True)
            except Exception:
                pass

            cur = conn.cursor()

            # Apply read-only transaction mode and transaction-local statement timeout
            cur.execute("SET TRANSACTION READ ONLY;")
            cur.execute(f"SET LOCAL statement_timeout = '{self.statement_timeout_ms}ms';")

            # Execute normalized query and record execution duration
            start_time = time.perf_counter()
            cur.execute(normalized_sql)
            execution_time_ms = round((time.perf_counter() - start_time) * 1000.0, 2)

            # Extract column names from cursor description
            columns: List[str] = [desc[0] for desc in cur.description] if cur.description else []

            # Fetch rows with limit guard
            raw_rows = cur.fetchmany(self.max_row_limit + 1)
            is_truncated = False
            if len(raw_rows) > self.max_row_limit:
                raw_rows = raw_rows[:self.max_row_limit]
                is_truncated = True

            # Serialize rows
            serialized_rows: List[Dict[str, Any]] = []
            try:
                for row in raw_rows:
                    row_dict = {col: serialize_cell_value(val) for col, val in zip(columns, row)}
                    serialized_rows.append(row_dict)
            except Exception as ser_err:
                conn.rollback()
                err_msg = f"Failed to serialize database row data: {_sanitize_error(str(ser_err))}"
                if raise_on_failure:
                    raise SerializationError(err_msg) from None
                return DatabaseExecutionResult(
                    status=ExecutionStatus.SERIALIZATION_FAILED,
                    error_message=err_msg,
                    executed_sql=normalized_sql,
                    execution_time_ms=execution_time_ms,
                    statement_timeout_ms=self.statement_timeout_ms,
                )

            # Roll back transaction cleanly (read-only query releases locks immediately)
            conn.rollback()

            return DatabaseExecutionResult(
                status=ExecutionStatus.SUCCESS,
                columns=columns,
                rows=serialized_rows,
                row_count=len(serialized_rows),
                execution_time_ms=execution_time_ms,
                is_truncated=is_truncated,
                executed_sql=normalized_sql,
                statement_timeout_ms=self.statement_timeout_ms,
            )

        except Exception as e:
            # Ensure transaction is rolled back on any exception
            try:
                conn.rollback()
            except Exception:
                pass

            err_str = str(e).lower()
            pgcode = getattr(e, "pgcode", "")

            # Check for statement timeout (PostgreSQL error code 57014 / query_canceled)
            is_timeout = (
                pgcode == "57014"
                or isinstance(e, getattr(psycopg2.errors, "QueryCanceled", type(None)))
                or "statement timeout" in err_str
                or "canceling statement due to statement timeout" in err_str
            )

            if is_timeout:
                err_msg = f"Database query execution exceeded statement timeout of {self.statement_timeout_ms}ms."
                if raise_on_failure:
                    raise DatabaseTimeoutError(err_msg, timeout_ms=self.statement_timeout_ms) from None
                return DatabaseExecutionResult(
                    status=ExecutionStatus.TIMEOUT,
                    error_message=err_msg,
                    executed_sql=normalized_sql,
                    statement_timeout_ms=self.statement_timeout_ms,
                )

            # General database execution failure
            err_msg = f"Database query execution failed: {_sanitize_error(str(e))}"
            if raise_on_failure:
                raise QueryExecutionError(err_msg) from None
            return DatabaseExecutionResult(
                status=ExecutionStatus.EXECUTION_FAILED,
                error_message=err_msg,
                executed_sql=normalized_sql,
                statement_timeout_ms=self.statement_timeout_ms,
            )

        finally:
            # Guarantee cursor and connection are closed and returned cleanly
            if cur is not None:
                try:
                    cur.close()
                except Exception:
                    pass
            try:
                conn.close()
            except Exception:
                pass
