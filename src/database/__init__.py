"""
src/database/__init__.py

FloatChat Controlled Database Execution Package.
Exports ControlledDatabaseExecutor, DatabaseExecutionResult, ExecutionStatus,
get_db_connection, and related database exceptions.
"""

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
from src.database.executor import ControlledDatabaseExecutor, serialize_cell_value
from src.database.models import DatabaseExecutionResult, ExecutionStatus

__all__ = [
    "ControlledDatabaseExecutor",
    "DatabaseExecutionResult",
    "ExecutionStatus",
    "get_db_connection",
    "serialize_cell_value",
    "DatabaseExecutionError",
    "ExecutionInputRejectionError",
    "PreExecutionValidationError",
    "DatabaseConnectionError",
    "DatabaseTimeoutError",
    "QueryExecutionError",
    "SerializationError",
]
