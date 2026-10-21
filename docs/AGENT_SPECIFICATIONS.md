# FloatChat: Detailed Agent Specifications

**Document Version:** 1.0.0  
**Phase:** Phase 0 (Architecture & Specification)  
**Status:** Approved Specification  

---

## 1. Query Understanding Agent

### Purpose
The Query Understanding Agent serves as the gateway to the AI workflow. It analyzes raw natural language user inputs, classifies the query intent, and extracts structured spatial-temporal slot parameters into a validated Pydantic model.

### Responsibilities
- Classify user query intent into `KNOWLEDGE_ONLY`, `DATA_ONLY`, or `HYBRID`.
- Classify taxonomy subcategory (retrieval, filtering, aggregation, statistics, temporal, pressure_depth, float_specific, spatial, comparison, combined).
- Extract spatial parameters (latitude/longitude bounding box).
- Extract temporal bounds (start timestamp, end timestamp).
- Extract oceanographic variables (`TEMP`, `PSAL`, `PRES`).
- Extract platform metadata (WMO float IDs stored in `QueryIntent.wmo_ids`, which map to database column `argo_floats.platform_number`).
- Interpret explicit depth requests in meters into pressure in decibars ($1\text{ dbar} \approx 1\text{ m}$) with `is_depth_requested = True`.
- Flag ambiguous requests (`needs_clarification = True`) and unsupported requests (`is_supported = False`).

### Inputs & Outputs
- **Input:** Raw user prompt string.
- **Output:** Strongly-typed Pydantic `QueryIntent` object:
  ```json
  {
    "intent_type": "DATA_ONLY",
    "intent_category": "filtering",
    "physical_variables": ["TEMP", "PSAL"],
    "aggregation_operation": null,
    "spatial_bounds": {"latitude_min": -10.0, "latitude_max": 10.0, "longitude_min": 60.0, "longitude_max": 80.0},
    "temporal_range": {"start_date": "2024-01-01", "end_date": "2024-01-31"},
    "pressure_range": {"pressure_min": 0.0, "pressure_max": 500.0, "is_depth_requested": false},
    "wmo_ids": ["2901550"],
    "comparison_target": null,
    "is_supported": true,
    "needs_clarification": false,
    "clarification_question": null,
    "unsupported_reason": null
  }
  ```

### Tools & Dependencies
- `BaseLLMProvider.generate_structured()` using Pydantic JSON schema enforcement.

### Restrictions
- Must NOT generate SQL statements.
- Must NOT attempt document retrieval or database calls.
- Must NOT invent unmentioned spatial, temporal, or numerical constraints.

### Failure Cases & Mitigation
- **Empty Query Input:** Raises `ValueError("Query string cannot be empty.")`.
- **Malformed LLM JSON / Validation Error:** Caught by Pydantic schema validation; raises `LLMStructuredOutputError`. Does not invent or guess unmentioned slots.
- **LLM Connection Failure / Timeout:** Propagates `LLMConnectionError` or `LLMTimeoutError`.

### Success Criteria
- >90% classification accuracy on benchmark evaluation dataset.

---

## 2. Data Query Agent (Text-to-SQL)

### Purpose
The Data Query Agent translates structured data query intents into candidate PostGIS spatial SQL queries targeting physical oceanographic observation tables.

### Responsibilities
- Construct syntactically valid PostgreSQL / PostGIS SQL queries based on `QueryIntent` slot parameters.
- Target verified physical observation tables (`argo_floats`, `argo_profiles`, `argo_measurements`).
- Correctly map `QueryIntent.wmo_ids` to `argo_profiles.platform_number` / `argo_floats.platform_number`.
- Correctly map physical variables: `TEMP` $\to$ `temperature_c`, `PSAL` $\to$ `salinity_psu`, `PRES` $\to$ `pressure_dbar`.
- Apply PostGIS spatial functions (`ST_MakeEnvelope`, `ST_Within`, `ST_DWithin`, `ST_SetSRID`) when spatial geometry is available, or bounding-box coordinate predicates (`latitude BETWEEN ... AND ...`) in fallback environments.

### Inputs & Outputs
- **Input:** Validated `QueryIntent` object + physical Database DDL schema + SQL prompt guidelines.
- **Output:** Candidate SQL string:
  ```sql
  SELECT p.platform_number, p.latitude, p.longitude, m.pressure_dbar, m.temperature_c, m.salinity_psu
  FROM argo_profiles p
  JOIN argo_measurements m ON p.profile_id = m.profile_id
  WHERE ST_Within(p.location, ST_MakeEnvelope(60.0, -10.0, 80.0, 10.0, 4326))
    AND m.pressure_dbar BETWEEN 0 AND 500
  LIMIT 500;
  ```

### Tools & Dependencies
- `BaseLLMProvider.generate()` with detailed database DDL prompt and few-shot examples.

### Restrictions
- Must only generate `SELECT` queries.
- Prohibited from generating `INSERT`, `UPDATE`, `DELETE`, `DROP`, `ALTER`, `TRUNCATE`, `EXEC`.
- Output is strictly passed to the **Deterministic SQL Validator** before execution.
- Never directly executes queries or connects to the database.

### Failure Cases & Mitigation
- **Invalid SQL Syntax / Unknown Column:** Caught deterministically by `sqlglot` AST parser in the validator; error message is fed back to the Data Query Agent for a maximum of 1 auto-retry.

### Success Criteria
- >85% execution correctness rate on benchmark data queries.

---

## 3. Scientific Knowledge & Response Agent

### Purpose
The Scientific Knowledge & Response Agent is the consolidated third primary agent responsible for domain knowledge retrieval, grounded factual answer synthesis, inline citations, numerical result contextualization, and interactive visualization specification generation.

### Responsibilities
1. **Internal Scientific RAG Retrieval:** Queries `argo_doc_embeddings` in `pgvector` for authoritative ARGO program documentation chunks matching the user's scientific question.
2. **Grounded Factual Synthesis:** Synthesizes natural-language answers strictly grounded in retrieved document chunks, attaching explicit inline citations (`[Document Title, Section, Page]`).
3. **Observation Result Contextualization:** When database results are supplied by the orchestration layer, interprets numerical observations, trends, averages, and distributions without inventing unobserved measurements.
4. **Interactive Visualization Specifications:** Emits validated Plotly / Recharts JSON configurations (e.g., vertical temperature/salinity profiles with inverted pressure Y-axis, geographic scatter maps, parameter distributions) when queries warrant visualization.
5. **Anti-Hallucination Guardrails:** Refuses to answer topics outside ingested documentation; returns explicit fallback: *"The requested scientific topic is not covered in authoritative ARGO documentation."*

### Inputs & Outputs
- **Inputs:**
  - Raw user prompt string.
  - Validated `QueryIntent` from Query Understanding Agent.
  - Retrieved scientific documentation chunks (for knowledge and hybrid queries).
  - Database query result tuples from Controlled DB Execution Layer (for data and hybrid queries).
- **Outputs:** Grounded Markdown response text + inline citations + optional Chart/Map JSON:
  ```json
  {
    "answer": "Water temperature in the selected equatorial profiles exhibits a steep thermocline drop from 28.5°C at 10 dbar down to 8.2°C at 500 dbar pressure. ARGO CTD sensors measure conductivity and temperature at high resolution [ARGO User Manual v3.4, Section 2.1].",
    "citations": [
      "ARGO User Manual v3.4, Section 2.1, p. 12"
    ],
    "visualization_spec": {
      "chart_type": "line",
      "x_axis": "temperature_c",
      "y_axis": "pressure_dbar",
      "invert_y": true,
      "title": "Temperature vs Pressure Profile"
    }
  }
  ```

### Tools & Dependencies
- `BaseLLMProvider.generate()` / `BaseLLMProvider.generate_structured()`.
- Internal vector retriever interface querying `argo_doc_embeddings` in PostgreSQL (`pgvector`).

### Restrictions
- Must NOT fabricate answers unsupported by retrieved text chunks or database result tuples.
- Must NOT generate SQL queries or bypass the Deterministic SQL Validator.
- Must NOT execute arbitrary database queries.

### Failure Cases & Mitigation
- **Low Retrieval Similarity:** Returns explicit message: *"Information not found in authoritative ARGO documentation"* rather than guessing.
- **Empty Database Results:** Informs user cleanly: *"No observation records matched the specified spatial-temporal filters."*
- **Malformed Chart Spec:** Schema validator catches JSON issues and falls back safely to textual narrative and raw tabular presentation.

### Success Criteria
- >90% answer faithfulness score; zero hallucinations on domain physics or numerical data.
