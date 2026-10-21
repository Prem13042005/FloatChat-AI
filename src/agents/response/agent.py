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

import logging
from typing import Any, Dict, List, Optional, Set, Tuple
from pydantic import BaseModel, Field

from src.agents.query_understanding.models import IntentType, QueryIntent
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
from src.llm import BaseLLMProvider, LLMProviderError, get_llm_provider
from src.rag.models import RetrievalResult, RetrievedChunk
from src.rag.retriever import ScientificDocumentRetriever

logger = logging.getLogger("floatchat.agents.response")


class _LLMResponsePayload(BaseModel):
    """Internal Pydantic schema for structured LLM generation."""
    answer: str = Field(description="Comprehensive Markdown answer narrative grounded in evidence.")
    citations: List[Citation] = Field(
        default_factory=list,
        description="List of document citations directly referenced in the answer."
    )


class ScientificResponseAgent:
    """
    Primary AI Agent responsible for synthesizing grounded scientific answers,
    contextualizing observational ARGO data, providing citations, and generating
    validated visualization specifications.
    """

    def __init__(
        self,
        llm_provider: Optional[BaseLLMProvider] = None,
        retriever: Optional[ScientificDocumentRetriever] = None,
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
        self.retriever = retriever if retriever is not None else ScientificDocumentRetriever(config=self.config)

    def respond(
        self,
        query: str,
        intent: Optional[QueryIntent] = None,
        db_result: Optional[DatabaseExecutionResult] = None,
        top_k: Optional[int] = None,
        similarity_threshold: Optional[float] = None,
    ) -> ScientificResponse:
        """
        Main entry point for generating an evidence-grounded scientific response.

        Args:
            query: User's natural language question.
            intent: Optional validated QueryIntent from Query Understanding Agent.
            db_result: Optional DatabaseExecutionResult from Controlled Database Execution Layer.
            top_k: Optional override for retrieval chunk count.
            similarity_threshold: Optional override for retrieval similarity threshold.

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

        # 1. Determine whether scientific document retrieval is needed
        needs_retrieval = self._should_retrieve_docs(cleaned_query, intent)
        retrieved_chunks: List[RetrievedChunk] = []

        if needs_retrieval:
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
            data_summary = self._build_data_summary(db_result)
            if db_result.is_success and db_result.row_count == 0:
                warnings.append("Database query returned 0 rows matching criteria.")
            elif not db_result.is_success:
                warnings.append(f"Database query execution issue: {db_result.error_message}")

        # 3. Generate and validate visualization specification (strictly grounded in columns)
        candidate_viz: Optional[VisualizationSpec] = None
        if db_result is not None and db_result.is_success and db_result.row_count >= 2:
            candidate_viz = self._build_visualization_spec(db_result, intent)

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
            return ScientificResponse(
                answer="No observation records matched the specified spatial-temporal filters in the database.",
                citations=[],
                data_summary=data_summary,
                visualization_spec=None,
                status=ResponseStatus.NO_DATA_MATCH,
                warnings=warnings,
            )

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
        """Determines whether semantic document retrieval should be invoked."""
        if intent is not None:
            if intent.intent_type in (IntentType.KNOWLEDGE_ONLY, IntentType.HYBRID):
                return True
            # For DATA_ONLY queries, check if the question also seeks domain context
            keywords = {"why", "how", "what", "explain", "sensor", "ctd", "qc", "flag", "manual", "accuracy", "principle", "meaning"}
            tokens = set(query.lower().split())
            if tokens.intersection(keywords):
                return True
            return False
        # If intent is None, default to retrieving to support general inquiries
        return True

    def _build_data_summary(self, db_result: DatabaseExecutionResult) -> DataSummary:
        """
        Deterministically inspects DatabaseExecutionResult to build an accurate DataSummary.
        Computes row counts, variable names, coordinate bounds, and metric highlights.
        """
        if not db_result.is_success or not db_result.rows:
            return DataSummary(
                total_records=db_result.row_count if db_result.is_success else 0,
                variables_present=[c for c in db_result.columns if not c.startswith("_")],
                highlights=["No records returned to summarize."] if db_result.is_success else [f"Execution error: {db_result.error_message}"],
            )

        rows = db_result.rows
        cols = db_result.columns
        variables_present = [c for c in cols if not c.startswith("_")]

        highlights: List[str] = []
        highlights.append(f"Total matching observation rows: {len(rows)}")

        # Check for numeric metrics to compute exact statistics (min, max, mean)
        numeric_candidates = ["temp", "psal", "pres", "temperature", "salinity", "pressure", "avg_temp", "avg_salinity", "max_temp", "min_temp"]
        for num_col in cols:
            col_lower = num_col.lower()
            if any(cand in col_lower for cand in numeric_candidates):
                values = [r[num_col] for r in rows if r.get(num_col) is not None and isinstance(r[num_col], (int, float))]
                if values:
                    val_min = min(values)
                    val_max = max(values)
                    val_mean = sum(values) / len(values)
                    highlights.append(f"{num_col}: min={val_min:.2f}, max={val_max:.2f}, mean={val_mean:.2f}")

        # Geographic bounds
        lat_col = next((c for c in cols if c.lower() in ("lat", "latitude")), None)
        lon_col = next((c for c in cols if c.lower() in ("lon", "long", "longitude")), None)
        spatial_cov = None
        if lat_col and lon_col:
            lats = [r[lat_col] for r in rows if r.get(lat_col) is not None and isinstance(r[lat_col], (int, float))]
            lons = [r[lon_col] for r in rows if r.get(lon_col) is not None and isinstance(r[lon_col], (int, float))]
            if lats and lons:
                spatial_cov = f"Lat: [{min(lats):.2f}, {max(lats):.2f}], Lon: [{min(lons):.2f}, {max(lons):.2f}]"
                highlights.append(f"Spatial coverage: {spatial_cov}")

        # Temporal bounds
        time_col = next((c for c in cols if any(t in c.lower() for t in ("time", "date", "timestamp"))), None)
        temporal_cov = None
        if time_col:
            times = [str(r[time_col]) for r in rows if r.get(time_col) is not None]
            if times:
                temporal_cov = f"{min(times)[:10]} to {max(times)[:10]}"
                highlights.append(f"Temporal span: {temporal_cov}")

        return DataSummary(
            total_records=len(rows),
            variables_present=variables_present,
            temporal_coverage=temporal_cov,
            spatial_coverage=spatial_cov,
            highlights=highlights,
        )

    def _build_visualization_spec(
        self,
        db_result: DatabaseExecutionResult,
        intent: Optional[QueryIntent] = None,
    ) -> Optional[VisualizationSpec]:
        """
        Validates database columns and constructs a grounded VisualizationSpec.
        NEVER invents columns or outputs a spec unsupported by the query results.
        """
        if not db_result.is_success or not db_result.rows or len(db_result.rows) < 2:
            return None

        cols = db_result.columns
        cols_lower_map = {c.lower(): c for c in cols}

        # Identify key column candidates
        pres_col = cols_lower_map.get("pres") or cols_lower_map.get("pressure") or cols_lower_map.get("pressure_dbar")
        temp_col = cols_lower_map.get("temp") or cols_lower_map.get("temperature") or cols_lower_map.get("temperature_c")
        psal_col = cols_lower_map.get("psal") or cols_lower_map.get("salinity")
        lat_col = cols_lower_map.get("lat") or cols_lower_map.get("latitude")
        lon_col = cols_lower_map.get("lon") or cols_lower_map.get("longitude") or cols_lower_map.get("long")
        time_col = next((cols_lower_map[c] for c in cols_lower_map if "time" in c or "date" in c), None)
        series_col = cols_lower_map.get("platform_number") or cols_lower_map.get("wmo_id") or cols_lower_map.get("cycle_number")

        # 1. Vertical Oceanographic Profile: (Temperature or Salinity vs Pressure/Depth)
        if pres_col and temp_col:
            return VisualizationSpec(
                chart_type=ChartType.LINE,
                x_axis=temp_col,
                y_axis=pres_col,
                title="Vertical Temperature Profile (T vs P)",
                invert_y=True,
                series_column=series_col,
                description="Vertical ocean temperature profile showing depth variation with inverted pressure axis.",
            )
        if pres_col and psal_col:
            return VisualizationSpec(
                chart_type=ChartType.LINE,
                x_axis=psal_col,
                y_axis=pres_col,
                title="Vertical Salinity Profile (S vs P)",
                invert_y=True,
                series_column=series_col,
                description="Vertical salinity profile showing water column structure with inverted pressure axis.",
            )

        # 2. Geographic Scatter Map: (Longitude vs Latitude)
        if lon_col and lat_col:
            return VisualizationSpec(
                chart_type=ChartType.MAP,
                x_axis=lon_col,
                y_axis=lat_col,
                title="Float Observation Coordinates",
                invert_y=False,
                series_column=series_col,
                description="Geographical distribution and spatial positions of ARGO profiles.",
            )

        # 3. Temporal Trend / Time Series: (Time vs Physical Variable)
        if time_col and (temp_col or psal_col):
            y_col = temp_col or psal_col
            var_name = "Temperature" if y_col == temp_col else "Salinity"
            return VisualizationSpec(
                chart_type=ChartType.LINE,
                x_axis=time_col,
                y_axis=y_col,
                title=f"{var_name} Time Series Trend",
                invert_y=False,
                series_column=series_col,
                description=f"Temporal variation of ocean {var_name.lower()} over time.",
            )

        # 4. Bar / Distribution: Aggregations or counts
        count_col = next((cols_lower_map[c] for c in cols_lower_map if "count" in c or "total" in c), None)
        cat_col = next((cols_lower_map[c] for c in cols_lower_map if c in ("platform_number", "wmo_id", "month", "year")), None)
        if cat_col and (count_col or temp_col or psal_col):
            y_metric = count_col or temp_col or psal_col
            return VisualizationSpec(
                chart_type=ChartType.BAR,
                x_axis=cat_col,
                y_axis=y_metric,
                title="Observation Distribution",
                invert_y=False,
                series_column=None,
                description="Categorical distribution of observations across platforms or intervals.",
            )

        # No suitable columns for standard chart types
        return None

    def _invoke_llm(self, prompt: str) -> Tuple[Optional[_LLMResponsePayload], Optional[str], Optional[str]]:
        """
        Executes generation through BaseLLMProvider.
        First attempts structured Pydantic generation; if that fails, falls back
        to raw text generation, and finally to deterministic template fallback.
        Returns (payload, raw_text, error_message).
        """
        try:
            payload: _LLMResponsePayload = self.llm_provider.generate_structured(
                prompt=prompt,
                response_model=_LLMResponsePayload,
                system_prompt=SCIENTIFIC_RESPONSE_SYSTEM_PROMPT,
                temperature=0.0,
            )
            return payload, None, None
        except LLMProviderError as e:
            logger.warning(f"Structured LLM generation issue: {e}. Attempting free-form text generation...")
            try:
                gen_res = self.llm_provider.generate(
                    prompt=prompt,
                    system_prompt=SCIENTIFIC_RESPONSE_SYSTEM_PROMPT,
                    temperature=0.0,
                )
                if gen_res and isinstance(gen_res.text, str) and gen_res.text.strip():
                    raw_content = gen_res.text.strip()
                    return _LLMResponsePayload(answer=raw_content, citations=[]), raw_content, None
            except Exception as e2:
                logger.warning(f"Free-form generation fallback also failed: {e2}")
            return None, None, str(e)
        except Exception as e:
            logger.warning(f"Unexpected error during LLM response generation: {e}")
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
            paragraphs.append(f"### Observational Data Results\nA total of **{len(db_result.rows)}** observation records were retrieved from the ARGO database.")
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
