# FloatChat: Architectural Decision Records (ADRs)

**Document Version:** 1.0.0  
**Phase:** Phase 0 (Architecture & Specification)  
**Status:** Approved Specification  

---

## ADR-01: Four AI Agents Baseline (SUPERSEDED)

* **Status:** Superseded by ADR-07
* **Context:** Preliminary Phase 0 architecture proposed four separate AI agents (Query Understanding, Text-to-SQL, Scientific RAG, and Result Analysis).
* **Superseded Reason:** Separating RAG document synthesis from numerical result analysis introduced unnecessary serialization, orchestration latency, and graph complexity. Result interpretation and RAG context grounding belong naturally within a single response agent.

---

## ADR-02: Local Ollama First, Gemini Pluggable Cloud Provider

* **Status:** Approved
* **Context:** FloatChat must support offline, zero-cost, private local development while remaining capable of upgrading to state-of-the-art cloud LLMs for production deployment.
* **Decision:** Adopt a provider-agnostic `BaseLLMProvider` abstraction. Implement `OllamaProvider` (running `llama3`, `mistral`, or `qwen2.5` locally) as the primary default provider. Implement `GeminiProvider` (Google GenAI SDK) as a pluggable cloud provider selectable via `.env`.
* **Consequences:** Developers can run the entire system locally without API key dependencies. Agents depend strictly on the abstraction.

---

## ADR-03: Single Database Engine (PostgreSQL + PostGIS + pgvector)

* **Status:** Approved
* **Context:** Storing spatial-temporal observation profiles alongside document vector embeddings often leads developers to introduce multiple database servers (e.g., PostgreSQL + ChromaDB/Pinecone).
* **Decision:** Standardize on a **single unified PostgreSQL instance** with the `postgis` extension for spatial-temporal oceanographic data and the `vector` (`pgvector`) extension for document chunk embeddings.
* **Consequences:** Eliminates multi-database synchronization overhead, simplifies deployment via Docker, and keeps system architecture achievable for a B.Tech CSE project. ChromaDB or secondary vector databases are explicitly excluded.

---

## ADR-04: Deterministic AST-Based SQL Security Barrier

* **Status:** Approved
* **Context:** Relying on LLMs to enforce SQL safety via prompt instructions (e.g., "do not modify data") is insecure and vulnerable to prompt injection attacks.
* **Decision:** Implement a non-LLM Python AST parser using `sqlglot` (`Deterministic SQL Validator`) that intercepts every generated SQL query. Enforce strict `SELECT`-only execution, table/column allowlists, forced `LIMIT` clauses, and statement timeouts.
* **Consequences:** 100% deterministic security containment against SQL injections and unauthorized database write/drop attempts.

---

## ADR-05: Decoupled Python AI Service with Java Integration in Phase 11

* **Status:** Approved
* **Context:** The team incorporates a Java full-stack developer, but forcing Python AI development to depend on Java service startup during early phases slows down iteration.
* **Decision:** Structure the system so the Python AI Service (FastAPI + LangGraph) is fully standalone and interacts directly with PostgreSQL during Phases 1–10. In Phase 11, the Java Application Backend (Spring Boot) integrates with the Python service via REST APIs (`/api/v1/query`).
* **Consequences:** Frictionless, independent AI agent development without Java dependencies in early phases; clean enterprise application boundary in later phases. Zero business logic duplication.

---

## ADR-06: 3-Flow LangGraph Workflow with Consolidated Response Synthesis

* **Status:** Approved
* **Context:** Knowledge-only queries do not need SQL generation or database execution, and simple data queries do not require complex external scientific explanations.
* **Decision:** Use LangGraph to explicitly support 3 routing flows (`KNOWLEDGE_ONLY`, `DATA_ONLY`, `HYBRID`). For hybrid queries, the Data Query Agent and the third agent's RAG retrieval are orchestrated cleanly. The **Scientific Knowledge & Response Agent** synthesizes grounded explanations and visualization specifications over database results.
* **Consequences:** Significantly reduces average latency, avoids unnecessary database queries, and minimizes LLM token consumption.

---

## ADR-07: Consolidation into Exactly Three Primary AI Agents

* **Status:** Approved (Supersedes ADR-01)
* **Context:** FloatChat requires an implementable, testable, and demonstrable architecture without agent sprawl or excessive orchestration hops.
* **Decision:** FloatChat contains **EXACTLY THREE PRIMARY AI AGENTS**:
  1. **Query Understanding Agent:** Parses user questions into a strongly-typed `QueryIntent` Pydantic model.
  2. **Data Query Agent (Text-to-SQL):** Translates structured intents into candidate SQL queries targeting physical observation schema.
  3. **Scientific Knowledge & Response Agent:** Consolidates scientific domain RAG retrieval (via `pgvector`), grounded factual answer synthesis with citations, result interpretation over database query outputs, and validated visualization specification generation.
* **Consequences:** LangGraph is strictly an orchestration framework, not an agent. The SQL validator, controlled database execution layer, API, frontend, LLM providers, and data ingestion pipeline are supporting components, NOT agents. No autonomous sub-agents or fourth primary agents exist.

---

## ADR-08: Separation of Deterministic SQL Validation and Controlled Database Execution

* **Status:** Approved
* **Context:** Static validation must not be confused with physical database runtime enforcement. The SQL validator does not connect to the database or set session parameters.
* **Decision:** Enforce a strict architectural boundary:
  - `DeterministicSQLValidator` (`src/security/sql_validator.py`): Non-LLM static AST analysis, table/column allowlisting, single-statement enforcement, and LIMIT transformation.
  - `Controlled Database Execution Layer` (Phase 6): Manages database transactions, read-only session roles, connection pooling, and physical statement timeout enforcement (`SET statement_timeout = 5000;`).
* **Consequences:** Eliminates false security claims; guarantees statement timeouts and connection constraints are actively enforced at the database connection level.
