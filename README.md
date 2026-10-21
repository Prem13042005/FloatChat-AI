# FloatChat: AI-Powered Conversational & Spatial Analytics for ARGO Float Observations

FloatChat is an open-source, conversational AI and spatial analytics platform designed for querying Indian Ocean ARGO float observation data and scientific domain documentation.

---

## 1. Problem & Solution Overview

### The Problem
Autonomous ARGO floats collect vast amounts of spatial-temporal oceanographic data across global oceans, recording physical profile measurements such as ocean pressure (`PRES`), water temperature (`TEMP`), and salinity (`PSAL`). However, accessing this data requires specialized scientific programming libraries (`netCDF4`, `xarray`) to read multi-dimensional binary NetCDF files. Furthermore, domain knowledge regarding CTD sensor mechanics, measurement standards, and quality control flags is scattered across extensive scientific manuals.

### The Solution
FloatChat unifies natural language processing with spatial database querying:
- **Spatial-Temporal Data Queries:** Translates plain English queries into deterministic PostGIS spatial SQL queries over structured PostgreSQL observation tables.
- **Scientific RAG Knowledge Grounding:** Retrieves domain documentation chunks from `pgvector` and synthesizes factual answers with explicit section citations.
- **Deterministic SQL Security:** Validates all generated SQL using a non-LLM Abstract Syntax Tree (AST) parser prior to database execution.

---

## 2. Technology Stack

- **AI Orchestration:** Python 3.10+, LangGraph, FastAPI
- **LLM Abstraction:** Ollama (Local: Llama 3 / Mistral) + Gemini (Cloud: Google GenAI SDK)
- **Database & Vectors:** PostgreSQL 15+ with PostGIS & `pgvector` extensions
- **SQL Parser & Security:** `sqlglot` (Non-LLM AST Validation Engine)
- **Enterprise Backend:** Java 17+ Spring Boot (Phase 11 Integration)
- **Frontend:** Next.js (React), HTML5/CSS3 Vanilla Styles, Plotly.js / Recharts, Leaflet/Mapbox

---

## 3. The 3 Canonical Primary AI Agents

FloatChat V1 incorporates **EXACTLY THREE PRIMARY AI AGENTS**:

1. **Query Understanding Agent:** Classifies user query intent (`KNOWLEDGE_ONLY`, `DATA_ONLY`, `HYBRID`) and extracts spatial-temporal slot parameters into a validated `QueryIntent`.
2. **Data Query Agent (Text-to-SQL):** Translates structured data intents into candidate PostGIS SQL queries targeting physical observation tables, subject to deterministic validation before execution.
3. **Scientific Knowledge & Response Agent:** Consolidates scientific domain RAG retrieval (via `pgvector`), grounded factual answer synthesis with citations, result interpretation over database query outputs, and validated visualization specification generation.

*Note: All other components (LangGraph orchestration, deterministic SQL validation, controlled database execution layer, document ingestion, FastAPI service, Java backend, and Next.js frontend) are supporting software components, NOT agents.*

---

## 4. LangGraph Workflow Routing (3 Flows)

```
A. KNOWLEDGE-ONLY FLOW
   User -> Query Understanding Agent -> Scientific Knowledge & Response Agent (Internal RAG) -> Response

B. DATA-ONLY FLOW
   User -> Query Understanding Agent -> Data Query Agent -> Deterministic SQL Validator -> Controlled DB Execution Layer -> PostgreSQL/PostGIS -> Scientific Knowledge & Response Agent (Synthesis & Visuals) -> Response

C. HYBRID FLOW
   User -> Query Understanding Agent -> [Data Query Agent -> Validator -> Controlled DB Execution Layer] + [Scientific Knowledge & Response Agent (RAG Context + Result Synthesis + Visuals)] -> Response
```

---

## 5. Development Roadmap Summary

- **Phase 0:** Architecture & Engineering Specification (Complete)
- **Phase 1:** ARGO Data Ingestion & Preprocessing (Complete)
  - **Phase 1.1:** Dataset Forensics (Complete)
  - **Phase 1.2:** Normalization Specification (Complete)
  - **Phase 1.3:** Deterministic Ingestion Pipeline (Complete)
- **Phase 2:** PostgreSQL + PostGIS Database Foundation (Complete)
- **Phase 3:** Deterministic SQL Validation & Security Gate (Phase 3.1 Complete)
- **Phase 4:** LLM Provider Abstraction & Ollama Integration (Complete)
- **Phase 5:** Query Understanding Agent (Complete — 22 Unit Tests Passing)
- **Phase 6:** Data Query Agent (Text-to-SQL) & Controlled DB Execution
- **Phase 7/8:** Scientific Knowledge & Response Agent (Consolidated RAG, Synthesis & Visualization Specs)
- **Phase 9:** LangGraph Orchestration (3 Agents)
- **Phase 10:** FastAPI AI Service
- **Phase 11:** Java Backend Integration (Owned & Implemented by Another Team Member)
- **Phase 12:** Next.js Frontend Integration (Owned & Implemented by Another Team Member)
- **Phase 13:** System Evaluation & Benchmarking
- **Phase 14:** Production Deployment & Demonstration

*Project Scope Boundary: Our implementation responsibility is the Python AI layer (FastAPI service, 3 AI agents, deterministic SQL validator, controlled DB execution, RAG indexing, and evaluation). The Java/Spring Boot backend and Next.js frontend are owned and implemented by another team member.*

---

## 6. Repository Structure

```
FLOATCHAT/
├── data/
│   └── processed/
│       ├── floats.parquet
│       ├── profiles.parquet
│       ├── measurements.parquet
│       └── validation_report.json
├── docs/
│   ├── PROJECT_REQUIREMENTS.md
│   ├── SYSTEM_ARCHITECTURE.md
│   ├── AI_ARCHITECTURE.md
│   ├── AGENT_SPECIFICATIONS.md
│   ├── DATABASE_DESIGN.md
│   ├── RAG_SPECIFICATION.md
│   ├── QUERY_TAXONOMY.md
│   ├── API_CONTRACTS.md
│   ├── SECURITY_DESIGN.md
│   ├── EVALUATION_PLAN.md
│   ├── DEVELOPMENT_ROADMAP.md
│   ├── DECISIONS.md
│   ├── PHASE_1_DATASET_REPORT.md
│   ├── PHASE_1_NORMALIZATION_SPEC.md
│   ├── PHASE_1_INGESTION.md
│   ├── PHASE_1_VALIDATION_REPORT.md
│   ├── PHASE_2_DATABASE_FOUNDATION.md
│   ├── PHASE_2_2_DATA_INGESTION.md
│   ├── PHASE_3_1_SQL_VALIDATOR.md
│   ├── PHASE_4_LLM_PROVIDER.md
│   ├── PHASE_5_QUERY_UNDERSTANDING.md
│   └── PRE_PHASE_4_CODEBASE_AUDIT.md
├── scripts/
│   ├── init-db.sql
│   ├── inspect_argo_dataset.py
│   ├── load_parquet_to_postgis.py
│   ├── normalize_argo_dataset.py
│   ├── setup_db_local.py
│   └── validate_argo_data.py
├── src/
│   ├── config.py
│   ├── agents/
│   │   ├── __init__.py
│   │   └── query_understanding/
│   │       ├── __init__.py
│   │       ├── agent.py
│   │       ├── models.py
│   │       └── prompts.py
│   ├── llm/
│   │   ├── __init__.py
│   │   ├── base.py
│   │   ├── exceptions.py
│   │   ├── gemini_provider.py
│   │   └── ollama_provider.py
│   └── security/
│       └── sql_validator.py
├── tests/
│   ├── test_database_ingestion.py
│   ├── test_database_schema.py
│   ├── test_llm_provider.py
│   ├── test_pipeline.py
│   ├── test_query_understanding.py
│   ├── test_sql_validator.py
│   └── test_validation.py
├── Indian_ARGO_Floats_0f9d_516d_c560_U1788882326310.nc  (Development NetCDF Dataset)
├── docker-compose.yml
├── .env.example
├── .gitignore
└── README.md
```

---

## 7. Current Project Status

- **Phase 0 Documentation:** Fully authored and aligned with the 3-agent architecture.
- **Phase 1 Data Ingestion Pipeline:** Fully executed and validated. Processed Parquet files and validation report generated in `data/processed/`.
- **Phase 2 PostgreSQL + PostGIS Database Foundation:** Fully implemented, schema DDL applied, and Parquet data loaded & reconciled (17,339 measurements across 21 floats).
- **Phase 3.1 Deterministic SQL Validator Core:** Fully implemented, tested (37 unit tests), and documented.
- **Phase 4 LLM Provider Abstraction & Ollama Integration:** Fully implemented, tested (15 provider unit tests), and documented with `qwen2.5:1.5b-instruct` local default.
- **Phase 5 Query Understanding Agent:** Fully implemented and tested (22 unit tests passing).
- **Phase 6 Data Query Agent & Controlled DB Execution:** Next step.
