"""
src/agents/data_query/agent.py

FloatChat Data Query Agent Implementation.
Translates structured QueryIntent objects into candidate PostGIS/PostgreSQL queries
and validates them deterministically using DeterministicSQLValidator before returning.
Contains zero database execution or active database connections.
"""

import re
from typing import Optional, Set

import sqlglot
import sqlglot.expressions as exp

from src.agents.data_query.exceptions import (
    AmbiguousIntentError,
    DataQueryError,
    InsufficientIntentError,
    SQLGenerationError,
    SQLValidationError,
    UnsupportedIntentError,
)
from src.agents.data_query.models import (
    DataQueryResult,
    DataQueryStatus,
    SQLCandidate,
)
from src.agents.data_query.prompts import (
    DATA_QUERY_SYSTEM_PROMPT,
    build_data_query_prompt,
    build_sql_retry_prompt,
)
from src.agents.query_understanding.models import (
    AggregationOp,
    IntentCategory,
    IntentType,
    QueryIntent,
)
from src.config import Config, get_config
from src.llm import BaseLLMProvider, LLMProviderError, get_llm_provider
from src.security.sql_validator import (
    DeterministicSQLValidator,
    SQLValidationResult,
    validator as default_validator,
)


def _clean_sql(raw_sql: str) -> str:
    """
    Strips markdown code block fences and trailing semicolons/whitespace from SQL text.
    """
    if not raw_sql:
        return ""
    text = raw_sql.strip()

    # Match markdown code block ```sql ... ``` or ``` ... ```
    sql_block_match = re.search(r"```(?:sql)?\s*([\s\S]*?)\s*```", text, re.IGNORECASE)
    if sql_block_match:
        text = sql_block_match.group(1).strip()

    # Remove trailing semicolon if present
    text = text.rstrip(";").strip()
    return text


MEASUREMENT_COLUMNS: Set[str] = {"pressure_dbar", "temperature_c", "salinity_psu"}


def _refine_candidate_sql(cleaned_sql: str, intent: QueryIntent) -> str:
    """
    Deterministically refines candidate SQL to ensure schema correctness and ID fidelity:
    1. Ensures argo_measurements is joined whenever measurement columns (pressure_dbar,
       temperature_c, salinity_psu) are referenced.
    2. Aligns platform_number filter predicates with the exact requested intent.wmo_ids,
       preventing few-shot example ID leakage.
    Preserves all metadata-only queries and non-platform queries untouched.
    """
    if not cleaned_sql:
        return cleaned_sql

    try:
        parsed = sqlglot.parse_one(cleaned_sql)
    except Exception:
        # If sqlglot cannot parse, return raw cleaned_sql so DeterministicSQLValidator reports standard parse error
        return cleaned_sql

    tables = {t.name.lower(): t for t in parsed.find_all(exp.Table)}
    columns = {c.name.lower() for c in parsed.find_all(exp.Column)}

    # 1. Ensure argo_measurements JOIN if measurement columns are referenced
    needs_measurements = bool(columns.intersection(MEASUREMENT_COLUMNS))
    has_measurements = "argo_measurements" in tables
    has_profiles = "argo_profiles" in tables

    if needs_measurements and not has_measurements and has_profiles:
        p_table = tables["argo_profiles"]
        p_alias = p_table.alias or "argo_profiles"
        join_template = sqlglot.parse_one(
            f"SELECT 1 FROM dummy JOIN argo_measurements m ON {p_alias}.profile_id = m.profile_id"
        )
        parsed.append("joins", join_template.find(exp.Join))

    # 2. Align platform IDs with user intent
    if intent.wmo_ids:
        has_platform_pred = False
        for in_expr in list(parsed.find_all(exp.In)):
            col = in_expr.this
            if isinstance(col, exp.Column) and col.name.lower() == "platform_number":
                has_platform_pred = True
                literals = [str(e.this) for e in in_expr.expressions if isinstance(e, exp.Literal)]
                if literals != intent.wmo_ids:
                    if len(intent.wmo_ids) == 1:
                        in_expr.replace(exp.EQ(this=col.copy(), expression=exp.Literal.string(intent.wmo_ids[0])))
                    else:
                        in_expr.set("expressions", [exp.Literal.string(x) for x in intent.wmo_ids])

        for eq_expr in list(parsed.find_all(exp.EQ)):
            col = None
            lit = None
            if isinstance(eq_expr.this, exp.Column) and eq_expr.this.name.lower() == "platform_number":
                col = eq_expr.this
                lit = eq_expr.expression
            elif isinstance(eq_expr.expression, exp.Column) and eq_expr.expression.name.lower() == "platform_number":
                col = eq_expr.expression
                lit = eq_expr.this

            if col is not None and isinstance(lit, exp.Literal):
                has_platform_pred = True
                if [str(lit.this)] != intent.wmo_ids:
                    if len(intent.wmo_ids) == 1:
                        lit.set("this", intent.wmo_ids[0])
                    else:
                        eq_expr.replace(exp.In(this=col.copy(), expressions=[exp.Literal.string(x) for x in intent.wmo_ids]))

        # If intent has wmo_ids but candidate query had no platform_number predicate at all:
        if not has_platform_pred and has_profiles:
            p_table = tables["argo_profiles"]
            col_ref = exp.Column(
                this=exp.to_identifier("platform_number"),
                table=exp.to_identifier(p_table.alias or "argo_profiles")
            )
            if len(intent.wmo_ids) == 1:
                pred = exp.EQ(this=col_ref, expression=exp.Literal.string(intent.wmo_ids[0]))
            else:
                pred = exp.In(this=col_ref, expressions=[exp.Literal.string(x) for x in intent.wmo_ids])

            where_clause = parsed.find(exp.Where)
            if where_clause:
                where_clause.set("this", exp.And(this=pred, expression=where_clause.this))
            else:
                parsed.set("where", exp.Where(this=pred))

    try:
        return parsed.sql()
    except Exception:
        return cleaned_sql


def _is_intent_sufficient(intent: QueryIntent) -> bool:
    """
    Checks if QueryIntent contains sufficient criteria to generate a meaningful SQL query.
    """
    if intent.physical_variables:
        return True
    if intent.wmo_ids:
        return True
    if intent.spatial_bounds and any(
        v is not None
        for v in (
            intent.spatial_bounds.latitude_min,
            intent.spatial_bounds.latitude_max,
            intent.spatial_bounds.longitude_min,
            intent.spatial_bounds.longitude_max,
        )
    ):
        return True
    if intent.temporal_range and (
        intent.temporal_range.start_date or intent.temporal_range.end_date
    ):
        return True
    if intent.pressure_range and (
        intent.pressure_range.pressure_min is not None
        or intent.pressure_range.pressure_max is not None
        or intent.pressure_range.is_depth_requested
    ):
        return True
    if intent.aggregation_operation is not None:
        return True
    if intent.intent_category == IntentCategory.AGGREGATION:
        return True
    if intent.comparison_target and (
        intent.comparison_target.comparison_targets
        or intent.comparison_target.comparison_aspect
    ):
        return True
    return False


class DataQueryAgent:
    """
    Agent responsible for translating validated QueryIntent into verified, read-only
    PostgreSQL/PostGIS observation queries. Every candidate query must pass through
    the DeterministicSQLValidator before being returned.
    """

    def __init__(
        self,
        llm_provider: Optional[BaseLLMProvider] = None,
        validator: Optional[DeterministicSQLValidator] = None,
        enable_retry: bool = True,
        config: Optional[Config] = None,
    ):
        """
        Initializes the DataQueryAgent.

        Args:
            llm_provider: Optional BaseLLMProvider. If None, resolves configured provider.
            validator: Optional DeterministicSQLValidator. Defaults to singleton instance.
            enable_retry: Whether to attempt a single bounded regeneration if validation fails.
            config: Optional Config instance. Defaults to get_config().
        """
        self.config = config or get_config()
        self.llm_provider = llm_provider if llm_provider is not None else get_llm_provider()
        self.validator = validator if validator is not None else default_validator
        self.enable_retry = enable_retry

    def generate_sql(
        self,
        intent: QueryIntent,
        raise_on_failure: bool = False,
        query: Optional[str] = None,
    ) -> DataQueryResult:
        """
        Processes a QueryIntent and generates a validated SQL query.

        Args:
            intent: Validated QueryIntent from Query Understanding Agent.
            raise_on_failure: If True, raises domain-specific exceptions on failure.

        Returns:
            DataQueryResult with status, validated SQL (if successful), and metadata.

        Raises:
            UnsupportedIntentError: If intent is unsupported and raise_on_failure=True.
            AmbiguousIntentError: If intent requires clarification and raise_on_failure=True.
            InsufficientIntentError: If intent lacks search criteria and raise_on_failure=True.
            SQLGenerationError: If LLM generation fails and raise_on_failure=True.
            SQLValidationError: If candidate SQL fails validation and raise_on_failure=True.
        """
        # 1. Routing: KNOWLEDGE_ONLY does not require SQL
        if intent.intent_type == IntentType.KNOWLEDGE_ONLY:
            res = DataQueryResult(
                status=DataQueryStatus.NO_SQL_REQUIRED,
                sql=None,
                error_message="Query intent is KNOWLEDGE_ONLY; no SQL query is required.",
            )
            return res

        # 2. Routing: Unsupported intent
        if not intent.is_supported:
            error_msg = intent.unsupported_reason or "Query intent is marked unsupported for V1 oceanographic dataset."
            if raise_on_failure:
                raise UnsupportedIntentError(error_msg)
            return DataQueryResult(
                status=DataQueryStatus.UNSUPPORTED_INTENT,
                sql=None,
                error_message=error_msg,
            )

        # 3. Routing: Ambiguous intent requiring user clarification
        if intent.needs_clarification:
            error_msg = intent.clarification_question or "Query intent is ambiguous and requires user clarification."
            if raise_on_failure:
                raise AmbiguousIntentError(error_msg)
            return DataQueryResult(
                status=DataQueryStatus.AMBIGUOUS_INTENT,
                sql=None,
                error_message=error_msg,
            )

        # 4. Routing: Insufficient search criteria
        if not _is_intent_sufficient(intent):
            error_msg = (
                "Query intent contains insufficient criteria (no variables, platform IDs, "
                "spatial, or temporal filters) to generate an observation query."
            )
            if raise_on_failure:
                raise InsufficientIntentError(error_msg)
            return DataQueryResult(
                status=DataQueryStatus.INSUFFICIENT_INTENT,
                sql=None,
                error_message=error_msg,
            )

        # 5. Candidate SQL Generation (Deterministic fast path for unambiguous counts)
        candidate: Optional[SQLCandidate] = None
        gen_error: Optional[str] = None

        is_unfiltered_count = (
            intent.aggregation_operation == AggregationOp.COUNT
            and not intent.physical_variables
            and not intent.wmo_ids
            and not intent.spatial_bounds
            and not intent.temporal_range
            and not intent.pressure_range
        )

        if is_unfiltered_count:
            entity = getattr(intent, "target_entity", None)
            if not entity and query:
                q_lower = query.lower()
                if "profile" in q_lower:
                    entity = "profiles"
                elif any(m in q_lower for m in ("measurement", "reading", "observation", "record")):
                    entity = "measurements"
                elif any(f in q_lower for f in ("float", "platform")):
                    entity = "floats"

            if entity == "profiles":
                candidate = SQLCandidate(
                    sql="SELECT COUNT(*) AS total_profiles FROM argo_profiles;",
                    explanation="Deterministic count of all ARGO ocean profiles."
                )
            elif entity == "measurements":
                candidate = SQLCandidate(
                    sql="SELECT COUNT(*) AS total_measurements FROM argo_measurements;",
                    explanation="Deterministic count of all ARGO ocean measurements."
                )
            elif entity == "floats":
                candidate = SQLCandidate(
                    sql="SELECT COUNT(*) AS total_floats FROM argo_floats;",
                    explanation="Deterministic count of all ARGO float platforms."
                )

        if candidate is None:
            prompt = build_data_query_prompt(intent)
            candidate, gen_error = self._call_llm_for_candidate(prompt)

        if gen_error is not None or candidate is None:
            error_msg = f"LLM candidate SQL generation failed: {gen_error}"
            if raise_on_failure:
                raise SQLGenerationError(error_msg)
            return DataQueryResult(
                status=DataQueryStatus.GENERATION_FAILED,
                sql=None,
                error_message=error_msg,
            )

        raw_sql = candidate.sql
        cleaned_sql = _clean_sql(raw_sql)
        refined_sql = _refine_candidate_sql(cleaned_sql, intent)

        # 6. Deterministic SQL Validation (Attempt 1)
        val_result: SQLValidationResult = self.validator.validate(refined_sql)

        if val_result.valid:
            return DataQueryResult(
                status=DataQueryStatus.SUCCESS,
                sql=val_result.normalized_sql,
                raw_candidate_sql=raw_sql,
                explanation=candidate.explanation,
                validation_warnings=val_result.warnings,
                validation_details=val_result.to_dict(),
                retry_count=0,
            )

        # 7. Bounded Single Regeneration Attempt on Validation Failure
        if self.enable_retry:
            retry_prompt = build_sql_retry_prompt(intent, cleaned_sql, val_result.errors)
            retry_candidate, retry_gen_error = self._call_llm_for_candidate(retry_prompt)

            if retry_candidate is not None:
                retry_raw_sql = retry_candidate.sql
                retry_cleaned_sql = _clean_sql(retry_raw_sql)
                retry_refined_sql = _refine_candidate_sql(retry_cleaned_sql, intent)
                retry_val_result: SQLValidationResult = self.validator.validate(retry_refined_sql)

                if retry_val_result.valid:
                    return DataQueryResult(
                        status=DataQueryStatus.SUCCESS,
                        sql=retry_val_result.normalized_sql,
                        raw_candidate_sql=retry_raw_sql,
                        explanation=retry_candidate.explanation,
                        validation_warnings=retry_val_result.warnings,
                        validation_details=retry_val_result.to_dict(),
                        retry_count=1,
                    )
                else:
                    # Retry also failed validation
                    error_msg = (
                        f"Candidate SQL failed deterministic validation (after retry): "
                        f"{'; '.join(retry_val_result.errors)}"
                    )
                    if raise_on_failure:
                        raise SQLValidationError(
                            error_msg,
                            errors=retry_val_result.errors,
                            candidate_sql=retry_raw_sql,
                        )
                    return DataQueryResult(
                        status=DataQueryStatus.VALIDATION_FAILED,
                        sql=None,
                        raw_candidate_sql=retry_raw_sql,
                        explanation=retry_candidate.explanation,
                        error_message=error_msg,
                        validation_errors=retry_val_result.errors,
                        validation_warnings=retry_val_result.warnings,
                        validation_details=retry_val_result.to_dict(),
                        retry_count=1,
                    )

        # Validation failed and retry was disabled or could not regenerate
        error_msg = f"Candidate SQL failed deterministic validation: {'; '.join(val_result.errors)}"
        if raise_on_failure:
            raise SQLValidationError(
                error_msg,
                errors=val_result.errors,
                candidate_sql=raw_sql,
            )
        return DataQueryResult(
            status=DataQueryStatus.VALIDATION_FAILED,
            sql=None,
            raw_candidate_sql=raw_sql,
            explanation=candidate.explanation,
            error_message=error_msg,
            validation_errors=val_result.errors,
            validation_warnings=val_result.warnings,
            validation_details=val_result.to_dict(),
            retry_count=0,
        )

    def run(self, intent: QueryIntent, raise_on_failure: bool = False) -> DataQueryResult:
        """Alias for generate_sql to support standard pipeline execution interfaces."""
        return self.generate_sql(intent, raise_on_failure=raise_on_failure)

    def _call_llm_for_candidate(
        self,
        prompt: str,
    ) -> tuple[Optional[SQLCandidate], Optional[str]]:
        """
        Executes LLM generation, attempting structured output first,
        and falling back to text generation if structured output is unavailable.
        """
        max_tokens = self.config.ollama_num_predict_data_query
        # Try structured generation first
        try:
            candidate: SQLCandidate = self.llm_provider.generate_structured(
                prompt=prompt,
                response_model=SQLCandidate,
                system_prompt=DATA_QUERY_SYSTEM_PROMPT,
                temperature=0.0,
                max_tokens=max_tokens,
            )
            return candidate, None
        except NotImplementedError:
            pass
        except Exception as e:
            # Check if this was a provider error or structured output parsing error
            # If provider allows plain text generation, fallback
            try:
                gen_result = self.llm_provider.generate(
                    prompt=prompt,
                    system_prompt=DATA_QUERY_SYSTEM_PROMPT,
                    temperature=0.0,
                    max_tokens=max_tokens,
                )
                raw_text = gen_result.text.strip()
                cleaned = _clean_sql(raw_text)
                if cleaned:
                    return SQLCandidate(sql=cleaned, explanation="Extracted from text generation"), None
                return None, f"Text generation returned empty SQL: {raw_text}"
            except Exception as inner_e:
                return None, f"LLM error: {str(e)} (fallback: {str(inner_e)})"

        # Fallback to plain text generation if generate_structured is not implemented
        try:
            gen_result = self.llm_provider.generate(
                prompt=prompt,
                system_prompt=DATA_QUERY_SYSTEM_PROMPT,
                temperature=0.0,
                max_tokens=max_tokens,
            )
            raw_text = gen_result.text.strip()
            cleaned = _clean_sql(raw_text)
            if cleaned:
                return SQLCandidate(sql=cleaned, explanation="Extracted from text generation"), None
            return None, f"Text generation returned empty SQL: {raw_text}"
        except Exception as e:
            return None, str(e)
