"""
src/security/sql_validator.py

FloatChat Phase 3.1 — Deterministic SQL Validator Core.

A non-LLM security gate that parses SQL into an Abstract Syntax Tree (AST) using sqlglot,
enforcing:
- Strict single-statement SELECT-only execution
- Whitelisted tables (argo_floats, argo_profiles, argo_measurements)
- Whitelisted columns matching physical Phase 2 schema
- Allowed PostGIS and standard analytical functions
- Mandatory result LIMIT injection / capping (max 1000)
- Rejection of dangerous constructs, system catalogs, and multi-statement injection attempts

This module is 100% deterministic, contains zero LLM calls, and requires no active database connection.
"""

import enum
from dataclasses import dataclass, field
from typing import List, Set, Dict, Optional, Any

import sqlglot
import sqlglot.expressions as exp


class ValidationErrorCode(str, enum.Enum):
    EMPTY_SQL = "EMPTY_SQL"
    PARSE_ERROR = "PARSE_ERROR"
    MULTIPLE_STATEMENTS = "MULTIPLE_STATEMENTS"
    NON_SELECT_STATEMENT = "NON_SELECT_STATEMENT"
    UNAUTHORIZED_TABLE = "UNAUTHORIZED_TABLE"
    UNAUTHORIZED_COLUMN = "UNAUTHORIZED_COLUMN"
    MISSING_LIMIT = "MISSING_LIMIT"
    LIMIT_EXCEEDED = "LIMIT_EXCEEDED"
    UNSAFE_FUNCTION = "UNSAFE_FUNCTION"
    UNSAFE_CONSTRUCT = "UNSAFE_CONSTRUCT"
    INVALID_SCHEMA_REFERENCE = "INVALID_SCHEMA_REFERENCE"


@dataclass
class SQLValidationResult:
    valid: bool
    original_sql: str
    normalized_sql: Optional[str] = None
    error_code: Optional[ValidationErrorCode] = None
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "valid": self.valid,
            "original_sql": self.original_sql,
            "normalized_sql": self.normalized_sql,
            "error_code": self.error_code.value if self.error_code else None,
            "errors": self.errors,
            "warnings": self.warnings,
        }


# ===================================================================
# Policy & Schema Configuration Baseline (Phase 2 Alignment)
# ===================================================================

ALLOWED_SCHEMAS: Set[str] = {"public", ""}

ALLOWED_TABLES: Set[str] = {
    "argo_floats",
    "argo_profiles",
    "argo_measurements",
}

ALLOWED_COLUMNS_BY_TABLE: Dict[str, Set[str]] = {
    "argo_floats": {
        "platform_number",
        "created_at",
    },
    "argo_profiles": {
        "profile_id",
        "platform_number",
        "profile_time",
        "latitude",
        "longitude",
        "location",
    },
    "argo_measurements": {
        "measurement_id",
        "profile_id",
        "pressure_dbar",
        "temperature_c",
        "salinity_psu",
    },
}

ALL_ALLOWED_COLUMNS: Set[str] = set().union(*ALLOWED_COLUMNS_BY_TABLE.values())

# Standard aggregate / scalar functions allowed in observation analytics
ALLOWED_STANDARD_FUNCTIONS: Set[str] = {
    "count", "avg", "min", "max", "sum",
    "coalesce", "round", "date_trunc", "extract", "cast",
    "to_char", "now", "current_timestamp", "abs", "floor", "ceil"
}

# PostGIS spatial functions allowed in read-only observation queries
ALLOWED_POSTGIS_FUNCTIONS: Set[str] = {
    "st_dwithin", "st_within", "st_intersects", "st_distance",
    "st_makepoint", "st_point", "st_setsrid", "st_makeenvelope",
    "st_area", "st_length", "st_asgeojson", "st_astext",
    "st_contains", "st_centroid", "st_isvalid"
}

ALLOWED_FUNCTIONS: Set[str] = ALLOWED_STANDARD_FUNCTIONS.union(ALLOWED_POSTGIS_FUNCTIONS)

# Dangerous system functions explicitly forbidden
DISALLOWED_SYSTEM_FUNCTIONS: Set[str] = {
    "pg_read_file", "pg_ls_dir", "pg_stat_file", "eval",
    "query_to_xml", "pg_sleep", "version", "current_setting",
    "pg_cancel_backend", "pg_terminate_backend"
}

DEFAULT_MAX_LIMIT: int = 1000
DEFAULT_AUTO_LIMIT: int = 500
STATEMENT_TIMEOUT_MS: int = 5000


class DeterministicSQLValidator:
    """
    Core AST-based SQL Security Validator.
    """

    def __init__(
        self,
        allowed_tables: Optional[Set[str]] = None,
        allowed_columns: Optional[Dict[str, Set[str]]] = None,
        allowed_functions: Optional[Set[str]] = None,
        max_limit: int = DEFAULT_MAX_LIMIT,
        auto_limit: int = DEFAULT_AUTO_LIMIT,
        statement_timeout_ms: int = STATEMENT_TIMEOUT_MS,
    ):
        self.allowed_tables = {t.lower() for t in (allowed_tables or ALLOWED_TABLES)}
        self.allowed_columns = {
            t.lower(): {c.lower() for c in cols}
            for t, cols in (allowed_columns or ALLOWED_COLUMNS_BY_TABLE).items()
        }
        self.all_allowed_columns = set().union(*self.allowed_columns.values())
        self.allowed_functions = {f.lower() for f in (allowed_functions or ALLOWED_FUNCTIONS)}
        self.max_limit = max_limit
        self.auto_limit = auto_limit
        self.statement_timeout_ms = statement_timeout_ms

    def validate(self, sql: str) -> SQLValidationResult:
        """
        Validates an input SQL query string against the deterministic security policy.
        """
        if not sql or not sql.strip():
            return SQLValidationResult(
                valid=False,
                original_sql=sql or "",
                error_code=ValidationErrorCode.EMPTY_SQL,
                errors=["SQL query string is empty or whitespace-only."],
            )

        sql_trimmed = sql.strip().rstrip(";")

        # Step 1: Parse statements using sqlglot
        try:
            parsed_statements = sqlglot.parse(sql_trimmed, read="postgres")
        except Exception as e:
            return SQLValidationResult(
                valid=False,
                original_sql=sql,
                error_code=ValidationErrorCode.PARSE_ERROR,
                errors=[f"Failed to parse SQL into AST: {str(e)}"],
            )

        # Step 2: Enforce Single Statement Rule
        if not parsed_statements or len(parsed_statements) == 0:
            return SQLValidationResult(
                valid=False,
                original_sql=sql,
                error_code=ValidationErrorCode.EMPTY_SQL,
                errors=["No valid SQL statements found."],
            )

        if len(parsed_statements) > 1:
            return SQLValidationResult(
                valid=False,
                original_sql=sql,
                error_code=ValidationErrorCode.MULTIPLE_STATEMENTS,
                errors=[f"Multiple SQL statements detected ({len(parsed_statements)}). Exactly 1 statement is permitted."],
            )

        ast = parsed_statements[0]
        if ast is None:
            return SQLValidationResult(
                valid=False,
                original_sql=sql,
                error_code=ValidationErrorCode.PARSE_ERROR,
                errors=["Parsed AST node is None."],
            )

        # Step 3: Enforce Root Node must be SELECT
        if not isinstance(ast, exp.Select):
            return SQLValidationResult(
                valid=False,
                original_sql=sql,
                error_code=ValidationErrorCode.NON_SELECT_STATEMENT,
                errors=[f"Root statement type '{ast.key}' is forbidden. Only SELECT queries are allowed."],
            )

        # Step 4: Check for Dangerous AST Constructs
        dangerous_error = self._check_dangerous_constructs(ast)
        if dangerous_error:
            return SQLValidationResult(
                valid=False,
                original_sql=sql,
                error_code=ValidationErrorCode.UNSAFE_CONSTRUCT,
                errors=[dangerous_error],
            )

        # Step 5: Table & Schema Allowlist Validation
        table_errors = self._validate_tables(ast)
        if table_errors:
            return SQLValidationResult(
                valid=False,
                original_sql=sql,
                error_code=ValidationErrorCode.UNAUTHORIZED_TABLE,
                errors=table_errors,
            )

        # Step 6: Column Allowlist Validation
        column_errors = self._validate_columns(ast)
        if column_errors:
            return SQLValidationResult(
                valid=False,
                original_sql=sql,
                error_code=ValidationErrorCode.UNAUTHORIZED_COLUMN,
                errors=column_errors,
            )

        # Step 7: Function Allowlist Validation
        function_errors = self._validate_functions(ast)
        if function_errors:
            return SQLValidationResult(
                valid=False,
                original_sql=sql,
                error_code=ValidationErrorCode.UNSAFE_FUNCTION,
                errors=function_errors,
            )

        # Step 8: Mandatory LIMIT Policy Enforcement (Transformation)
        ast_transformed, limit_warning = self._enforce_limit_policy(ast)

        normalized_sql = ast_transformed.sql(dialect="postgres")
        warnings = [limit_warning] if limit_warning else []

        return SQLValidationResult(
            valid=True,
            original_sql=sql,
            normalized_sql=normalized_sql,
            warnings=warnings,
        )

    def _check_dangerous_constructs(self, ast: exp.Expression) -> Optional[str]:
        """
        Inspects AST for dangerous constructs (SELECT INTO, COPY, EXECUTE, system catalog queries).
        """
        # Reject SELECT ... INTO
        if ast.find(exp.Into):
            return "Forbidden construct: SELECT INTO statement is not permitted."

        # Check for system catalog references in strings or expressions
        for table in ast.find_all(exp.Table):
            t_name = table.name.lower()
            if t_name.startswith("pg_") or t_name in ("information_schema", "pg_catalog"):
                return f"Forbidden access to system catalog or schema table '{t_name}'."

        return None

    def _validate_tables(self, ast: exp.Expression) -> List[str]:
        """
        Validates that every referenced table in AST (including CTEs, JOINs, subqueries) is in the table allowlist.
        """
        errors = []
        
        # Collect CTE names defined in WITH clause so they are treated as valid aliases
        cte_names: Set[str] = set()
        for cte in ast.find_all(exp.CTE):
            if cte.alias:
                cte_names.add(cte.alias.lower())

        for table in ast.find_all(exp.Table):
            t_name = table.name.lower()
            
            # Skip checking CTE aliases defined within the query
            if t_name in cte_names:
                continue

            # Check schema qualification
            if table.db:
                schema_name = table.db.lower()
                if schema_name not in ALLOWED_SCHEMAS:
                    errors.append(f"Forbidden schema qualification '{schema_name}' on table '{t_name}'.")

            # Check table allowlist
            if t_name not in self.allowed_tables:
                errors.append(f"Unauthorized table '{t_name}'. Allowed tables: {sorted(list(self.allowed_tables))}")

        return errors

    def _validate_columns(self, ast: exp.Expression) -> List[str]:
        """
        Validates that explicitly referenced column names exist in the allowed schema.
        """
        errors = []

        # Find all explicit column references
        for col in ast.find_all(exp.Column):
            col_name = col.name.lower()
            
            # Skip special pseudo-columns or table aliases where name is wildcard '*'
            if col_name == "*":
                continue

            # If table/alias is qualified on column (e.g. p.latitude)
            table_ref = col.table.lower() if col.table else None

            if table_ref and table_ref in self.allowed_tables:
                # Validate against specific table's column whitelist
                allowed_for_t = self.allowed_columns[table_ref]
                if col_name not in allowed_for_t:
                    errors.append(
                        f"Unauthorized column '{col_name}' for table '{table_ref}'. "
                        f"Allowed columns: {sorted(list(allowed_for_t))}"
                    )
            else:
                # Validate against global allowed column whitelist
                if col_name not in self.all_allowed_columns:
                    errors.append(
                        f"Unauthorized column '{col_name}'. Column does not exist in allowed FloatChat schema."
                    )

        return errors

    def _validate_functions(self, ast: exp.Expression) -> List[str]:
        """
        Validates function calls against allowed standard & PostGIS function whitelist.
        """
        errors = []

        for func in ast.find_all(exp.Func, exp.Anonymous):
            # Extract function name cleanly from SQL syntax
            raw_sql = func.sql()
            func_name = raw_sql.split("(")[0].strip().lower()

            if func_name in DISALLOWED_SYSTEM_FUNCTIONS:
                errors.append(f"Forbidden system function '{func_name}'.")
                continue

            if func_name not in self.allowed_functions and func_name not in ("select", "cast", "alias", "case"):
                errors.append(
                    f"Unauthorized function '{func_name}'. Function is not in approved PostGIS or analytical whitelist."
                )

        return errors

    def _enforce_limit_policy(self, ast: exp.Select) -> tuple[exp.Select, Optional[str]]:
        """
        Applies mandatory LIMIT policy via AST transformation:
        - Injects LIMIT auto_limit if query has no LIMIT clause.
        - Caps existing LIMIT at max_limit if it exceeds max_limit.
        """
        ast_copy = ast.copy()
        limit_node = ast_copy.args.get("limit")

        if limit_node is None:
            ast_copy = ast_copy.limit(self.auto_limit)
            warning = f"No LIMIT clause specified. Injected default safety LIMIT {self.auto_limit}."
            return ast_copy, warning

        # Inspect existing LIMIT value
        try:
            limit_val_expr = limit_node.expression
            if isinstance(limit_val_expr, exp.Literal):
                val = int(limit_val_expr.this)
                if val > self.max_limit:
                    ast_copy = ast_copy.limit(self.max_limit)
                    warning = f"Requested LIMIT {val} exceeded maximum threshold ({self.max_limit}). Capped LIMIT to {self.max_limit}."
                    return ast_copy, warning
        except Exception:
            pass

        return ast_copy, None


# Singleton instance for quick module-level imports
validator = DeterministicSQLValidator()

def validate_sql(sql: str) -> SQLValidationResult:
    """
    Convenience function exposing the primary validator interface.
    """
    return validator.validate(sql)
