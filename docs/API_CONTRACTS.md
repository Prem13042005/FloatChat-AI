# FloatChat: API Contracts & Interface Definitions

**Document Version:** 1.0.0  
**Phase:** Phase 0 (Architecture & Specification)  
**Status:** Approved Specification  

---

## 1. System Communication Architecture

FloatChat enforces clean, minimal REST API boundaries across system layers:

```
[ Next.js Frontend ] <--- REST / HTTPS ---> [ Java Application Backend ] <--- REST / HTTP ---> [ Python AI Service ]
```

### Decoupling Requirement & Team Ownership
- **Python AI Service Responsibility**: The Python AI layer team is solely responsible for implementing the Python AI Service (FastAPI, exactly 3 primary AI agents, scientific RAG, LangGraph orchestration, controlled DB execution, and SQL validation).
- **External Integration**: The Java Application Backend (Spring Boot) and Next.js Frontend are owned and implemented by another team member. The Python AI service exposes clean REST endpoints conforming to this contract. During AI development phases (Phases 1–10), all endpoints are tested directly via Swagger UI or automated tests without requiring the Java backend or frontend.

---

## 2. Python AI Service Endpoints (FastAPI)

Base URL: `http://localhost:8000/api/v1`

### 2.1 Endpoint: Submit Query
* **Method:** `POST /query`
* **Description:** Accepts natural language query, runs LangGraph orchestrator, and returns structured answer, citations, SQL metrics, and chart specs.
* **Request Payload (`application/json`):**
  ```json
  {
    "session_id": "sess-12345",
    "query": "Show temperature profiles in the Arabian Sea with temperature > 25°C"
  }
  ```
* **Response Payload (`application/json`):**
  ```json
  {
    "session_id": "sess-12345",
    "intent_type": "DATA_ONLY",
    "answer": "Found 42 profiles matching your criteria in the Arabian Sea.",
    "citations": [],
    "sql_meta": {
      "generated_sql": "SELECT p.platform_number, m.pressure_dbar, m.temperature_c FROM argo_profiles p JOIN argo_measurements m ON p.profile_id = m.profile_id WHERE ST_Within(p.location_geom, ST_MakeEnvelope(60.0, 10.0, 75.0, 25.0, 4326)) AND m.temperature_c > 25.0 LIMIT 100;",
      "execution_time_ms": 42.5
    },
    "visualization_spec": {
      "chart_type": "line",
      "x_axis": "temperature_c",
      "y_axis": "pressure_dbar",
      "title": "Arabian Sea Temperature Profile (>25°C)"
    }
  }
  ```

### 2.2 Endpoint: Health Check
* **Method:** `GET /health`
* **Description:** Returns operational status of Python AI Service, PostgreSQL connection, PostGIS, `pgvector`, and Ollama LLM connectivity.
* **Response Payload (`application/json`):**
  ```json
  {
    "status": "healthy",
    "database": "connected",
    "postgis": "available",
    "pgvector": "available",
    "llm_provider": "ollama (llama3)",
    "timestamp": "2026-09-11T18:14:00Z"
  }
  ```

---

## 3. Java Backend Gateway Endpoints (Spring Boot)

Base URL: `http://localhost:8080/api/v1`

### 3.1 Endpoint: User Chat Proxy
* **Method:** `POST /chat`
* **Headers:** `Authorization: Bearer <JWT_TOKEN>`
* **Request Payload (`application/json`):**
  ```json
  {
    "conversation_id": "conv-987",
    "message": "Explain how salinity sensors work on ARGO floats."
  }
  ```
* **Response Payload:** Proxies the Python AI Service response, persisting conversation history in Java database.

---

## 4. API Error Response Standard

All FloatChat services adhere to a standardized HTTP error JSON schema:

```json
{
  "error_code": "SQL_VALIDATION_FAILED",
  "message": "Generated query violated read-only constraint.",
  "details": "Query contained disallowed token: DROP",
  "timestamp": "2026-09-11T18:14:00Z"
}
```
