# FloatChat: Project Requirements Specification

**Document Version:** 1.0.0  
**Phase:** Phase 0 (Architecture & Specification)  
**Status:** Approved Specification  

---

## 1. Problem Statement

Autonomous ARGO floats collect vast amounts of oceanographic data across the world's oceans, recording critical vertical profile measurements such as water temperature (`TEMP`), salinity (`PSAL`), and pressure (`PRES`) at varying geographic coordinates (`latitude`, `longitude`) and timestamps (`time`). 

However, extracting insights from this spatial-temporal data presents significant hurdles:
1. **Complex Data Formats:** Raw observation records are stored in multi-dimensional binary NetCDF (`.nc`) files, requiring specialized scientific programming libraries (`netCDF4`, `xarray`) to extract and query.
2. **Scattered Scientific Context:** Understanding measurement methodology, float mechanics, quality control standards, and sensor specs requires searching through extensive oceanographic PDF user manuals and technical reports.
3. **High Barrier to Entry:** Non-technical marine researchers, environmental policy analysts, and students struggle to formulate complex spatial-temporal queries or cross-reference numerical profiles with domain documentation.

---

## 2. Proposed Solution

**FloatChat** is a conversational AI and spatial analytics platform designed for querying Indian Ocean ARGO float data and scientific domain documentation. 

FloatChat unifies two distinct intelligence streams:
- **Numerical & Spatial Data Querying:** Translates natural language requests into deterministic PostGIS spatial SQL queries over structured PostgreSQL observation tables.
- **Domain Knowledge Retrieval:** Grounded Retrieval-Augmented Generation (RAG) over authoritative ARGO scientific manuals using `pgvector`.

By employing a **LangGraph-orchestrated multi-agent architecture** combined with a **deterministic SQL security validator**, FloatChat allows users to converse with oceanographic data safely, accurately, and intuitively.

---

## 3. System Objectives

- **Natural Language Accessibility:** Allow users to query oceanographic data and documentation using plain English.
- **Strict Accuracy & Grounding:** Prevent LLM hallucinations by grounding factual scientific answers in authoritative documents and executing exact SQL queries over numerical observations.
- **Deterministic Security:** Enforce 100% read-only SQL validation prior to database execution using AST parsing.
- **Low Latency Orchestration:** Route knowledge-only queries directly to the RAG path to avoid unnecessary SQL generation or database load.
- **Modularity & Feasibility:** Built as a clean service-oriented system achievable for a final-year B.Tech CSE project.

---

## 4. Target Users

- **Oceanographers & Marine Scientists:** Seeking rapid spatial-temporal data filtering and scientific documentation lookups without writing custom scripts.
- **Environmental Policy Makers:** Needing natural language summaries of regional ocean parameter trends.
- **Students & Researchers:** Learning about ARGO float operations, sensor physics, and regional ocean dynamics.

---

## 5. Functional Requirements

| ID | Module | Requirement Description |
| :--- | :--- | :--- |
| **FR-01** | Query Intent Understanding | System must classify user queries into `KNOWLEDGE_ONLY`, `DATA_ONLY`, or `HYBRID` intents. |
| **FR-02** | Entity & Slot Extraction | System must extract spatial bounds, temporal ranges, WMO float IDs, pressure/depth ranges, and physical variables from user queries. |
| **FR-03** | Text-to-SQL Translation | System must translate natural language data queries into valid PostgreSQL / PostGIS SQL queries targeting physical observation tables. |
| **FR-04** | Deterministic SQL Validation | System must parse generated SQL using AST validation, enforcing `SELECT`-only execution, table/column allowlisting, and safety `LIMIT` injection. |
| **FR-05** | Scientific Knowledge & Response | Third agent must retrieve domain document chunks from `pgvector` and synthesize grounded answers with explicit document citations. |
| **FR-06** | Result Analysis & Visualization | Third agent must conditionally interpret database results, compute statistical summaries, and emit chart visualization specs. |
| **FR-07** | Multi-Provider LLM Abstraction | System must support local Ollama execution (primary) and cloud providers (Gemini, pluggable fallback) via a unified interface. |

---

## 6. Non-Functional Requirements

- **NFR-01 Performance & Latency:** Knowledge-only RAG queries must return within 2 seconds on local hardware.
- **NFR-02 Deterministic Security:** 100% rejection rate for any SQL query attempting data modification (`INSERT`, `UPDATE`, `DELETE`, `DROP`, `ALTER`).
- **NFR-03 Reliability:** Automated retry mechanism (max 1 retry) for SQL syntax corrections guided by deterministic parser errors.
- **NFR-04 Extensibility:** Provider-agnostic LLM design allowing seamless model swapping via environment configuration.
- **NFR-05 Maintainability:** Clean separation between deterministic software components and probabilistic AI agents.

---

## 7. V1 System Scope

- **Dataset:** Indian Ocean ARGO Float NetCDF dataset (`Indian_ARGO_Floats_0f9d_516d_c560_U1788882326310.nc`).
- **Observed Variables:** `PLATFORM_NUMBER`, `time`, `latitude`, `longitude`, `PRES` (pressure), `TEMP` (water temperature at observation pressure), `PSAL` (salinity).
- **AI Architecture:** Exactly 3 Primary AI Agents:
  1. Query Understanding Agent
  2. Data Query Agent (Text-to-SQL)
  3. Scientific Knowledge & Response Agent (integrating RAG retrieval, grounded answer synthesis, citations, and visualization specifications)
- **Supporting Components (Non-Agents):** LangGraph workflow orchestrator, Deterministic SQL Validator, Controlled Database Execution Layer, PostgreSQL/PostGIS, pgvector, and FastAPI service.
- **Project Implementation Boundary:** The core project scope covers the Python AI Service (Phases 0–10, 13–14). The Java/Spring Boot backend (Phase 11) and Next.js frontend (Phase 12) are owned and implemented by another team member.
- **Database Infrastructure:** Single PostgreSQL instance with PostGIS and `pgvector` extensions (containerized via Docker Compose).
- **Orchestration:** Stateful LangGraph workflow supporting 3 distinct routing paths.

---

## 8. Limitations & Future Scope

### V1 Limitations
- **Read-Only Operations:** System does not support user data uploads or profile mutations in V1.
- **Regional Focus:** Dataset limited to Indian Ocean ARGO float observations available in the local development NetCDF file.
- **No Unverified QC Assumptions:** Quality Control variables are not assumed to exist prior to Phase 1 data pipeline verification.

### Future Scope
- Ingestion of multi-ocean global ARGO datasets (Atlantic, Pacific, Southern Ocean).
- Automated live NetCDF ingestion streams from Global Data Assembly Centres (GDAC).
- Advanced predictive ocean modeling and spatial anomaly forecasting.

---

## 9. Smart India Hackathon (SIH) Relevance

FloatChat aligns directly with SIH themes focused on **Oceanographic AI Analytics & Marine Data Accessibility**:
- Demonstrates advanced AI orchestration over complex geospatial scientific data.
- Bridges the gap between complex binary NetCDF observations and intuitive natural language interaction.
- Adheres to rigorous engineering standards: deterministic security, zero hallucination on numerical observations, and low-latency conditional routing.
