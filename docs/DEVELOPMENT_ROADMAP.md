# FloatChat: Canonical Master Development Roadmap (Phases 0 - 14)

**Document Version:** 1.0.0  
**Phase:** Phase 0 (Architecture & Specification)  
**Status:** Approved Specification  

---

## Roadmap Overview

```
+-----------------------------------------------------------------------------------+
|  PHASE 0: Architecture & Engineering Specification (Complete)                     |
+-----------------------------------------------------------------------------------+
                                          |
                                          v
+-----------------------------------------------------------------------------------+
|  DATA & DATABASE FOUNDATION                                                       |
|  Phase 1: ARGO Data Ingestion and Preprocessing (Complete)                        |
|  Phase 2: PostgreSQL + PostGIS Database Foundation (Complete)                     |
|  Phase 3: Deterministic SQL Validation / Security (Complete)                      |
+-----------------------------------------------------------------------------------+
                                          |
                                          v
+-----------------------------------------------------------------------------------+
|  CORE AI INFRASTRUCTURE & AGENTS                                                  |
|  Phase 4: LLM Provider Abstraction + Ollama Integration (Complete)                |
|  Phase 5: Query Understanding Agent (Complete — 22 Unit Tests Passing)            |
|  Phase 6: Data Query Agent (Text-to-SQL) & Controlled DB Execution                |
|  Phase 7/8: Scientific Knowledge & Response Agent (Consolidated RAG & Visuals)   |
+-----------------------------------------------------------------------------------+
                                          |
                                          v
+-----------------------------------------------------------------------------------+
|  ORCHESTRATION & SERVICES                                                         |
|  Phase 9: LangGraph Orchestration (Exactly Three Primary Agents)                  |
|  Phase 10: FastAPI AI Service                                                     |
+-----------------------------------------------------------------------------------+
                                          |
                                          v
+-----------------------------------------------------------------------------------+
|  INTEGRATION, EVALUATION & DEPLOYMENT                                             |
|  Phase 11: Java Backend Integration (Owned & Implemented by Another Team Member)  |
|  Phase 12: Next.js Frontend Integration (Owned & Implemented by Another Team Member) |
|  Phase 13: Evaluation and Benchmarking                                            |
|  Phase 14: Deployment, Demonstration and Final Optimization                       |
+-----------------------------------------------------------------------------------+
```

---

## Phase 0: Architecture and Engineering Specification

* **Objective:** Define the complete architectural blueprint, data models, agent boundaries, system topology, security policies, and implementation roadmap for FloatChat.
* **Prerequisites:** User request alignment and domain context understanding.
* **Implementation Tasks:**
  1. Author the 12 canonical documentation files in `docs/`.
  2. Create root repository configuration (`README.md`, `.env.example`, `.gitignore`).
  3. Define schemas for PostGIS spatial tables and pgvector documentation indexes.
  4. Formalize the 3 primary AI agent specifications vs. deterministic supporting components.
* **Testing Requirements:** Phase 0 audit against all architectural constraints (16 verification checks).
* **Exit Criteria:** Complete documentation set authored with zero architectural contradictions; Phase 0 audit passed.
* **Deliverables:** Canonical `docs/*.md` files, `README.md`, `.env.example`, `.gitignore`.

---

## Phase 1: ARGO Data Ingestion and Preprocessing

* **Objective:** Build a Python data pipeline to parse raw NetCDF (`.nc`) oceanographic files, extract spatial-temporal variables, verify NetCDF fields, and output clean relational records.
* **Prerequisites:** Phase 0 completion; sample NetCDF file (`Indian_ARGO_Floats_0f9d_516d_c560_U1788882326310.nc`).
* **Implementation Tasks:**
  1. Set up Python NetCDF parser using `netCDF4` / `xarray`.
  2. Inspect and extract verified fields (`PLATFORM_NUMBER`, `time`, `latitude`, `longitude`, `PRES`, `TEMP`, `PSAL`).
  3. Verify presence or absence of Quality Control (QC) fields in the dataset.
  4. Build batch ingestion script exporting clean CSV/Parquet intermediate records ready for database import.
* **Testing Requirements:** Unit tests for variable extraction; spatial coordinate validation (Indian Ocean bounds).
* **Exit Criteria:** Successful parsing of test NetCDF file with zero unhandled missing/corrupt records (17,339 measurements across 21 floats).
* **Deliverables:** `scripts/normalize_argo_dataset.py`, `scripts/validate_argo_data.py`, `data/processed/*.parquet`, validation report.

---

## Phase 2: PostgreSQL + PostGIS Database Foundation

* **Objective:** Deploy PostgreSQL with PostGIS for spatial-temporal oceanographic data and `pgvector` for document embeddings.
* **Prerequisites:** Phase 1 processed clean data; Docker / PostgreSQL environment.
* **Implementation Tasks:**
  1. Initialize PostgreSQL instance with `postgis` and `vector` extensions enabled.
  2. Execute DDL creating `argo_floats`, `argo_profiles`, `argo_measurements`, and `argo_doc_embeddings`.
  3. Create spatial GIST indexes on profile geometry and B-tree indexes on platform number and timestamps.
  4. Load Phase 1 processed data into database tables via idempotent batch loader.
* **Testing Requirements:** Execute spatial queries (`ST_DWithin`, `ST_Within`) and time-series aggregation queries.
* **Exit Criteria:** Spatial tables populated (17,339 rows); PostGIS spatial functions executing cleanly.
* **Deliverables:** `scripts/init-db.sql`, `scripts/load_parquet_to_postgis.py`, `tests/test_database_schema.py`, `tests/test_database_ingestion.py`.

---

## Phase 3: Deterministic SQL Validation / Security

* **Objective:** Build a deterministic, non-LLM security gate that parses, validates, and sanitizes generated SQL before execution.
* **Prerequisites:** Phase 2 database schema.
* **Implementation Tasks:**
  1. Integrate `sqlglot` parser to construct AST from generated SQL.
  2. Enforce strict `SELECT`-only constraint (reject `INSERT`, `UPDATE`, `DELETE`, `DROP`, `ALTER`, `SELECT INTO`).
  3. Enforce table and column allowlist validation matching physical schema.
  4. Enforce mandatory `LIMIT` clause injection and capping.
* **Testing Requirements:** Unit test suite with 37 test cases including SQL injection attempts, write queries, out-of-schema queries.
* **Exit Criteria:** 100% rejection rate for unsafe/invalid SQL; 100% pass rate for valid schema SELECT queries.
* **Deliverables:** `src/security/sql_validator.py`, `tests/test_sql_validator.py`.

---

## Phase 4: LLM Provider Abstraction + Ollama Integration

* **Objective:** Construct a unified provider interface supporting local Ollama models (primary) and cloud providers (Gemini, pluggable).
* **Prerequisites:** Phase 0 specifications; Python environment.
* **Implementation Tasks:**
  1. Define base interface `BaseLLMProvider` with `generate()` and `generate_structured()` methods.
  2. Implement `OllamaProvider` connecting to local Ollama instance (`qwen2.5:1.5b-instruct` default).
  3. Implement `GeminiProvider` using Google GenAI SDK for cloud fallback (lazy-loaded).
  4. Add configuration selector (`LLM_PROVIDER=ollama` or `LLM_PROVIDER=gemini`) via `src/config.py`.
* **Testing Requirements:** Unit & integration tests verifying JSON schema output enforcement across providers (15 tests).
* **Exit Criteria:** Ability to switch between Ollama and Gemini via config without modifying agent logic.
* **Deliverables:** `src/llm/base.py`, `src/llm/ollama_provider.py`, `src/llm/gemini_provider.py`, `src/config.py`, `tests/test_llm_provider.py`.

---

## Phase 5: Query Understanding Agent

* **Objective:** Build the Query Understanding Agent to classify intent (`KNOWLEDGE_ONLY`, `DATA_ONLY`, `HYBRID`) and extract structured physical parameters into a validated Pydantic model.
* **Status:** Complete (22 unit tests passing).
* **Implementation Details:**
  1. Defined Pydantic schemas in `src/agents/query_understanding/models.py` with physical range validators.
  2. Prompt template engineering with system instructions in `src/agents/query_understanding/prompts.py`.
  3. Physical implementation delegates structured output extraction to `llm_provider.generate_structured()`. No regex or heuristic fallback is present in code; errors raise `LLMStructuredOutputError` cleanly.
* **Deliverables:** `src/agents/query_understanding/`, `tests/test_query_understanding.py`.

---

## Phase 6: Data Query Agent (Text-to-SQL) & Controlled DB Execution

* **Objective:** Build the Data Query Agent that translates structured data intents into valid PostGIS SQL queries targeting observation tables, coupled with a controlled database execution layer.
* **Prerequisites:** Phase 2 schema, Phase 3 validator, Phase 5 Query Understanding Agent.
* **Implementation Tasks:**
  1. Construct system prompt containing PostgreSQL/PostGIS DDL and spatial function usage rules.
  2. Implement SQL generation method consuming `QueryIntent` and mapping physical columns (`platform_number`, `pressure_dbar`, `temperature_c`, `salinity_psu`).
  3. Connect output directly to `Deterministic SQL Validator` (Phase 3).
  4. Implement single-retry loop feeding validator error feedback back to Data Query Agent.
  5. Implement `Controlled Database Execution Layer` that executes validated SQL with `SET statement_timeout = 5000;` and read-only connection credentials.
* **Testing Requirements:** Benchmark against 30 natural language data queries (spatial filtering, pressure ranges, time-series).
* **Exit Criteria:** Text-to-SQL generation produces valid, executable PostGIS SQL for >85% of test cases; zero validator bypasses.
* **Deliverables:** `src/agents/data_query/`, controlled DB execution module, evaluation test suite.

---

## Phase 7/8: Scientific Knowledge & Response Agent (Consolidated RAG, Synthesis & Visuals)

* **Objective:** Build the third primary agent consolidating document retrieval (`pgvector`), grounded factual answer synthesis with inline citations, numerical observation interpretation, and Plotly/Recharts visualization specifications.
* **Prerequisites:** Phase 2 PostgreSQL/pgvector database foundation, Phase 4 LLM abstraction, Phase 6 Data Query Agent & execution layer.
* **Implementation Tasks:**
  1. Ingest official ARGO documentation (User Manual, QC flag manuals) into `argo_doc_embeddings`.
  2. Implement text chunking, metadata enrichment, and vector embedding generation.
  3. Implement internal RAG retriever querying `pgvector` top-k chunks ($k=4$, threshold $T=0.70$).
  4. Implement grounded answer synthesizer attaching explicit inline citations (`[Document Title, Section, Page]`).
  5. Implement result analysis and chart specification generator emitting Plotly/Recharts JSON configs for multi-profile/vertical trend data.
  6. Enforce anti-hallucination guardrail (explicit refusal when topic is outside documentation).
* **Testing Requirements:** Benchmark RAG accuracy on domain questions; evaluate citation precision and chart JSON validity.
* **Exit Criteria:** Factual answers grounded with accurate section citations; valid chart specs generated for multi-level observations; zero hallucinations.
* **Deliverables:** `src/rag/`, `src/agents/scientific_response/`, unit and integration tests.

---

## Phase 9: LangGraph Orchestration (Exactly Three Primary Agents)

* **Objective:** Orchestrate the three primary AI agents and deterministic supporting tools into a stateful LangGraph workflow supporting all 3 query flows.
* **Prerequisites:** Phases 3, 5, 6, 7/8.
* **Implementation Tasks:**
  1. Define graph state schema `FloatChatState`.
  2. Implement routing logic for Flow 1 (Knowledge-Only), Flow 2 (Data-Only), and Flow 3 (Hybrid).
  3. Coordinate handoff: `QueryIntent` $\to$ Data Query Agent $\to$ Validator $\to$ DB Execution Layer $\to$ Scientific Knowledge & Response Agent.
  4. Enforce max-1-retry loop for SQL validation errors.
* **Testing Requirements:** Integration tests verifying graph execution paths for Knowledge-Only, Data-Only, and Hybrid queries.
* **Exit Criteria:** Successful execution of all 3 flows in LangGraph with zero unhandled graph state errors.
* **Deliverables:** `src/orchestration/graph.py`, `src/orchestration/state.py`.

---

## Phase 10: FastAPI AI Service

* **Objective:** Wrap the LangGraph workflow into an independently deployable Python FastAPI service.
* **Prerequisites:** Phase 9 LangGraph Orchestration.
* **Implementation Tasks:**
  1. Create FastAPI application with endpoint routing.
  2. Implement `POST /api/v1/query`: Accepts user query and session ID; returns response payload.
  3. Implement `GET /api/v1/health`: Checks status of PostgreSQL, PostGIS, pgvector, and Ollama provider.
  4. Add CORS middleware and Pydantic request/response models.
* **Testing Requirements:** API integration tests using `httpx` / `TestClient`.
* **Exit Criteria:** FastAPI service running independently, serving requests under 2 seconds latency for local tests.
* **Deliverables:** `src/main.py`, `src/api/routes.py`, `Dockerfile`.

---

## Phase 11: Java Backend Integration (Owned by Another Team Member)

* **Objective:** Integrate Python AI Service with Java Application Backend (Spring Boot) responsible for user auth, sessions, and business logic.
* **Ownership Boundary:** Owned and implemented by another team member. The Python AI service provides the API contract (`/api/v1/query`, `/health`).
* **Integration Tasks (External):**
  1. Build Java Spring Boot REST client service to communicate with Python FastAPI endpoints.
  2. Implement Java DTOs matching FastAPI schemas.
  3. Implement user chat history persistence in Java database.
  4. Implement Java security gateway (JWT auth, rate limiting).
* **Deliverables:** Java Spring Boot integration module (`FloatChatClientService.java`, DTO classes, Controller).

---

## Phase 12: Next.js Frontend Integration (Owned by Another Team Member)

* **Objective:** Build an interactive web interface using Next.js, HTML5/CSS3 vanilla styles, and dynamic charts.
* **Ownership Boundary:** Owned and implemented by another team member. Consumes the Java backend API (or Python AI service directly).
* **Integration Tasks (External):**
  1. Build Next.js UI structure with dark mode theme tokens and glassmorphism UI components.
  2. Build Conversational Interface component supporting markdown rendering and scientific citations.
  3. Build Data Visualization Panel rendering dynamic Plotly/Recharts components and Leaflet/Mapbox interactive maps.
* **Deliverables:** Next.js application codebase (`src/app/`, `src/components/`).

---

## Phase 13: Evaluation and Benchmarking

* **Objective:** Perform systematic quantitative evaluation across retrieval accuracy, Text-to-SQL correctness, execution latency, and security safety.
* **Prerequisites:** Phase 12 completion (or Phase 10 complete test harness).
* **Implementation Tasks:**
  1. Run 75 benchmark queries across Knowledge, Data, and Hybrid categories.
  2. Benchmark Text-to-SQL execution accuracy and RAG Faithfulness score.
  3. Measure latency breakdown per node.
  4. Validate SQL security containment under deliberate injection stress tests.
* **Testing Requirements:** Automated evaluation harness reporting quantitative accuracy percentages and latency percentiles.
* **Exit Criteria:** System achieves >85% Text-to-SQL accuracy, >90% RAG grounding accuracy, 100% SQL security pass rate.
* **Deliverables:** `evaluation/benchmark_suite.py`, `evaluation/results_report.md`.

---

## Phase 14: Deployment, Demonstration and Final Optimization

* **Objective:** Package FloatChat system with Docker Compose, prepare demonstration workflows, finalize documentation, and optimize system performance.
* **Prerequisites:** Phase 13 evaluation complete.
* **Implementation Tasks:**
  1. Finalize single `docker-compose.yml` orchestrating PostgreSQL/PostGIS, Python AI Service, Java Backend, and Next.js Frontend.
  2. Optimize database indexes and memory allocations.
  3. Package project documentation, user manual, and setup guides for B.Tech CSE thesis submission.
* **Testing Requirements:** Clean deployment from scratch (`docker-compose up --build`) on a fresh environment.
* **Exit Criteria:** System starts cleanly via Docker Compose and executes live demonstration queries flawlessly.
* **Deliverables:** Production `docker-compose.yml`, User Guide, Thesis Documentation, Demonstration Video.
