"""
src/agents/data_query/agent.py

FloatChat Data Query Agent Implementation.
Translates structured QueryIntent objects into candidate PostGIS/PostgreSQL queries
and validates them deterministically using DeterministicSQLValidator before returning.
Contains zero database execution or active database connections.
"""

import re
from typing import Optional

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
from src.agents.query_understanding.models import IntentType, QueryIntent
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
    ):
        """
        Initializes the DataQueryAgent.

        Args:
            llm_provider: Optional BaseLLMProvider. If None, resolves configured provider.
            validator: Optional DeterministicSQLValidator. Defaults to singleton instance.
            enable_retry: Whether to attempt a single bounded regeneration if validation fails.
        """
        self.llm_provider = llm_provider if llm_provider is not None else get_llm_provider()
        self.validator = validator if validator is not None else default_validator
        self.enable_retry = enable_retry

    def generate_sql(
        self,
        intent: QueryIntent,
        raise_on_failure: bool = False,
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

        # 5. LLM Candidate SQL Generation
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

        # 6. Deterministic SQL Validation (Attempt 1)
        val_result: SQLValidationResult = self.validator.validate(cleaned_sql)

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
                retry_val_result: SQLValidationResult = self.validator.validate(retry_cleaned_sql)

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
        # Try structured generation first
        try:
            candidate: SQLCandidate = self.llm_provider.generate_structured(
                prompt=prompt,
                response_model=SQLCandidate,
                system_prompt=DATA_QUERY_SYSTEM_PROMPT,
                temperature=0.0,
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
            )
            raw_text = gen_result.text.strip()
            cleaned = _clean_sql(raw_text)
            if cleaned:
                return SQLCandidate(sql=cleaned, explanation="Extracted from text generation"), None
            return None, f"Text generation returned empty SQL: {raw_text}"
        except Exception as e:
            return None, str(e)
