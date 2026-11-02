"""
src/agents/response/agent.py

FloatChat Scientific Knowledge & Response Agent.
Combines semantic retrieval over authoritative scientific literature with structured
observational ARGO database results to synthesize grounded, evidence-backed responses.

Responsibilities:
1. Coordinate semantic document retrieval via ScientificDocumentRetriever.
2. Produce deterministic data summaries over empirical database results.
3. Validate and build visualization specifications strictly grounded in actual columns.
4. Synthesize natural language narratives with explicit document citations [Doc, Section].
5. Strictly separate measured observation data from scientific program theory.
6. Gracefully handle empty retrieval, empty SQL rows, offline models, and provider errors.
7. Maintain strict safety: ZERO SQL execution, ZERO database modifications.
"""

import json
import logging
import math
import re
import statistics
from typing import Any, Dict, List, Optional, Set, Tuple, TYPE_CHECKING, Union
from pydantic import BaseModel, Field, field_validator

from src.agents.query_understanding.models import (
    AggregationOp,
    IntentCategory,
    IntentType,
    PhysicalVariable,
    QueryIntent,
)
from src.agents.response.exceptions import (
    ResponseAgentException,
    ResponseGenerationError,
    ResponseValidationError,
    VisualizationGroundingError,
)
from src.agents.response.models import (
    ChartType,
    Citation,
    DataSummary,
    ResponseStatus,
    ScientificResponse,
    VisualizationSpec,
)
from src.agents.response.prompts import (
    SCIENTIFIC_RESPONSE_SYSTEM_PROMPT,
    build_response_user_prompt,
)
from src.config import Config, get_config
from src.database.models import DatabaseExecutionResult
from src.llm import BaseLLMProvider, LLMConnectionError, LLMProviderError, LLMTimeoutError, get_llm_provider
from src.rag.models import RetrievalResult, RetrievedChunk

if TYPE_CHECKING:
    from src.rag.retriever import ScientificDocumentRetriever

logger = logging.getLogger("floatchat.agents.response")


class _LLMResponsePayload(BaseModel):
    """Internal Pydantic schema for structured LLM generation."""
    answer: str = Field(description="Comprehensive Markdown answer narrative grounded in evidence.")
    citations: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="List of document citations directly referenced in the answer."
    )

    @field_validator("citations", mode="before")
    @classmethod
    def coerce_citations(cls, v: Any) -> Any:
        if isinstance(v, list):
            res = []
            for item in v:
                if hasattr(item, "model_dump"):
                    res.append(item.model_dump())
                elif isinstance(item, dict):
                    res.append(item)
            return res
        return v


def _is_valid_numeric_measurement(val: Any) -> bool:
    """
    Validates that a value is a finite numeric measurement (int or float).
    Explicitly excludes None, bool, NaN, and positive/negative infinity.
    """
    if val is None or isinstance(val, bool):
        return False
    if isinstance(val, (int, float)):
        return not (math.isnan(val) or math.isinf(val))
    return False


def _get_column_unit(col_name: str) -> Optional[str]:
    """
    Maps column name to standard oceanographic unit if applicable:
    temperature_c -> °C
    salinity_psu -> PSU
    pressure_dbar -> dbar
    """
    c_lower = col_name.lower()
    if any(k in c_lower for k in ("temperature_c", "temperature", "temp")):
        if not any(k in c_lower for k in ("count", "total", "var")):
            return "°C"
    if any(k in c_lower for k in ("salinity_psu", "salinity", "psal")):
        if not any(k in c_lower for k in ("count", "total", "var")):
            return "PSU"
    if any(k in c_lower for k in ("pressure_dbar", "pressure", "pres")):
        if not any(k in c_lower for k in ("count", "total", "var")):
            return "dbar"
    return None


_INVALID_METRIC_SUBSTRINGS: Tuple[str, ...] = ("count", "total", "qc", "flag", "error", "warning")

_TEMP_RE = re.compile(
    r"^(?:(?:avg|mean|median|min|max)_)?(temp|temperature|temperature_c)(?:_(?:avg|mean|median|min|max))?$",
    re.IGNORECASE,
)
_PSAL_RE = re.compile(
    r"^(?:(?:avg|mean|median|min|max)_)?(psal|salinity|salinity_psu)(?:_(?:avg|mean|median|min|max))?$",
    re.IGNORECASE,
)
_PRES_RE = re.compile(
    r"^(?:(?:avg|mean|median|min|max)_)?(pres|pressure|pressure_dbar)(?:_(?:avg|mean|median|min|max))?$",
    re.IGNORECASE,
)
_LAT_RE = re.compile(
    r"^(?:(?:avg|mean)_)?(lat|latitude)(?:_deg)?$",
    re.IGNORECASE,
)
_LON_RE = re.compile(
    r"^(?:(?:avg|mean)_)?(lon|long|longitude)(?:_deg)?$",
    re.IGNORECASE,
)


def _find_physical_column(
    cols_lower_map: Dict[str, str],
    regex: re.Pattern,
    primary_keys: Tuple[str, ...],
) -> Optional[str]:
    """Finds physical measurement column using exact primary keys or regex aggregate aliases."""
    for pk in primary_keys:
        if pk in cols_lower_map:
            return cols_lower_map[pk]
    for c_lower, orig_name in cols_lower_map.items():
        if any(bad in c_lower for bad in _INVALID_METRIC_SUBSTRINGS):
            continue
        if regex.match(c_lower):
            return orig_name
    return None


def _find_coordinate_column(
    cols_lower_map: Dict[str, str],
    regex: re.Pattern,
    primary_keys: Tuple[str, ...],
) -> Optional[str]:
    """Finds geographic coordinate column using exact primary keys or regex aggregate aliases."""
    for pk in primary_keys:
        if pk in cols_lower_map:
            return cols_lower_map[pk]
    for c_lower, orig_name in cols_lower_map.items():
        if any(bad in c_lower for bad in _INVALID_METRIC_SUBSTRINGS):
            continue
        if regex.match(c_lower):
            return orig_name
    return None


class ScientificResponseAgent:
    """
    Primary AI Agent responsible for synthesizing grounded scientific answers,
    contextualizing observational ARGO data, providing citations, and generating
    validated visualization specifications.
    """

    def __init__(
        self,
        llm_provider: Optional[BaseLLMProvider] = None,
        retriever: Optional["ScientificDocumentRetriever"] = None,
        config: Optional[Config] = None,
    ):
        """
        Initializes the ScientificResponseAgent.

        Args:
            llm_provider: Optional BaseLLMProvider implementation (defaults to configured provider).
            retriever: Optional ScientificDocumentRetriever (defaults to new instance with config).
            config: Optional Config instance (defaults to get_config()).
        """
        self.config = config or get_config()
        self.llm_provider = llm_provider if llm_provider is not None else get_llm_provider()
        if retriever is not None:
            self.retriever = retriever
        else:
            from src.rag.retriever import ScientificDocumentRetriever
            self.retriever = ScientificDocumentRetriever(config=self.config)

    def respond(
        self,
        query: str,
        intent: Optional[QueryIntent] = None,
        db_result: Optional[DatabaseExecutionResult] = None,
        top_k: Optional[int] = None,
        similarity_threshold: Optional[float] = None,
        pre_retrieved_chunks: Optional[List[RetrievedChunk]] = None,
        pre_retrieval_warnings: Optional[List[str]] = None,
    ) -> ScientificResponse:
        """
        Main entry point for generating an evidence-grounded scientific response.

        Args:
            query: User's natural language question.
            intent: Optional validated QueryIntent from Query Understanding Agent.
            db_result: Optional DatabaseExecutionResult from Controlled Database Execution Layer.
            top_k: Optional override for retrieval chunk count.
            similarity_threshold: Optional override for retrieval similarity threshold.
            pre_retrieved_chunks: Optional already-retrieved chunks from workflow retrieval branch.
            pre_retrieval_warnings: Optional warnings from workflow retrieval branch.

        Returns:
            ScientificResponse containing narrative, citations, data summary, and chart spec.
        """
        if not query or not query.strip():
            return ScientificResponse(
                answer="No query provided. Please ask an oceanographic question or request ARGO observations.",
                status=ResponseStatus.ERROR,
                warnings=["Query string was empty or whitespace."],
            )

        cleaned_query = query.strip()
        warnings: List[str] = []
        if pre_retrieval_warnings:
            warnings.extend(pre_retrieval_warnings)

        # 1. Determine whether scientific document retrieval is needed
        needs_retrieval = self._should_retrieve_docs(cleaned_query, intent)
        retrieved_chunks: List[RetrievedChunk] = []

        if pre_retrieved_chunks is not None:
            # Graph supplied pre-retrieved chunks: use directly without calling retriever again
            retrieved_chunks = list(pre_retrieved_chunks)
            if needs_retrieval and not retrieved_chunks:
                msg = "No scientific documents met the similarity threshold."
                if msg not in warnings:
                    warnings.append(msg)
        elif needs_retrieval:
            try:
                retrieval_res: RetrievalResult = self.retriever.retrieve(
                    query=cleaned_query,
                    top_k=top_k,
                    similarity_threshold=similarity_threshold,
                    raise_on_error=False,
                )
                if retrieval_res.has_results:
                    retrieved_chunks = retrieval_res.chunks
                else:
                    msg = "No scientific documents met the similarity threshold."
                    warnings.append(msg)
                    if retrieval_res.warning:
                        warnings.append(retrieval_res.warning)
            except Exception as e:
                logger.warning(f"Scientific document retrieval error: {e}")
                warnings.append(f"Document retrieval degraded: {str(e)}")

        # 2. Extract deterministic DataSummary if database results are present
        data_summary: Optional[DataSummary] = None
        if db_result is not None:
            data_summary = self._build_data_summary(db_result, intent=intent)
            if db_result.is_success and db_result.row_count == 0:
                warnings.append("Database query returned 0 rows matching criteria.")
            elif not db_result.is_success:
                warnings.append(f"Database query execution issue: {db_result.error_message}")

        # 3. Generate and validate visualization specification (strictly grounded in columns)
        candidate_viz: Optional[VisualizationSpec] = None
        if db_result is not None and db_result.is_success and db_result.row_count >= 1:
            candidate_viz = self._build_visualization_spec(db_result, intent=intent, query=cleaned_query)
            if candidate_viz is None and db_result.row_count == 1 and data_summary is not None:
                data_summary.highlights.append(
                    "Visualization omitted: single-record scalar aggregate is represented in narrative summary."
                )

        # 4. Check for pure empty state scenarios
        is_knowledge_only = intent is not None and intent.intent_type == IntentType.KNOWLEDGE_ONLY
        is_data_only = intent is not None and intent.intent_type == IntentType.DATA_ONLY

        if is_knowledge_only and not retrieved_chunks:
            return ScientificResponse(
                answer="Information not found in authoritative ARGO documentation for the requested scientific topic.",
                citations=[],
                data_summary=data_summary,
                visualization_spec=None,
                status=ResponseStatus.NO_KNOWLEDGE_MATCH,
                warnings=warnings,
            )

        if is_data_only and db_result is not None and db_result.is_success and db_result.row_count == 0:
            msg = "No observation records matched the specified spatial-temporal filters in the database."
            if intent and intent.temporal_range and (
                (intent.temporal_range.start_date and intent.temporal_range.start_date > "2025-04-01")
                or (intent.temporal_range.end_date and intent.temporal_range.end_date > "2025-04-01")
            ):
                msg += " Note: The currently loaded FloatChat ARGO dataset contains observations only through April 1, 2025. This empty result reflects local dataset coverage boundaries rather than the absence of global ARGO float operations."
            return ScientificResponse(
                answer=msg,
                citations=[],
                data_summary=data_summary,
                visualization_spec=None,
                status=ResponseStatus.NO_DATA_MATCH,
                warnings=warnings,
            )

        # Deterministic fast path for simple aggregate queries (e.g. total float / profile / measurement inventory counts)
        has_filters = bool(
            intent
            and (
                intent.physical_variables
                or intent.wmo_ids
                or intent.spatial_bounds
                or intent.temporal_range
                or intent.pressure_range
            )
        )

        if (
            is_data_only
            and db_result is not None
            and db_result.is_success
            and db_result.row_count == 1
            and db_result.rows
            and intent is not None
            and intent.aggregation_operation == AggregationOp.COUNT
            and not has_filters
        ):
            row = db_result.rows[0]
            count_val = None
            detected_entity = None

            # 1. Check known column names first
            if "total_floats" in row:
                count_val = row["total_floats"]
                detected_entity = "floats"
            elif "total_profiles" in row:
                count_val = row["total_profiles"]
                detected_entity = "profiles"
            elif "total_measurements" in row:
                count_val = row["total_measurements"]
                detected_entity = "measurements"
            else:
                # Dynamic extraction from single-row aggregate result
                for k, v in row.items():
                    if isinstance(v, (int, float)) or (isinstance(v, str) and v.isdigit()):
                        count_val = int(v)
                        k_lower = k.lower()
                        if "float" in k_lower:
                            detected_entity = "floats"
                        elif "profile" in k_lower:
                            detected_entity = "profiles"
                        elif "measurement" in k_lower:
                            detected_entity = "measurements"
                        break

            # 2. Correlate with intent target_entity or user query
            target = getattr(intent, "target_entity", None) or detected_entity
            if not target:
                q_lower = cleaned_query.lower()
                if "profile" in q_lower:
                    target = "profiles"
                elif any(m in q_lower for m in ("measurement", "reading", "observation", "record")):
                    target = "measurements"
                elif any(f in q_lower for f in ("float", "platform")):
                    target = "floats"

            # 3. Only produce deterministic aggregate response if count_val is verified and non-malformed
            if count_val is not None:
                try:
                    num_val = int(count_val)
                    if num_val >= 0:
                        formatted_val = f"{num_val:,}"

                        if target == "profiles":
                            entity_str = "ocean profiles"
                        elif target == "measurements":
                            entity_str = "measurements"
                        elif target == "floats":
                            entity_str = "floats"
                        else:
                            entity_str = "records"

                        return ScientificResponse(
                            answer=f"The ARGO database currently stores {formatted_val} {entity_str}.",
                            citations=[],
                            data_summary=data_summary,
                            visualization_spec=candidate_viz,
                            status=ResponseStatus.SUCCESS,
                            warnings=warnings,
                        )
                except (ValueError, TypeError):
                    # Malformed count: do not fabricate, proceed to LLM / fallback
                    pass

        # 5. Build grounded prompt for LLM
        user_prompt = build_response_user_prompt(
            query=cleaned_query,
            intent=intent,
            retrieved_chunks=retrieved_chunks,
            db_result=db_result,
            data_summary=data_summary,
            candidate_viz=candidate_viz,
        )

        # 6. Invoke LLM with error isolation and fallback
        llm_payload, raw_text, gen_error = self._invoke_llm(user_prompt)

        if gen_error or llm_payload is None:
            # Graceful fallback: synthesize grounded deterministic answer without crashing
            logger.warning(f"Falling back to deterministic grounded synthesis due to LLM error: {gen_error}")
            warnings.append(f"Language model generation unavailable: {gen_error or 'No response'}. Using deterministic fallback.")
            fallback_answer, fallback_citations = self._build_deterministic_fallback(
                query=cleaned_query,
                retrieved_chunks=retrieved_chunks,
                db_result=db_result,
                data_summary=data_summary,
            )
            return ScientificResponse(
                answer=fallback_answer,
                citations=fallback_citations,
                data_summary=data_summary,
                visualization_spec=candidate_viz,
                status=ResponseStatus.DEGRADED,
                warnings=warnings,
                raw_llm_response=raw_text,
            )

        # 7. Ground and validate citations against actually retrieved chunks
        grounded_citations = self._ground_citations(llm_payload.citations, retrieved_chunks)

        # 8. Determine overall status
        status = ResponseStatus.SUCCESS
        if is_knowledge_only and not retrieved_chunks:
            status = ResponseStatus.NO_KNOWLEDGE_MATCH
        elif is_data_only and db_result is not None and db_result.row_count == 0:
            status = ResponseStatus.NO_DATA_MATCH
        elif warnings:
            status = ResponseStatus.DEGRADED

        return ScientificResponse(
            answer=llm_payload.answer,
            citations=grounded_citations,
            data_summary=data_summary,
            visualization_spec=candidate_viz,
            status=status,
            warnings=warnings,
            raw_llm_response=raw_text,
        )

    def _should_retrieve_docs(self, query: str, intent: Optional[QueryIntent]) -> bool:
        """
        Determines whether semantic document retrieval should be invoked.
        Uses QueryIntent.intent_type as the primary retrieval decision:
        - KNOWLEDGE_ONLY: perform document retrieval.
        - HYBRID: perform document retrieval.
        - DATA_ONLY: skip document retrieval (generic words such as 'what', 'how',
          'show', or 'explain' do not independently trigger RAG for DATA_ONLY queries).
        - None: default to retrieving to support general/unparsed inquiries.
        """
        if intent is not None:
            if intent.intent_type in (IntentType.KNOWLEDGE_ONLY, IntentType.HYBRID):
                return True
            if intent.intent_type == IntentType.DATA_ONLY:
                return False
            return False
        # If intent is None, default to retrieving to support general inquiries
        return True

    def _build_data_summary(
        self,
        db_result: DatabaseExecutionResult,
        intent: Optional[QueryIntent] = None,
    ) -> DataSummary:
        """
        Deterministically inspects DatabaseExecutionResult to build an accurate DataSummary.
        Computes row counts, variable names, coordinate bounds, metric highlights,
        statistical distributions, null counts, and depth-stratified oceanographic summaries.
        """
        if not db_result.is_success or not db_result.rows:
            return DataSummary(
                total_records=db_result.row_count if db_result.is_success else 0,
                variables_present=[c for c in db_result.columns if not c.startswith("_")],
                highlights=["No records returned to summarize."] if db_result.is_success else [f"Execution error: {db_result.error_message}"],
                is_truncated=bool(getattr(db_result, "is_truncated", False)),
                sample_size=None,
                null_counts={},
                depth_strata=None,
            )

        rows = db_result.rows
        cols = db_result.columns
        variables_present = [c for c in cols if not c.startswith("_")]
        is_truncated = bool(getattr(db_result, "is_truncated", False))
        sample_size = len(rows) if is_truncated else None

        highlights: List[str] = []
        if is_truncated:
            highlights.append(
                f"Analyzed sample size: {len(rows)} records (truncated query result; total matching observation count in database is unknown)."
            )
        else:
            highlights.append(f"Total matching observation rows: {len(rows)}")

        # Check for pre-aggregated SQL results (single-row aggregation)
        AGGREGATE_PREFIXES = ("avg_", "min_", "max_", "std_", "stddev_", "var_", "median_", "count", "total_")
        is_single_row_aggregate = (
            len(rows) == 1 and (
                any(c.lower().startswith(p) for c in cols for p in AGGREGATE_PREFIXES)
                or (
                    intent is not None
                    and (
                        intent.aggregation_operation is not None
                        or intent.intent_category in (IntentCategory.AGGREGATION, IntentCategory.STATISTICS)
                    )
                    and not any(c.lower() in ("profile_id", "measurement_id", "created_at") for c in cols)
                    and not any(c.lower() in ("temp", "psal", "pres", "temperature_c", "salinity_psu", "pressure_dbar") for c in cols)
                )
            )
        )

        if is_single_row_aggregate:
            row0 = rows[0]
            for col in cols:
                val = row0.get(col)
                if _is_valid_numeric_measurement(val):
                    unit = _get_column_unit(col)
                    unit_str = f" {unit}" if unit else ""
                    if isinstance(val, int):
                        highlights.append(f"{col}: {val:,}{unit_str}")
                    else:
                        highlights.append(f"{col}: {val:.2f}{unit_str}")
                elif val is not None:
                    highlights.append(f"{col}: {val}")

            return DataSummary(
                total_records=len(rows),
                variables_present=variables_present,
                temporal_coverage=None,
                spatial_coverage=None,
                highlights=highlights,
                is_truncated=is_truncated,
                sample_size=sample_size,
                null_counts={},
                depth_strata=None,
            )

        # Raw Observational Processing
        numeric_candidates = [
            "temp", "psal", "pres", "temperature", "salinity", "pressure",
            "temperature_c", "salinity_psu", "pressure_dbar",
            "avg_temp", "avg_salinity", "max_temp", "min_temp"
        ]

        # 1. Deterministic summary statistics for measurement columns
        null_counts: Dict[str, int] = {}
        for num_col in cols:
            col_lower = num_col.lower()
            if any(cand in col_lower for cand in numeric_candidates):
                valid_values = [
                    r[num_col] for r in rows
                    if _is_valid_numeric_measurement(r.get(num_col))
                ]
                if valid_values:
                    val_min = min(valid_values)
                    val_max = max(valid_values)
                    val_mean = statistics.mean(valid_values)
                    val_median = statistics.median(valid_values)
                    val_std = statistics.stdev(valid_values) if len(valid_values) >= 2 else None
                    val_var = statistics.variance(valid_values) if len(valid_values) >= 2 else None

                    unit = _get_column_unit(num_col)
                    unit_str = f" {unit}" if unit else ""

                    stat_parts = [
                        f"min={val_min:.2f}{unit_str}",
                        f"max={val_max:.2f}{unit_str}",
                        f"mean={val_mean:.2f}{unit_str}",
                        f"median={val_median:.2f}{unit_str}",
                    ]
                    if val_std is not None:
                        stat_parts.append(f"stddev={val_std:.2f}{unit_str}")
                    if val_var is not None:
                        stat_parts.append(f"var={val_var:.2f}")

                    highlights.append(f"{num_col}: {', '.join(stat_parts)}")

        # 2. Null and missing value counts for relevant measurement columns
        for num_col in cols:
            col_lower = num_col.lower()
            if any(cand in col_lower for cand in numeric_candidates):
                none_count = sum(1 for r in rows if r.get(num_col) is None)
                if none_count > 0:
                    null_counts[num_col] = none_count
                    highlights.append(f"Missing values for {num_col}: {none_count} of {len(rows)} records null")

        # 3. Depth stratification when pressure column is present
        pres_col = next((c for c in cols if c.lower() in ("pressure_dbar", "pressure", "pres")), None)
        temp_col = next((c for c in cols if c.lower() in ("temperature_c", "temperature", "temp")), None)
        sal_col = next((c for c in cols if c.lower() in ("salinity_psu", "salinity", "psal")), None)

        depth_strata: Optional[Dict[str, Any]] = None
        if pres_col is not None:
            layer_counts = {"epipelagic": 0, "mesopelagic": 0, "bathypelagic": 0}
            layer_temps: Dict[str, List[float]] = {"epipelagic": [], "mesopelagic": [], "bathypelagic": []}
            layer_sals: Dict[str, List[float]] = {"epipelagic": [], "mesopelagic": [], "bathypelagic": []}

            for r in rows:
                p_val = r.get(pres_col)
                if not _is_valid_numeric_measurement(p_val):
                    continue
                # Exclude negative pressures
                if p_val < 0.0:
                    continue

                if 0.0 <= p_val <= 200.0:
                    layer = "epipelagic"
                elif 200.0 < p_val <= 1000.0:
                    layer = "mesopelagic"
                elif p_val > 1000.0:
                    layer = "bathypelagic"
                else:
                    continue

                layer_counts[layer] += 1

                if temp_col is not None:
                    t_val = r.get(temp_col)
                    if _is_valid_numeric_measurement(t_val):
                        layer_temps[layer].append(float(t_val))

                if sal_col is not None:
                    s_val = r.get(sal_col)
                    if _is_valid_numeric_measurement(s_val):
                        layer_sals[layer].append(float(s_val))

            has_strata_data = any(count > 0 for count in layer_counts.values())
            if has_strata_data:
                depth_strata = {
                    "epipelagic": {
                        "depth_range_dbar": [0.0, 200.0],
                        "observation_count": layer_counts["epipelagic"],
                        "temperature_mean_c": round(statistics.mean(layer_temps["epipelagic"]), 2) if layer_temps["epipelagic"] else None,
                        "temperature_count": len(layer_temps["epipelagic"]),
                        "salinity_mean_psu": round(statistics.mean(layer_sals["epipelagic"]), 2) if layer_sals["epipelagic"] else None,
                        "salinity_count": len(layer_sals["epipelagic"]),
                    },
                    "mesopelagic": {
                        "depth_range_dbar": [200.0, 1000.0],
                        "observation_count": layer_counts["mesopelagic"],
                        "temperature_mean_c": round(statistics.mean(layer_temps["mesopelagic"]), 2) if layer_temps["mesopelagic"] else None,
                        "temperature_count": len(layer_temps["mesopelagic"]),
                        "salinity_mean_psu": round(statistics.mean(layer_sals["mesopelagic"]), 2) if layer_sals["mesopelagic"] else None,
                        "salinity_count": len(layer_sals["mesopelagic"]),
                    },
                    "bathypelagic": {
                        "depth_range_dbar": [1000.0, None],
                        "observation_count": layer_counts["bathypelagic"],
                        "temperature_mean_c": round(statistics.mean(layer_temps["bathypelagic"]), 2) if layer_temps["bathypelagic"] else None,
                        "temperature_count": len(layer_temps["bathypelagic"]),
                        "salinity_mean_psu": round(statistics.mean(layer_sals["bathypelagic"]), 2) if layer_sals["bathypelagic"] else None,
                        "salinity_count": len(layer_sals["bathypelagic"]),
                    },
                }

                layer_labels = {
                    "epipelagic": "0–200 dbar",
                    "mesopelagic": "200–1000 dbar",
                    "bathypelagic": ">1000 dbar",
                }
                for l_name, l_label in layer_labels.items():
                    l_data = depth_strata[l_name]
                    if l_data["observation_count"] > 0:
                        desc_parts = [f"Depth stratum {l_name} ({l_label}): {l_data['observation_count']} obs"]
                        if l_data["temperature_mean_c"] is not None:
                            desc_parts.append(f"mean temp={l_data['temperature_mean_c']:.2f} °C (n={l_data['temperature_count']})")
                        if l_data["salinity_mean_psu"] is not None:
                            desc_parts.append(f"mean salinity={l_data['salinity_mean_psu']:.2f} PSU (n={l_data['salinity_count']})")
                        highlights.append(", ".join(desc_parts))

        # 4. Geographic bounds
        lat_col = next((c for c in cols if c.lower() in ("lat", "latitude")), None)
        lon_col = next((c for c in cols if c.lower() in ("lon", "long", "longitude")), None)
        spatial_cov = None
        if lat_col and lon_col:
            lats = [r[lat_col] for r in rows if _is_valid_numeric_measurement(r.get(lat_col))]
            lons = [r[lon_col] for r in rows if _is_valid_numeric_measurement(r.get(lon_col))]
            if lats and lons:
                spatial_cov = f"Lat: [{min(lats):.2f}, {max(lats):.2f}], Lon: [{min(lons):.2f}, {max(lons):.2f}]"
                highlights.append(f"Spatial coverage: {spatial_cov}")

        # 5. Temporal bounds
        time_col = next((c for c in cols if any(t in c.lower() for t in ("time", "date", "timestamp"))), None)
        temporal_cov = None
        if time_col:
            times = [str(r[time_col]) for r in rows if r.get(time_col) is not None and str(r[time_col]).strip()]
            if times:
                temporal_cov = f"{min(times)[:10]} to {max(times)[:10]}"
                highlights.append(f"Temporal span: {temporal_cov}")

        return DataSummary(
            total_records=len(rows),
            variables_present=variables_present,
            temporal_coverage=temporal_cov,
            spatial_coverage=spatial_cov,
            highlights=highlights,
            is_truncated=is_truncated,
            sample_size=sample_size,
            null_counts=null_counts,
            depth_strata=depth_strata,
        )

    def _build_visualization_spec(
        self,
        db_result: DatabaseExecutionResult,
        intent: Optional[QueryIntent] = None,
        query: Optional[str] = None,
    ) -> Optional[VisualizationSpec]:
        """
        Validates database columns and constructs an appropriate, grounded VisualizationSpec.
        Dynamically aligns the chart type (line, histogram, scatter, bar, map) with the user query,
        intent category, and empirical measurement dimensions without hardcoded profile defaults.
        NEVER invents columns or outputs a spec unsupported by the query results.
        """
        if not db_result.is_success or not db_result.rows or len(db_result.rows) < 1:
            return None

        cols = db_result.columns
        cols_lower_map = {c.lower(): c for c in cols}

        # Identify key column candidates with deterministic normalization
        pres_col = _find_physical_column(
            cols_lower_map,
            regex=_PRES_RE,
            primary_keys=("pres", "pressure", "pressure_dbar"),
        )
        temp_col = _find_physical_column(
            cols_lower_map,
            regex=_TEMP_RE,
            primary_keys=("temp", "temperature", "temperature_c"),
        )
        psal_col = _find_physical_column(
            cols_lower_map,
            regex=_PSAL_RE,
            primary_keys=("psal", "salinity", "salinity_psu"),
        )
        lat_col = _find_coordinate_column(
            cols_lower_map,
            regex=_LAT_RE,
            primary_keys=("lat", "latitude"),
        )
        lon_col = _find_coordinate_column(
            cols_lower_map,
            regex=_LON_RE,
            primary_keys=("lon", "longitude", "long"),
        )
        time_col = next(
            (
                cols_lower_map[c]
                for c in cols_lower_map
                if "time" in c or "date" in c or c in ("timestamp", "datetime", "month", "year")
            ),
            None,
        )
        series_col = (
            cols_lower_map.get("platform_number")
            or cols_lower_map.get("wmo_id")
            or cols_lower_map.get("platform")
            or cols_lower_map.get("float_id")
            or cols_lower_map.get("cycle_number")
        )

        # Verify usable (non-null) data for physical variables
        if psal_col:
            has_usable_salinity = any(r.get(psal_col) is not None for r in db_result.rows)
            if not has_usable_salinity:
                psal_col = None

        if temp_col:
            has_usable_temp = any(r.get(temp_col) is not None for r in db_result.rows)
            if not has_usable_temp:
                temp_col = None

        # Check intent preference for variable
        q_lower = query.lower() if query else ""
        category = intent.intent_category if intent else None
        vars_set = set(intent.physical_variables) if (intent and intent.physical_variables) else set()

        prefers_salinity = False
        if "salinity" in q_lower or (PhysicalVariable.PSAL in vars_set and PhysicalVariable.TEMP not in vars_set):
            prefers_salinity = True

        # Extract up to 100 observation records for interactive chart rendering
        chart_data = []
        for r in db_result.rows[:100]:
            clean_row = {}
            for k, v in r.items():
                if hasattr(v, "isoformat"):
                    clean_row[k] = v.isoformat()
                else:
                    clean_row[k] = v
            chart_data.append(clean_row)

        num_records = len(chart_data)

        # -------------------------------------------------------------------
        # 1. Histogram / Frequency Distribution
        # Triggered by requests for distribution, intervals, frequency, histogram
        # -------------------------------------------------------------------
        is_dist_request = any(
            k in q_lower for k in ("distribution", "histogram", "interval", "intervals", "frequency", "frequencies", "binned", "bins", "density")
        )
        if is_dist_request and (temp_col or psal_col):
            if prefers_salinity and psal_col:
                target_col = psal_col
                target_name = "Salinity"
                unit = "PSU"
            elif temp_col:
                target_col = temp_col
                target_name = "Temperature"
                unit = "°C"
            else:
                target_col = psal_col
                target_name = "Salinity"
                unit = "PSU"

            valid_vals = [
                float(r[target_col])
                for r in db_result.rows
                if _is_valid_numeric_measurement(r.get(target_col))
            ]

            if len(valid_vals) >= 2:
                v_min = min(valid_vals)
                v_max = max(valid_vals)
                num_bins = 6
                histogram_data = []

                if v_max <= v_min:
                    histogram_data.append({
                        "interval": f"{v_min:.1f} {unit}",
                        "count": len(valid_vals),
                        "bin_min": round(v_min, 2),
                        "bin_max": round(v_max, 2),
                    })
                else:
                    bin_width = (v_max - v_min) / num_bins
                    for i in range(num_bins):
                        b_start = v_min + i * bin_width
                        b_end = v_min + (i + 1) * bin_width if i < num_bins - 1 else v_max
                        if i < num_bins - 1:
                            b_count = sum(1 for v in valid_vals if b_start <= v < b_end)
                        else:
                            b_count = sum(1 for v in valid_vals if b_start <= v <= b_end)
                        interval_label = f"{b_start:.1f} - {b_end:.1f} {unit}"
                        histogram_data.append({
                            "interval": interval_label,
                            "count": b_count,
                            "bin_min": round(b_start, 2),
                            "bin_max": round(b_end, 2),
                        })

                return VisualizationSpec(
                    chart_type=ChartType.HISTOGRAM,
                    x_axis="interval",
                    y_axis="count",
                    title=f"{target_name} Measurement Distribution",
                    invert_y=False,
                    series_column=None,
                    description=f"Frequency distribution of {len(valid_vals)} {target_name.lower()} observations across {len(histogram_data)} intervals.",
                    data=histogram_data,
                )

        # -------------------------------------------------------------------
        # 2. Scatter Plot (Relationship / Correlation / Temperature vs Salinity)
        # Triggered by requests for scatter, versus, relationship, T-S diagram
        # -------------------------------------------------------------------
        is_scatter_request = any(
            k in q_lower for k in ("scatter", "versus", " vs ", " vs.", "relationship", "correlation", "t-s", "ts diagram", "t/s")
        ) or (
            category == IntentCategory.COMPARISON
            and temp_col
            and psal_col
            and not any(k in q_lower for k in ("profile", "vertical", "depth", "pressure"))
        ) or (
            "temperature" in q_lower
            and "salinity" in q_lower
            and not any(k in q_lower for k in ("profile", "vertical", "depth", "pressure", "distribution", "histogram"))
        )

        if is_scatter_request and temp_col and psal_col:
            scatter_data = []
            for r in db_result.rows:
                if _is_valid_numeric_measurement(r.get(temp_col)) and _is_valid_numeric_measurement(r.get(psal_col)):
                    item = {
                        temp_col: float(r[temp_col]),
                        psal_col: float(r[psal_col]),
                    }
                    if series_col and r.get(series_col):
                        item[series_col] = str(r[series_col])
                    scatter_data.append(item)
                    if len(scatter_data) >= 150:
                        break

            if len(scatter_data) >= 2:
                if "salinity versus temperature" in q_lower or "salinity vs temperature" in q_lower or "salinity vs. temperature" in q_lower:
                    x_c, y_c = psal_col, temp_col
                    title_str = "Salinity vs Temperature Relationship"
                else:
                    x_c, y_c = temp_col, psal_col
                    title_str = "Temperature vs Salinity Relationship"

                return VisualizationSpec(
                    chart_type=ChartType.SCATTER,
                    x_axis=x_c,
                    y_axis=y_c,
                    title=title_str,
                    invert_y=False,
                    series_column=series_col if (series_col and any(r.get(series_col) for r in scatter_data)) else None,
                    description="Scatter plot showing the relationship between ocean temperature and salinity measurements.",
                    data=scatter_data,
                )

        # -------------------------------------------------------------------
        # 3. Time Series / Chronological Line Chart
        # Triggered by requests for over time, time series, trend, profile date
        # -------------------------------------------------------------------
        is_time_request = any(
            k in q_lower for k in ("over time", "time series", "chronological", "timeline", "temporal", "grouped by profile date", "by profile date", "by date", "trend over time")
        ) or (
            category == IntentCategory.TEMPORAL
            and time_col
            and not any(k in q_lower for k in ("profile", "vertical", "depth", "pressure"))
        )

        if (is_time_request or (time_col and not pres_col)) and time_col and (temp_col or psal_col):
            if prefers_salinity and psal_col:
                target_col = psal_col
                target_name = "Salinity"
            elif temp_col:
                target_col = temp_col
                target_name = "Temperature"
            else:
                target_col = psal_col
                target_name = "Salinity"

            from collections import defaultdict
            grouped_time = defaultdict(list)
            for r in db_result.rows:
                t = r.get(time_col)
                v = r.get(target_col)
                if t is not None and _is_valid_numeric_measurement(v):
                    t_str = t.isoformat() if hasattr(t, "isoformat") else str(t)
                    grouped_time[t_str].append(float(v))

            if len(grouped_time) >= 2:
                time_series_data = []
                for t_val, v_list in sorted(grouped_time.items()):
                    mean_v = round(statistics.mean(v_list), 2)
                    time_series_data.append({
                        time_col: t_val,
                        target_col: mean_v,
                    })
                title_suffix = " (Grouped by Profile Date)" if "grouped" in q_lower or "profile date" in q_lower else ""
                return VisualizationSpec(
                    chart_type=ChartType.LINE,
                    x_axis=time_col,
                    y_axis=target_col,
                    title=f"{target_name} Over Time{title_suffix}",
                    invert_y=False,
                    series_column=series_col if (series_col and len(set(r.get(series_col) for r in db_result.rows if r.get(series_col))) > 1) else None,
                    description=f"Chronological variation of {target_name.lower()} measurements over time.",
                    data=time_series_data,
                )
            elif len(chart_data) >= 2:
                return VisualizationSpec(
                    chart_type=ChartType.LINE,
                    x_axis=time_col,
                    y_axis=target_col,
                    title=f"{target_name} Time Series Trend",
                    invert_y=False,
                    series_column=series_col if (series_col and len(set(r.get(series_col) for r in db_result.rows if r.get(series_col))) > 1) else None,
                    description=f"Temporal variation of {target_name.lower()} observations over time.",
                    data=chart_data,
                )

        # -------------------------------------------------------------------
        # 4. Depth Range / Strata Bar Chart
        # Triggered by requests for depth range, depth strata, depth layers
        # -------------------------------------------------------------------
        is_depth_range_request = any(
            k in q_lower for k in ("depth range", "by depth", "strata", "stratum", "depth layer", "depth intervals")
        )
        if is_depth_range_request and pres_col and (temp_col or psal_col):
            if prefers_salinity and psal_col:
                target_col = psal_col
                target_name = "Salinity"
            else:
                target_col = temp_col or psal_col
                target_name = "Temperature"

            strata_buckets = [
                ("Epipelagic (0-200 dbar)", 0.0, 200.0, []),
                ("Mesopelagic (200-1000 dbar)", 200.0, 1000.0, []),
                ("Bathypelagic (>1000 dbar)", 1000.0, float("inf"), []),
            ]
            for r in db_result.rows:
                p_val = r.get(pres_col)
                v_val = r.get(target_col)
                if _is_valid_numeric_measurement(p_val) and _is_valid_numeric_measurement(v_val):
                    p_num = float(p_val)
                    v_num = float(v_val)
                    for name, p_min, p_max, vals in strata_buckets:
                        if p_min <= p_num < p_max or (p_max == float("inf") and p_num >= p_min):
                            vals.append(v_num)
                            break

            depth_data = []
            for name, _, _, vals in strata_buckets:
                if vals:
                    depth_data.append({
                        "depth_range": name,
                        f"avg_{target_col}": round(statistics.mean(vals), 2),
                        "count": len(vals),
                    })

            if depth_data:
                return VisualizationSpec(
                    chart_type=ChartType.BAR,
                    x_axis="depth_range",
                    y_axis=f"avg_{target_col}",
                    title=f"Average {target_name} by Depth Range",
                    invert_y=False,
                    series_column=None,
                    description=f"Average ocean {target_name.lower()} stratified across depth zones.",
                    data=depth_data,
                )

        # -------------------------------------------------------------------
        # 5. Geographic Map (Explicit Map Request)
        # Triggered by requests for map, locations, coordinates
        # -------------------------------------------------------------------
        is_map_request = any(
            k in q_lower for k in ("map", "location", "locations", "positions", "spatial", "coordinates", "trajectory", "track")
        )
        if is_map_request and lon_col and lat_col and num_records >= 1:
            return VisualizationSpec(
                chart_type=ChartType.MAP,
                x_axis=lon_col,
                y_axis=lat_col,
                title="Float Observation Coordinates",
                invert_y=False,
                series_column=series_col,
                description="Geographical distribution and spatial positions of ARGO profiles.",
                data=chart_data,
            )

        # -------------------------------------------------------------------
        # 6. Vertical Oceanographic Profile: (Temperature or Salinity vs Pressure/Depth)
        # Default for water column depth/pressure profiles
        # -------------------------------------------------------------------
        if num_records >= 2 and pres_col and (temp_col or psal_col):
            if prefers_salinity and psal_col:
                return VisualizationSpec(
                    chart_type=ChartType.LINE,
                    x_axis=psal_col,
                    y_axis=pres_col,
                    title="Vertical Salinity Profile (S vs P)",
                    invert_y=True,
                    series_column=series_col,
                    description="Vertical salinity profile showing water column structure with inverted pressure axis.",
                    data=chart_data,
                )
            if temp_col:
                return VisualizationSpec(
                    chart_type=ChartType.LINE,
                    x_axis=temp_col,
                    y_axis=pres_col,
                    title="Vertical Temperature Profile (T vs P)",
                    invert_y=True,
                    series_column=series_col,
                    description="Vertical ocean temperature profile showing depth variation with inverted pressure axis.",
                    data=chart_data,
                )
            if psal_col:
                return VisualizationSpec(
                    chart_type=ChartType.LINE,
                    x_axis=psal_col,
                    y_axis=pres_col,
                    title="Vertical Salinity Profile (S vs P)",
                    invert_y=True,
                    series_column=series_col,
                    description="Vertical salinity profile showing water column structure with inverted pressure axis.",
                    data=chart_data,
                )

        # -------------------------------------------------------------------
        # 7. Fallback: Geographic Map
        # -------------------------------------------------------------------
        if num_records >= 1 and lon_col and lat_col:
            return VisualizationSpec(
                chart_type=ChartType.MAP,
                x_axis=lon_col,
                y_axis=lat_col,
                title="Float Observation Coordinates",
                invert_y=False,
                series_column=series_col,
                description="Geographical distribution and spatial positions of ARGO profiles.",
                data=chart_data,
            )

        # -------------------------------------------------------------------
        # 8. Fallback: Categorical Bar
        # -------------------------------------------------------------------
        count_col = next((cols_lower_map[c] for c in cols_lower_map if "count" in c or "total" in c), None)
        cat_candidates = (
            "platform_number",
            "platform",
            "wmo_id",
            "float_id",
            "month",
            "year",
            "region",
            "ocean",
            "cycle_number",
        )
        cat_col = next((cols_lower_map[c] for c in cols_lower_map if c in cat_candidates), None)
        if num_records >= 1 and cat_col and (count_col or temp_col or psal_col):
            y_metric = count_col or temp_col or psal_col
            return VisualizationSpec(
                chart_type=ChartType.BAR,
                x_axis=cat_col,
                y_axis=y_metric,
                title="Observation Distribution",
                invert_y=False,
                series_column=None,
                description="Categorical distribution of observations across platforms or intervals.",
                data=chart_data,
            )

        # No suitable dimensions or minimum observations for standard chart types
        return None

    @staticmethod
    def _attempt_recover_response_payload(raw_text: Optional[str]) -> Optional[_LLMResponsePayload]:
        """
        Attempts to safely extract a valid _LLMResponsePayload from raw LLM output text,
        recovering usable answers from truncated JSON or non-conformant structured responses
        without requiring a second expensive LLM inference call.
        """
        if not raw_text or not raw_text.strip():
            return None

        cleaned = raw_text.strip()
        # Clean markdown code block fencing if present
        if cleaned.startswith("```json"):
            cleaned = cleaned[7:]
        elif cleaned.startswith("```"):
            cleaned = cleaned[3:]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
        cleaned = cleaned.strip()

        # 1. Try standard JSON decode
        try:
            data = json.loads(cleaned)
            if isinstance(data, dict):
                ans = data.get("answer")
                if isinstance(ans, str) and len(ans.strip()) >= 20:
                    raw_cits = data.get("citations")
                    cits = raw_cits if isinstance(raw_cits, list) else []
                    return _LLMResponsePayload(answer=ans.strip(), citations=cits)
        except Exception:
            pass

        # 2. Extract answer field via regex from truncated or malformed JSON
        # 2a. Fully closed string: "answer": "..."
        match_closed = re.search(r'"answer"\s*:\s*"((?:[^"\\]|\\.)*)"', cleaned, re.DOTALL)
        if match_closed:
            ans_raw = match_closed.group(1)
            try:
                ans = json.loads(f'"{ans_raw}"')
            except Exception:
                ans = ans_raw.replace('\\"', '"').replace('\\n', '\n')
            if ans and len(ans.strip()) >= 20:
                return _LLMResponsePayload(answer=ans.strip(), citations=[])

        # 2b. Truncated string at end of buffer: "answer": "...<EOF>
        match_unclosed = re.search(r'"answer"\s*:\s*"((?:[^"\\]|\\.)*)$', cleaned, re.DOTALL)
        if match_unclosed:
            ans_raw = match_unclosed.group(1)
            ans_raw = re.sub(r'\\+$', '', ans_raw)
            try:
                ans = json.loads(f'"{ans_raw}"')
            except Exception:
                ans = ans_raw.replace('\\"', '"').replace('\\n', '\n')
            if ans and len(ans.strip()) >= 20:
                return _LLMResponsePayload(answer=ans.strip(), citations=[])

        # 3. Direct Markdown text response (if model replied in natural language rather than JSON)
        if not cleaned.startswith("{") and len(cleaned) >= 20:
            return _LLMResponsePayload(answer=cleaned, citations=[])

        return None

    def _invoke_llm(self, prompt: str) -> Tuple[Optional[_LLMResponsePayload], Optional[str], Optional[str]]:
        """
        Executes generation through BaseLLMProvider.
        First attempts structured Pydantic generation; if that fails, attempts
        recovery from raw output before falling back to free-form or deterministic fallback.
        Guarantees no duplicate generation when output was truncated by token limit.
        Returns (payload, raw_text, error_message).
        """
        max_tokens = self.config.ollama_num_predict_response
        try:
            payload: _LLMResponsePayload = self.llm_provider.generate_structured(
                prompt=prompt,
                response_model=_LLMResponsePayload,
                system_prompt=SCIENTIFIC_RESPONSE_SYSTEM_PROMPT,
                temperature=0.0,
                max_tokens=max_tokens,
            )
            # Normalize dict citations into Citation models
            normalized_citations: List[Citation] = []
            for c in payload.citations:
                if isinstance(c, Citation):
                    normalized_citations.append(c)
                elif isinstance(c, dict) and c.get("document_title"):
                    c_copy = dict(c)
                    if "chunk_id" in c_copy and c_copy["chunk_id"] is not None:
                        c_copy["chunk_id"] = str(c_copy["chunk_id"])
                    try:
                        normalized_citations.append(Citation(**c_copy))
                    except Exception:
                        pass
            payload.citations = normalized_citations
            return payload, None, None
        except LLMProviderError as e:
            raw_text = getattr(e, "raw_text", None)
            finish_reason = getattr(e, "finish_reason", None)

            # Step A: Attempt fast zero-latency payload recovery from already generated raw_text
            recovered = self._attempt_recover_response_payload(raw_text)
            if recovered is not None:
                logger.info(
                    "Recovered substantive answer payload (%d chars) from raw response without duplicate LLM call.",
                    len(recovered.answer),
                )
                return recovered, raw_text, None

            # Step B: If truncated by token limit or already substantial, NEVER run a duplicate 512-token call
            if finish_reason == "length" or (raw_text and len(raw_text.strip()) >= 100):
                logger.warning(
                    "Structured generation truncated (finish_reason='%s', len=%d). "
                    "Skipping duplicate LLM call and proceeding directly to deterministic synthesis.",
                    finish_reason,
                    len(raw_text.strip()) if raw_text else 0,
                )
                return None, raw_text, str(e)

            # Step C: If connection or timeout error, do not retry
            if isinstance(e, (LLMTimeoutError, LLMConnectionError)):
                logger.warning("LLM connection/timeout error: %s. Skipping retry.", e)
                return None, raw_text, str(e)

            # Step D: Only attempt free-form fallback if raw_text was empty/unusable AND not a length limit
            logger.warning("Structured LLM generation issue: %s. Attempting free-form text generation...", e)
            try:
                gen_res = self.llm_provider.generate(
                    prompt=prompt,
                    system_prompt=SCIENTIFIC_RESPONSE_SYSTEM_PROMPT,
                    temperature=0.0,
                    max_tokens=max_tokens,
                )
                if gen_res and isinstance(gen_res.text, str) and gen_res.text.strip():
                    raw_content = gen_res.text.strip()
                    return _LLMResponsePayload(answer=raw_content, citations=[]), raw_content, None
            except Exception as e2:
                logger.warning("Free-form generation fallback also failed: %s", e2)
            return None, raw_text, str(e)
        except Exception as e:
            logger.warning("Unexpected error during LLM response generation: %s", e)
            return None, None, str(e)


    def _ground_citations(
        self,
        candidate_citations: List[Citation],
        retrieved_chunks: List[RetrievedChunk],
    ) -> List[Citation]:
        """
        Filters and validates candidate citations against actually retrieved chunks.
        Disallows citations that have no grounding in the retrieved passages.
        """
        if not retrieved_chunks:
            return []

        grounded: List[Citation] = []
        retrieved_titles = {chunk.document_title.strip().lower(): chunk for chunk in retrieved_chunks}

        for cit in candidate_citations:
            cit_title_lower = cit.document_title.strip().lower()
            matching_chunk = None

            # Match by document title substring
            for doc_title_lower, chunk in retrieved_titles.items():
                if cit_title_lower in doc_title_lower or doc_title_lower in cit_title_lower:
                    matching_chunk = chunk
                    break

            if matching_chunk is not None:
                grounded.append(
                    Citation(
                        document_title=matching_chunk.document_title,
                        section_title=cit.section_title or matching_chunk.section_title,
                        chunk_id=str(matching_chunk.chunk_id) if matching_chunk.chunk_id is not None else cit.chunk_id,
                        snippet=cit.snippet or matching_chunk.chunk_content[:200] + "...",
                    )
                )

        # If LLM didn't produce citations but we retrieved authoritative chunks, attach the top retrieved chunk
        if not grounded and retrieved_chunks:
            top = retrieved_chunks[0]
            grounded.append(
                Citation(
                    document_title=top.document_title,
                    section_title=top.section_title,
                    chunk_id=str(top.chunk_id) if top.chunk_id is not None else None,
                    snippet=top.chunk_content[:200] + "...",
                )
            )

        return grounded

    def _build_deterministic_fallback(
        self,
        query: str,
        retrieved_chunks: List[RetrievedChunk],
        db_result: Optional[DatabaseExecutionResult],
        data_summary: Optional[DataSummary],
    ) -> Tuple[str, List[Citation]]:
        """
        Deterministic, hallucination-free answer generator when LLM is unavailable.
        Uses pure deterministic extraction from data summary and retrieved chunks.
        """
        paragraphs = []
        citations: List[Citation] = []

        # 1. Observational data section
        if db_result is not None and db_result.is_success and db_result.rows:
            if getattr(db_result, "is_truncated", False):
                paragraphs.append(
                    f"### Observational Data Results\nA sample of **{len(db_result.rows)}** observation records was analyzed (query results were truncated by safety limits; total database matches unknown)."
                )
            else:
                paragraphs.append(
                    f"### Observational Data Results\nA total of **{len(db_result.rows)}** observation records were retrieved from the ARGO database."
                )
            if data_summary and data_summary.highlights:
                highlights_text = "\n".join(f"- {h}" for h in data_summary.highlights)
                paragraphs.append(f"**Key Observational Metrics:**\n{highlights_text}")
        elif db_result is not None and db_result.is_success and not db_result.rows:
            paragraphs.append("### Observational Data Results\nNo observation records matched the specified spatial-temporal filters.")
        elif db_result is not None and not db_result.is_success:
            paragraphs.append(f"### Observational Data Results\nDatabase query could not be executed: {db_result.error_message}")

        # 2. Scientific literature section
        if retrieved_chunks:
            paragraphs.append("### Scientific Background & Literature")
            for idx, chunk in enumerate(retrieved_chunks[:2], 1):
                doc_title = chunk.document_title
                sec_title = chunk.section_title or "General"
                paragraphs.append(
                    f"**From *{doc_title}* ({sec_title}):**\n"
                    f"{chunk.chunk_content[:350].strip()}... [{doc_title}, {sec_title}]"
                )
                citations.append(
                    Citation(
                        document_title=doc_title,
                        section_title=sec_title,
                        chunk_id=str(chunk.chunk_id) if chunk.chunk_id is not None else f"c{idx}",
                        snippet=chunk.chunk_content[:200] + "...",
                    )
                )
        else:
            if db_result is None or not db_result.rows:
                paragraphs.append("Information not found in authoritative ARGO documentation.")

        answer = "\n\n".join(paragraphs) if paragraphs else "No evidence available to formulate an answer."
        return answer, citations
