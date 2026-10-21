# Phase 5 — Query Understanding Agent Specification

## 1. Purpose & Objective

The **Query Understanding Agent** serves as the initial gateway to the FloatChat AI processing workflow. Its sole responsibility is converting natural-language oceanographic questions into strongly-typed, validated `QueryIntent` Pydantic objects.

It abstracts intent classification, metric extraction, and spatial-temporal slot parsing while depending strictly on the provider-agnostic `BaseLLMProvider` interface established in Phase 4.

---

## 2. Responsibilities & Non-Responsibilities

### Responsibilities
- Classify user queries into high-level intent types (`KNOWLEDGE_ONLY`, `DATA_ONLY`, `HYBRID`).
- Categorize queries into FloatChat taxonomy subcategories (`retrieval`, `filtering`, `aggregation`, `statistics`, `temporal`, `pressure_depth`, `float_specific`, `spatial`, `comparison`, `combined`).
- Extract physical oceanographic variables (`TEMP`, `PSAL`, `PRES`).
- Extract spatial bounding box coordinates (`latitude_min/max`, `longitude_min/max`).
- Extract temporal date/time range bounds (`start_date`, `end_date`).
- Extract pressure (dbar) and depth (m) ranges.
- Extract platform/WMO float identification numbers.
- Flag ambiguous requests (`needs_clarification=True`) and unsupported requests (`is_supported=False`).

> [!IMPORTANT]
> ### Strict Non-Responsibilities (Explicitly Deferred)
> - **Phase 5 does NOT generate SQL queries.**
> - **Phase 5 does NOT execute database queries against PostgreSQL / PostGIS.**
> - **Phase 5 does NOT perform vector retrieval or RAG document lookups.**
> - **Phase 5 does NOT use LangGraph state graph routing.**
> - **Phase 5 does NOT generate charts, maps, or final user responses.**

---

## 3. Architecture

```
                       Natural Language User Prompt
                                    │
                                    ▼
                     ┌─────────────────────────────┐
                     │   QueryUnderstandingAgent   │
                     └──────────────┬──────────────┘
                                    │
                                    ▼
                     ┌─────────────────────────────┐
                     │  BaseLLMProvider.generate_  │
                     │         structured()        │
                     └──────────────┬──────────────┘
                                    │
                                    ▼
                     ┌─────────────────────────────┐
                     │    Pydantic QueryIntent     │
                     └─────────────────────────────┘
                                    │
                   (Handoff to Phase 6 Text-to-SQL / RAG)
```

---

## 4. QueryIntent Schema Specification

Defined in `src/agents/query_understanding/models.py`:

```python
class QueryIntent(BaseModel):
    intent_type: IntentType            # KNOWLEDGE_ONLY | DATA_ONLY | HYBRID
    intent_category: IntentCategory    # retrieval | filtering | aggregation | statistics | ...
    physical_variables: List[PhysicalVariable]  # [TEMP, PSAL, PRES]
    aggregation_operation: Optional[AggregationOp] # average | minimum | maximum | count | sum
    spatial_bounds: Optional[SpatialBounds]        # lat/lon min/max
    temporal_range: Optional[TemporalRange]        # start_date / end_date
    pressure_range: Optional[PressureRange]        # pressure_min/max, is_depth_requested
    wmo_ids: List[str]                             # Float WMO IDs
    comparison_target: Optional[ComparisonTarget]  # Comparison entities/properties
    is_supported: bool                             # True if supported V1 query
    needs_clarification: bool                     # True if prompt is ambiguous
    clarification_question: Optional[str]         # Follow-up prompt for user
    unsupported_reason: Optional[str]             # Explanation if query is unsupported
```

---

## 5. Supported Query Concepts (V1 Dataset)

| Concept | Supported Values | Notes |
| :--- | :--- | :--- |
| **Physical Variables** | `TEMP` (Temperature), `PSAL` (Salinity), `PRES` (Pressure) | Restricted to V1 dataset capabilities |
| **Aggregations** | `average`, `minimum`, `maximum`, `count`, `sum` | Standard SQL aggregations |
| **Pressure vs Depth** | Pressure in dbar (`PRES`). Depth requests flag `is_depth_requested=True`. | 1 dbar ≈ 1 m assumed without hydrostatic conversion |
| **Platform IDs** | WMO numbers (e.g. `2901550`) | String list matching physical database column `argo_floats.platform_number` |

---

## 6. Prompt Strategy

Defined in `src/agents/query_understanding/prompts.py`:

- **Role Definition**: FloatChat Query Understanding Agent.
- **Constraint Enforcement**: System prompt explicitly forbids generating SQL, inventing unmentioned filters, or extracting unsupported observation parameters.
- **Ambiguity Handling**: Directs the model to emit structured clarification questions when user intent is incomplete or ambiguous.

---

## 7. Pydantic Model Validation Rules

Model validation rules (`@model_validator(mode="after")`) enforce physical consistency:

1. `latitude_min <= latitude_max` (Range: -90° to 90°)
2. `longitude_min <= longitude_max` (Range: -180° to 180°)
3. `pressure_min <= pressure_max` (Pressure >= 0 dbar)
4. `start_date <= end_date` (ISO date comparison)

If range bounds are inverted, Pydantic raises a `ValueError`, which is handled deterministically by the Phase 4 provider layer.

---

## 8. Error Handling Strategy

1. **Empty Query Input**: `QueryUnderstandingAgent.analyze()` raises a `ValueError("Query string cannot be empty.")`.
2. **Provider Failures**: Network timeouts, HTTP errors, or missing models raise `LLMProviderError` subclasses (`LLMTimeoutError`, `LLMResponseError`).
3. **Malformed JSON / Validation Error**: Raises `LLMStructuredOutputError`.

---

## 9. Testing Strategy

The test suite in `tests/test_query_understanding.py` contains **22 offline unit tests**:

- **Mocked LLM Provider Boundary**: Tests use `unittest.mock.MagicMock(spec=BaseLLMProvider)`. Zero network calls or Ollama dependency.
- **Coverage**: Verifies physical metrics, aggregations, spatial/temporal/pressure slot parsing, explicit depth flags, comparisons, ambiguity questions, unsupported parameter rejection, range validation errors, empty query validation, and provider exception propagation.

---

## 10. Example Intent Transformations

### Example 1: Spatial Aggregation
- **User Prompt**: *"What is the average water temperature between 0 and 10 degrees north in January 2024?"*
- **QueryIntent Output**:
  ```json
  {
    "intent_type": "DATA_ONLY",
    "intent_category": "statistics",
    "physical_variables": ["TEMP"],
    "aggregation_operation": "average",
    "spatial_bounds": {"latitude_min": 0.0, "latitude_max": 10.0},
    "temporal_range": {"start_date": "2024-01-01", "end_date": "2024-01-31"},
    "is_supported": true
  }
  ```

### Example 2: Explicit Depth Query
- **User Prompt**: *"Show salinity profiles from the surface down to 200 meters depth."*
- **QueryIntent Output**:
  ```json
  {
    "intent_type": "DATA_ONLY",
    "intent_category": "pressure_depth",
    "physical_variables": ["PSAL"],
    "pressure_range": {"pressure_min": 0.0, "pressure_max": 200.0, "is_depth_requested": true},
    "is_supported": true
  }
  ```

---

## 11. Relationship to Phase 6 Data Query Agent (Text-to-SQL)

The `QueryIntent` object acts as the input payload for the Phase 6 Data Query Agent. Phase 6 will convert valid `QueryIntent` objects into PostGIS SQL queries (e.g. mapping `spatial_bounds` to `ST_MakeEnvelope` and `physical_variables` to physical table columns).

---

## 12. Known Limitations & Deferred Features

- **Model Latency**: Local `qwen2.5:1.5b-instruct` inference speed depends on local hardware CPU/GPU acceleration.
- **No Heuristic/Regex Fallback**: The current implementation strictly uses the configured LLM provider structured output pipeline; no heuristic fallback is implemented.
- **Deferred Features**: SQL generation and controlled database execution (Phase 6), Scientific Knowledge & Response Agent incorporating scientific RAG, grounded synthesis, and visualization specifications (Consolidated Phase 7/8), LangGraph routing of exactly three primary agents (Phase 9), FastAPI REST service (Phase 10).
