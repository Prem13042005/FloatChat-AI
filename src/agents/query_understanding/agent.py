"""
src/agents/query_understanding/agent.py

FloatChat Query Understanding Agent Implementation.
Converts natural language user questions into validated QueryIntent Pydantic objects
using the provider-agnostic BaseLLMProvider abstraction layer.
"""

import re
from typing import Optional

from src.agents.query_understanding.gazetteer import find_matching_regions
from src.agents.query_understanding.models import (
    AggregationOp,
    IntentCategory,
    IntentType,
    QueryIntent,
    SpatialBounds,
)
from src.agents.query_understanding.prompts import QUERY_UNDERSTANDING_SYSTEM_PROMPT
from src.config import Config, get_config
from src.llm import BaseLLMProvider, get_llm_provider


def _has_explicit_numeric_coordinates(query: str) -> bool:
    """
    Checks if a user query contains explicit numeric coordinate constraints:
    e.g. '10N', '10°N', '10 degrees south', 'latitude between 10 and 20', '60E to 80E',
    'lat > 15', 'lon: 65'.
    """
    lower = query.lower()
    has_coord_keyword = bool(
        re.search(r"\b(lat|latitude|lon|long|longitude|coord|coordinates|bbox|degrees?)\b", lower)
    )
    has_directional_num = bool(
        re.search(r"\b\d+(\.\d+)?\s*(°|deg|degrees)?\s*[nsew]\b", lower)
    )
    has_num = bool(re.search(r"\d+(\.\d+)?", lower))

    if has_directional_num:
        return True
    if has_coord_keyword and has_num:
        return True
    return False


class QueryUnderstandingAgent:
    """
    Agent responsible for analyzing raw natural-language user inputs, classifying query intent,
    and extracting spatial, temporal, pressure, platform, and metric slot constraints.
    """

    def __init__(
        self,
        llm_provider: Optional[BaseLLMProvider] = None,
        config: Optional[Config] = None,
    ):
        """
        Initializes the QueryUnderstandingAgent.

        Args:
            llm_provider: Optional BaseLLMProvider instance.
                          If None, resolves active provider using `get_llm_provider()`.
            config: Optional Config instance. Defaults to get_config().
        """
        self.config = config or get_config()
        self.llm_provider = llm_provider if llm_provider is not None else get_llm_provider()

    def analyze(self, query: str) -> QueryIntent:
        """
        Analyzes a natural-language user query string and returns a structured QueryIntent object.

        Args:
            query: Natural language ocean data prompt string.

        Returns:
            Validated QueryIntent object.

        Raises:
            ValueError: If query is empty or whitespace-only.
            LLMProviderError: If underlying LLM provider generation or validation fails.
        """
        if not query or not query.strip():
            raise ValueError("Query string cannot be empty.")

        cleaned_query = query.strip()

        # Generate structured output via BaseLLMProvider abstraction
        intent: QueryIntent = self.llm_provider.generate_structured(
            prompt=cleaned_query,
            response_model=QueryIntent,
            system_prompt=QUERY_UNDERSTANDING_SYSTEM_PROMPT,
            temperature=0.0,
            max_tokens=self.config.ollama_num_predict_query_understanding,
        )

        # Deterministic slot refinement for counting and hybrid conceptual queries
        lower_q = cleaned_query.lower()
        has_counting = any(k in lower_q for k in ("how many", "count ", "count of", "number of", "total floats"))
        has_scientific_concept = any(
            k in lower_q for k in (
                "how do", "how does", "how is", "how ctd", "how the ctd",
                "explain how", "explain why", "explain ctd", "explain pss",
                "explain the ctd", "explain the pss", "explain the scale",
                "explain the practical salinity", "explain the physics",
                "explain the principles", "explain the sensor", "explain sensor",
                "what is the ctd", "what is pss", "measure ocean", "operating cycle",
                "mission cycle", "calibration", "ctd sensor", "pss-78", "salinity scale",
                "practical salinity scale", "changes with depth", "thermocline",
                "buoyancy", "water column structure"
            )
        )
        has_empirical_data = (
            len(intent.wmo_ids) > 0
            or bool(intent.spatial_bounds)
            or bool(intent.temporal_range)
            or (
                len(intent.physical_variables) > 0
                and any(k in lower_q for k in (
                    "observation", "observations", "measurement", "measurements",
                    "profile", "profiles", "plot", "show", "compare", "record",
                    "records", "reading", "readings", "data", "average", "mean",
                    "min", "max", "stat"
                ))
            )
        )

        if (has_scientific_concept and has_empirical_data) or (has_counting and has_scientific_concept):
            intent.intent_type = IntentType.HYBRID
            intent.intent_category = IntentCategory.COMBINED
            if has_counting:
                intent.aggregation_operation = AggregationOp.COUNT
            if "float" in lower_q and not intent.wmo_ids and not intent.physical_variables:
                intent.physical_variables = []
        elif has_counting and intent.aggregation_operation is None:
            intent.aggregation_operation = AggregationOp.COUNT
            if intent.intent_category in (IntentCategory.FLOAT_SPECIFIC, IntentCategory.RETRIEVAL):
                intent.intent_category = IntentCategory.AGGREGATION

        # Resolve target entity for counting/inventory queries if not already identified
        if not intent.target_entity:
            if "profile" in lower_q:
                intent.target_entity = "profiles"
            elif any(m in lower_q for m in ("measurement", "reading", "observation", "record")):
                intent.target_entity = "measurements"
            elif any(f in lower_q for f in ("float", "platform")):
                intent.target_entity = "floats"

        # Deterministic spatial gazetteer resolution and coordinate precedence
        matched_regions = find_matching_regions(cleaned_query)
        has_explicit_coords = _has_explicit_numeric_coordinates(cleaned_query)

        if len(matched_regions) == 1:
            if not has_explicit_coords:
                # Single recognized named region and no user coordinates -> apply gazetteer bounds
                _, gazetteer_bounds = matched_regions[0]
                intent.spatial_bounds = SpatialBounds(
                    latitude_min=gazetteer_bounds.latitude_min,
                    latitude_max=gazetteer_bounds.latitude_max,
                    longitude_min=gazetteer_bounds.longitude_min,
                    longitude_max=gazetteer_bounds.longitude_max,
                )
            # If user provided explicit coordinates, preserve them (do not overwrite)
        elif len(matched_regions) > 1:
            # Multiple distinct regions in query (e.g. comparison between regions)
            # Do NOT collapse them into a single overbroad bounding box
            if not has_explicit_coords:
                intent.spatial_bounds = None
        elif len(matched_regions) == 0 and not has_explicit_coords:
            # Zero recognized gazetteer regions and no user-supplied coordinates -> discard hallucinated coordinates
            intent.spatial_bounds = None

        # Synchronize 7-digit numeric ARGO platform identifiers into wmo_ids
        for explicit_id in re.findall(r"\b\d{7}\b", cleaned_query):
            if explicit_id not in intent.wmo_ids:
                intent.wmo_ids.append(explicit_id)

        if intent.comparison_target and intent.comparison_target.comparison_targets:
            for target in intent.comparison_target.comparison_targets:
                if isinstance(target, str):
                    clean_id = re.sub(r"(?i)\b(float|wmo|platform)\b", "", target).strip()
                    if re.fullmatch(r"\d{7}", clean_id):
                        if clean_id not in intent.wmo_ids:
                            intent.wmo_ids.append(clean_id)

        return intent
