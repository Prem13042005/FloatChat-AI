# FloatChat AI 🌊
### Agentic Conversational Platform for Oceanographic Data Discovery & Analysis

[![Architecture](https://img.shields.io/badge/Architecture-3--Tier%20Microservices-blue.svg)](#-system-architecture)
[![Frontend](https://img.shields.io/badge/Frontend-React%2018%20%7C%20Vite-61dafb.svg)](#8-technology-stack)
[![Backend](https://img.shields.io/badge/Backend-Spring%20Boot%203.3-6db33f.svg)](#8-technology-stack)
[![AI Engine](https://img.shields.io/badge/AI%20Engine-FastAPI%20%7C%20LangGraph-009688.svg)](#8-technology-stack)
[![Database](https://img.shields.io/badge/Database-PostgreSQL%2015%20%7C%20PostGIS%20%7C%20pgvector-336791.svg)](#9-database-architecture)
[![Local LLM](https://img.shields.io/badge/Inference-Ollama%20(qwen2.5%20%7C%20nomic--embed--text)-black.svg)](#8-technology-stack)

FloatChat AI is an enterprise-grade, agentic conversational platform that democratizes access to oceanographic observation data collected by the international **ARGO float program**. By pairing specialized multi-agent LangGraph workflows with deterministic AST-based SQL validation, vector-grounded retrieval-augmented generation (RAG), and interactive multi-modal visualizations, FloatChat enables marine scientists, oceanographers, students, and maritime analysts to explore, analyze, and visualize high-dimensional ocean data using natural language.

Instead of writing complex PostGIS spatial SQL or parsing multidimensional netCDF archives manually, users interact conversationally to extract depth profiles, analyze temperature/salinity distributions, investigate spatio-temporal trends, and explore oceanographic literature.

---

## Table of Contents

1. [Project Overview](#1-project-overview)
2. [Problem Statement](#2-problem-statement)
3. [Project Objectives](#3-project-objectives)
4. [Key Features](#4-key-features)
5. [System Architecture](#5-system-architecture)
6. [Three-Agent LangGraph Architecture](#6-three-agent-langgraph-architecture)
7. [Agent Workflows: KNOWLEDGE_ONLY, DATA_ONLY, and HYBRID](#7-agent-workflows)
8. [Technology Stack](#8-technology-stack)
9. [Database Architecture](#9-database-architecture)
10. [ARGO Dataset Information](#10-argo-dataset-information)
11. [Repository Structure](#11-repository-structure)
12. [Prerequisites & Installation](#12-prerequisites--installation)
13. [Environment Configuration](#13-environment-configuration)
14. [Docker Database Startup](#14-docker-database-startup)
15. [Python AI Service Startup](#15-python-ai-service-startup)
16. [Java Spring Boot Backend Startup](#16-java-spring-boot-backend-startup)
17. [React / Vite Frontend Startup](#17-react--vite-frontend-startup)
18. [API Endpoints](#18-api-endpoints)
19. [Example Queries for Demonstration](#19-example-queries-for-demonstration)
20. [Testing Instructions](#20-testing-instructions)
21. [Known Limitations](#21-known-limitations)
22. [Future Scope](#22-future-scope)
23. [Team & Acknowledgements](#23-team--acknowledgements)

---

## 1. Project Overview

FloatChat AI bridges the gap between massive, heterogeneous oceanographic datasets and domain practitioners. Built on a resilient three-tier microservice architecture (React 18 + Vite frontend, Spring Boot 3 enterprise application backend, and FastAPI + LangGraph AI engine), the system translates conversational questions into deterministic, schema-safe PostGIS queries, executes semantic vector searches over peer-reviewed oceanographic documentation, and renders reactive scientific charts (vertical depth profiles, T-S scatter plots, histograms, and temporal trends).

---

## 2. Problem Statement

ARGO floats drift across the world's oceans, descending to depths of 2,000 meters and ascending to transmit profile measurements of temperature, salinity, and pressure via satellite. While this global observation network produces indispensable climate and marine data:

- **Complex Data Formats:** Data is traditionally archived in multi-dimensional netCDF files or complex normalized relational schemas with spatial geometries (`Point`, `Polygon`), requiring specialized programming skills in Python (`xarray`, `netCDF4`) or advanced SQL (`ST_DWithin`, `ST_MakePoint`).
- **Domain Silos:** Querying observational records requires simultaneously consulting domain literature (e.g., understanding mixed-layer dynamics, haloclines, thermoclines, and water mass characteristics) alongside raw numbers.
- **Query Vulnerability & Hallucination:** Naive LLM-to-SQL solutions generate hallucinated schema references, cross-product table joins, or SQL injection vectors, and frequently generate incorrect statistical aggregations.
- **Visualization Rigidity:** Standard chat interfaces output flat markdown tables rather than scientific charts configured for oceanographic conventions (e.g., inverting vertical pressure axes so surface waters appear at the top).

FloatChat AI resolves these challenges through verified agentic workflows, deterministic AST query refinement, strict database access controls, and dynamic visualization synthesis.

---

## 3. Project Objectives

- **Natural Language Discovery:** Enable researchers to query Indian Ocean ARGO float observations and ocean physics conversationally without prior SQL or netCDF knowledge.
- **Deterministic SQL Generation & Security:** Guarantee 100% read-only SQL execution via AST parsing (`sqlglot`), schema whitelisting, automatic join injection, hard statement timeouts, and a dedicated unprivileged database user (`floatchat_ai_user`).
- **Grounded Scientific Reasoning:** Combine observational data with vector-embedded literature chunks (`pgvector` + `nomic-embed-text`) to eliminate LLM hallucinations.
- **Dynamic Oceanographic Visualizations:** Automatically infer and render appropriate chart specifications (vertical profiles, temperature/salinity distributions, T-S diagrams, time series) with oceanographic axis conventions.
- **Enterprise Resiliency:** Provide JWT authentication, conversation history persistence, role-based dashboards, request rate limiting, and cooperative cancellation tokens to terminate orphaned background inferences cleanly.

---

## 4. Key Features

- **Agentic Multi-Model Orchestration:** Three specialized LangGraph agents coordinate natural language understanding, database querying, and scientific synthesis.
- **Deterministic SQL Validator & Auto-Joiner:** Validates generated SQL syntax against an abstract syntax tree, enforces `SELECT`-only permissions, whitelists tables/columns, automatically joins `argo_measurements` with `argo_profiles` when measurement columns are queried, and injects safe limits.
- **Vector-Grounded Oceanographic RAG:** Cosine similarity vector search over curated oceanographic documentation indexed in PostgreSQL via `pgvector` HNSW indexes.
- **Dynamic Visualization Engine:** Intelligently matches query intent and data shapes to generate vertical depth profiles, histograms, scatter plots, and time-series charts.
- **Cooperative Cancellation Tokens:** Thread-safe tokens allow HTTP client timeouts or disconnections to cancel long-running Ollama inference workflows immediately, freeing CPU concurrency slots.
- **Enterprise Spring Boot Tier:** Robust token-based authentication, user role hierarchy (Admin, Scientist, Analyst), conversation session management, in-memory rate limiting, and persistent query auditing.
- **Responsive React 18 UI:** Clean marine-themed UI featuring interactive Chart.js visualizations, chat history sidebar, scientific citations drawer, and real-time system health metrics.

---

## 5. System Architecture

```mermaid
flowchart TD
    subgraph Client_Tier ["Client Tier"]
        UI["React 18 + Vite SPA<br/>(Port 5173)"]
    end

    subgraph Backend_Tier ["Application Backend Tier (Spring Boot 3.3)"]
        GW["REST API Gateway & Security<br/>(Port 8080)"]
        AUTH["JWT Auth & Rate Limiting"]
        PERSIST["Conversation & History Service"]
        AI_CLI["AI Service HTTP Client<br/>(with Timeout & Error Handling)"]
    end

    subgraph AI_Tier ["AI Engine Tier (FastAPI + LangGraph)"]
        API["FastAPI AI Service<br/>(Port 8000)"]
        ORCH["LangGraph Orchestrator<br/>(CancellationToken Support)"]
        Q_AGENT["1. Query Understanding Agent<br/>(Intent, Gazetteer & Routing)"]
        D_AGENT["2. Data Query Agent<br/>(Schema-Aware SQL Generation)"]
        R_AGENT["3. Scientific Response Agent<br/>(Synthesis & Visualization Spec)"]
        VAL["Deterministic SQL AST Validator<br/>(sqlglot Whitelisting & Auto-Join)"]
    end

    subgraph Inference_Tier ["Local Inference (Ollama)"]
        LLM["qwen2.5:1.5b-instruct<br/>(Local CPU Inference)"]
        EMBED["nomic-embed-text<br/>(768-dim Embeddings)"]
    end

    subgraph Data_Tier ["Data Tier (PostgreSQL 15 + PostGIS + pgvector)"]
        APP_DB[("Application DB<br/>users, query_history, roles")]
        ARGO_DB[("ARGO Relational DB<br/>floats, profiles, measurements")]
        VEC_DB[("Vector Store (pgvector)<br/>argo_knowledge_chunks")]
    end

    UI <-->|HTTP / JSON / JWT| GW
    GW --> AUTH
    GW --> PERSIST
    PERSIST <--> APP_DB
    GW --> AI_CLI
    AI_CLI <-->|HTTP POST /api/v1/chat| API

    API --> ORCH
    ORCH --> Q_AGENT
    Q_AGENT <--> LLM
    Q_AGENT -->|DATA_ONLY / HYBRID| D_AGENT
    Q_AGENT -->|KNOWLEDGE_ONLY / HYBRID| VEC_DB

    D_AGENT <--> LLM
    D_AGENT --> VAL
    VAL -->|Read-Only SQL (floatchat_ai_user)| ARGO_DB

    D_AGENT --> R_AGENT
    VEC_DB --> R_AGENT
    R_AGENT <--> LLM
    R_AGENT --> API
```

---

## 6. Three-Agent LangGraph Architecture

FloatChat AI strictly coordinates **three specialized agents** within a LangGraph state graph:

```
[User Question]
       │
       ▼
┌─────────────────────────────────┐
│ 1. QueryUnderstandingAgent      │ ── Extracts temporal, spatial, float IDs & parameters
└─────────────────────────────────┘ ── Resolves geographic names via Indian Ocean Gazetteer
       │                            ── Determines workflow: KNOWLEDGE_ONLY | DATA_ONLY | HYBRID
       ├───────────────────────────────┬───────────────────────────────┐
       │ (DATA_ONLY)                   │ (HYBRID - Parallel)           │ (KNOWLEDGE_ONLY)
       ▼                               ▼                               │
┌──────────────────────────────┐ ┌──────────────────────────────┐      │
│ 2. DataQueryAgent            │ │ 2. DataQueryAgent            │      │
│  - SQL generation (few-shot) │ │  + Vector RAG Retrieval      │      │
│  - AST validation (sqlglot)  │ └──────────────────────────────┘      │
│  - Auto-join & Read-only DB  │               │                       │
└──────────────────────────────┘               │                       │
       │                                       │                       │
       └───────────────────────────────┬───────┴───────────────────────┘
                                       │
                                       ▼
┌───────────────────────────────────────────────────────────────────────┐
│ 3. ScientificResponseAgent                                            │
│  - Synthesizes tabular observation data and/or vector context chunks  │
│  - Computes deterministic statistics (sample size, averages, ranges)  │
│  - Emits structured citations & oceanographic visualization spec      │
└───────────────────────────────────────────────────────────────────────┘
                                       │
                                       ▼
                      [Structured Response JSON]
```

### 1. `QueryUnderstandingAgent`
- **Responsibility:** Parses user questions into structured intent parameters.
- **Gazetteer Matching:** Includes an Indian Ocean Gazetteer mapping natural names (e.g., *"Arabian Sea"*, *"Bay of Bengal"*, *"Equatorial Indian Ocean"*) to exact latitude/longitude bounding boxes.
- **Output:** Categorizes intent into one of three execution paths (`KNOWLEDGE_ONLY`, `DATA_ONLY`, or `HYBRID`), accompanied by target float IDs, ocean parameters, depth levels, and temporal constraints.

### 2. `DataQueryAgent`
- **Responsibility:** Generates and executes schema-accurate SQL against the ARGO relational store.
- **Deterministic SQL Validator:** Inspects the query AST using `sqlglot`. Prohibits DDL/DML, restricts queries exclusively to `SELECT`, whitelists tables (`argo_floats`, `argo_profiles`, `argo_measurements`), limits output to a safe ceiling (500 rows), and enforces a 5-second statement timeout.
- **Automated Join Refinement:** When queries select measurement fields (`temperature_c`, `salinity_psu`, `pressure_dbar`) alongside float/profile filters, the agent automatically validates and injects the proper join (`argo_measurements.profile_id = argo_profiles.id`).

### 3. `ScientificResponseAgent`
- **Responsibility:** Translates raw database rows and retrieved literature passages into clear scientific explanations.
- **Deterministic Aggregations:** Computes sample sizes, mean temperature, mean salinity, and depth ranges directly from the returned result set rather than relying on LLM arithmetic.
- **Dynamic Visualization Builder:** Analyzes query keywords and column aliases to generate verified Chart.js visualization specifications (e.g., selecting vertical line profiles for depth queries, histograms for distributions, scatter plots for T-S relationships, and line charts for temporal series).

---

## 7. Agent Workflows

FloatChat AI supports three execution workflows:

| Workflow | Trigger Condition | Execution Path | Example Query |
| :--- | :--- | :--- | :--- |
| **`KNOWLEDGE_ONLY`** | Conceptual, theoretical, or instrument questions without float/observational filters. | Skips SQL generation. Runs semantic vector retrieval over `argo_knowledge_chunks` and synthesizes an evidence-backed answer with literature citations. | *"What is an ARGO float and how does it measure ocean salinity?"* |
| **`DATA_ONLY`** | Empirical requests targeting float IDs, geographic regions, depth levels, or time series. | Invokes `DataQueryAgent` -> AST validation -> execution against `floatchat_db` -> generates data summary and visualization specification. | *"Show the vertical temperature profile for float 1902671."* |
| **`HYBRID`** | Questions combining conceptual ocean physics with specific observational data. | Executes `DataQueryAgent` and vector RAG retrieval concurrently. Merges returned rows and scientific chunks into a unified response with both data visualizations and theoretical context. | *"Explain what the thermocline is and show the temperature profile for float 1902671."* |

---

## 8. Technology Stack

### Frontend Client
- **Framework:** React 18 (Functional components, Hooks)
- **Tooling:** Vite 5 (Fast HMR, optimized production bundling)
- **Data Visualization:** Chart.js 4 & `react-chartjs-2`
- **Routing & Networking:** React Router DOM 6, Axios (with JWT interceptors)
- **Testing:** Vitest, `@testing-library/react`, JSDOM

### Application Backend Tier
- **Framework:** Spring Boot 3.3.4 (Java 17+)
- **Security:** Spring Security 6, JJWT (JSON Web Token authentication)
- **Persistence:** Spring Data JPA, Hibernate, PostgreSQL JDBC Driver
- **Resilience:** In-memory sliding-window rate limiting, configurable AI service read/connect timeouts
- **Build Tool:** Apache Maven (Wrapper included: `./mvnw`)

### AI & Orchestration Engine
- **Framework:** Python 3.10+, FastAPI, Uvicorn
- **Orchestration:** LangGraph 0.2+, LangChain Core
- **Validation:** Pydantic v2, `sqlglot` (SQL AST parser)
- **Database Driver:** `psycopg2-binary`, `pgvector-python`
- **Concurrency:** Thread-safe cooperative `CancellationToken`

### Local Inference & Storage
- **LLM Engine:** Ollama (local CPU/GPU inference)
  - **Generation Model:** `qwen2.5:1.5b-instruct`
  - **Embedding Model:** `nomic-embed-text` (768-dimensional embeddings)
- **Database:** PostgreSQL 15 with **PostGIS** (geospatial indexing) and **pgvector** (vector indexing)

---

## 9. Database Architecture

The data tier is deployed on PostgreSQL 15, containerized via Docker Compose, and partitioned into distinct logical domains:

### Relational ARGO Schema (`floatchat_db`)
- `argo_floats`: Float platform metadata (WMO platform number, float owner, deployment date).
- `argo_profiles`: Profile metadata (cycle number, timestamp, location geometry `GEOMETRY(Point, 4326)`).
- `argo_measurements`: High-resolution depth-level observations (profile foreign key, pressure in decibars, temperature in °C, salinity in PSU, QC quality flags).

### Scientific Vector Store (`argo_knowledge_chunks`)
- Storage for domain literature and ARGO technical documentation.
- Indexed with `vector(768)` utilizing HNSW cosine distance indexes (`vector_cosine_ops`) for sub-millisecond similarity lookups.

### Application Persistence Schema (`floatchat_app`)
- `users`: User credentials, password hashes (BCrypt), and assigned roles (`ROLE_USER`, `ROLE_SCIENTIST`, `ROLE_ADMIN`).
- `query_history`: Historical log of queries, response payloads, workflow classifications, and latency metrics.
- `conversations`: Conversation sessions and multi-turn message history.

### Database Security Hardening
- **Service Isolation:** Python AI Service connects using a dedicated read-only database user (`floatchat_ai_user`).
- **Privilege Separation:** `floatchat_ai_user` possesses strictly `SELECT` permissions on `argo_*` tables, with no write, update, drop, or administrative rights.

---

## 10. ARGO Dataset Information

The local demonstration database contains a verified, high-quality subset of real ARGO oceanographic observations deployed across the **Indian Ocean**:

| Metric | Verified Count | Description |
| :--- | :--- | :--- |
| **Active Floats** | **30** | WMO-registered profiling floats operating in the Indian Ocean basin |
| **Ocean Profiles** | **107** | Ascending and descending sampling cycles with validated GPS coordinates |
| **Measurements** | **26,046** | High-resolution vertical measurement records (temperature, salinity, pressure) |
| **Vector Chunks** | **12** | Curated oceanographic knowledge passages covering thermoclines, water masses, and ARGO sensor mechanics |
| **Embedding Dimension** | **768** | Generated via `nomic-embed-text` |
| **Temporal Coverage** | **2024–2025** | Validated recent Indian Ocean physical observations |

---

## 11. Repository Structure

```
FLOATCHAT/
├── .env.example                     # Root environment variable template
├── .gitignore                        # Git exclusion configuration
├── docker-compose.yml                # PostgreSQL 15 + PostGIS + pgvector orchestration
├── README.md                         # Comprehensive project documentation
├── requirements.txt                  # Python dependencies
├── backend/                          # Spring Boot 3 Java Application Backend
│   ├── mvnw / mvnw.cmd               # Maven wrappers
│   ├── pom.xml                       # Maven build configuration
│   ├── run.ps1                       # Backend startup script (PowerShell)
│   └── src/
│       ├── main/
│       │   ├── java/com/floatchat/backend/
│       │   │   ├── config/           # Security, CORS, and Web MVC configuration
│       │   │   ├── controller/       # REST API endpoints (Chat, Auth, Dashboard, etc.)
│       │   │   ├── dto/              # Request / Response Data Transfer Objects
│       │   │   ├── entity/           # JPA Entities (User, QueryHistory, Conversation)
│       │   │   ├── integration/      # Python AI service client (Real & Mock providers)
│       │   │   ├── repository/       # Spring Data JPA repositories
│       │   │   └── service/          # Business logic and transaction management
│       │   └── resources/
│       │       └── application.properties # Spring Boot configuration
│       └── test/                     # Backend integration and controller tests
├── frontend/                         # React 18 + Vite Frontend Application
│   ├── .env.example                  # Frontend environment template
│   ├── index.html                    # Single-page application entry HTML
│   ├── package.json                  # Frontend dependencies and scripts
│   ├── vite.config.js                # Vite build and proxy configuration
│   └── src/
│       ├── components/               # Reusable UI components (Navbar, DataVisualization, etc.)
│       ├── context/                  # React contexts (AuthContext, ThemeContext)
│       ├── pages/                    # Route pages (Chat, Dashboard, Visualizations, etc.)
│       ├── services/                 # API service clients and axios interceptors
│       ├── styles/                   # CSS stylesheets
│       └── tests/                    # Frontend Vitest suite (124 tests)
├── src/                              # Python AI Service (FastAPI + LangGraph)
│   ├── config.py                     # AI service configuration and environment loading
│   ├── agents/                       # Specialized LangGraph agents
│   │   ├── query_understanding/      # QueryUnderstandingAgent & Gazetteer
│   │   ├── data_query/               # DataQueryAgent & SQL generator
│   │   └── response/                 # ScientificResponseAgent & Chart builder
│   ├── api/                          # FastAPI route handlers and request models
│   ├── llm/                          # LLM provider abstractions (Ollama & Gemini)
│   ├── orchestration/                # LangGraph workflow graphs & CancellationToken
│   ├── rag/                          # Embeddings, pgvector storage, and vector retrieval
│   └── security/                     # SQL AST validator and security sanitizer
├── tests/                            # Python Pytest test suite (451 tests)
├── data/                             # Sample netCDF datasets and knowledge documents
└── scripts/                          # Ingestion, benchmarking, and database setup scripts
```

---

## 12. Prerequisites & Installation

Ensure the following tools are installed on your host system:

1. **Docker & Docker Compose:** Version 24.0+
2. **Python:** Version 3.10 or 3.11
3. **Java Development Kit (JDK):** Version 17 or higher
4. **Node.js & npm:** Node.js v18.0+ and npm v9.0+
5. **Ollama:** Download and install from [ollama.com](https://ollama.com)

### Pull Required Ollama Models
Launch Ollama and pull the required generation and embedding models:

```bash
ollama pull qwen2.5:1.5b-instruct
ollama pull nomic-embed-text
```

---

## 13. Environment Configuration

### Root Environment Setup
Copy the template `.env.example` in the project root to `.env`:

```bash
cp .env.example .env
```

Review `.env` and configure your credentials. The defaults are pre-configured for local containerized development:

```ini
# LLM Provider
LLM_PROVIDER=ollama
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=qwen2.5:1.5b-instruct

# Database (Docker container maps internal 5432 to host port 5433)
POSTGRES_HOST=localhost
POSTGRES_PORT=5433
POSTGRES_DB=floatchat_db
POSTGRES_USER=floatchat_user
POSTGRES_PASSWORD=your_secure_password_here
POSTGRES_READONLY_USER=floatchat_ai_user
POSTGRES_READONLY_PASSWORD=your_secure_readonly_password_here

# Spring Boot Configuration
APP_DB_HOST=127.0.0.1
APP_DB_PORT=5433
APP_DB_NAME=floatchat_app
APP_DB_USER=floatchat_app_user
APP_DB_PASSWORD=your_secure_app_password_here
APP_AI_MODE=real
AI_SERVICE_URL=http://127.0.0.1:8000

# Security Tokens (minimum 32 characters)
FLOATCHAT_INTERNAL_SECRET=your_shared_internal_secret_at_least_32_bytes_here
JWT_SECRET=your_jwt_signing_secret_at_least_32_bytes_here
```

### Frontend Environment Setup
Copy `frontend/.env.example` to `frontend/.env`:

```bash
cp frontend/.env.example frontend/.env
```

*(Note: For local development, `VITE_API_BASE_URL` can remain blank because Vite automatically proxies `/api` requests to `http://localhost:8080`).*

---

## 14. Docker Database Startup

Launch the containerized PostgreSQL database (equipped with PostGIS and pgvector extensions):

```bash
docker compose up -d --build
```

Verify the container is running and healthy:

```bash
docker ps --filter "name=floatchat_postgis_db"
```

The database accepts connections on host port **`5433`**.

---

## 15. Python AI Service Startup

1. Create and activate a Python virtual environment:

```bash
# Windows
py -3.10 -m venv venv
.\venv\Scripts\activate

# Linux / macOS
python3 -m venv venv
source venv/bin/activate
```

2. Install dependencies:

```bash
pip install -r requirements.txt
```

3. Start the FastAPI service via Uvicorn:

```bash
uvicorn src.api.main:app --host 127.0.0.1 --port 8000 --reload
```

Verify service readiness by querying:
```bash
curl http://127.0.0.1:8000/ready
```

---

## 16. Java Spring Boot Backend Startup

In a new terminal, launch the Spring Boot backend service:

### Option A: Using the PowerShell startup helper (Windows)
```powershell
powershell -ExecutionPolicy Bypass -File backend\run.ps1
```

### Option B: Using Maven directly
```bash
cd backend
./mvnw spring-boot:run
```

The Spring Boot backend will start on **`http://localhost:8080`**.

---

## 17. React / Vite Frontend Startup

In another terminal, install dependencies and start the Vite development server:

```bash
cd frontend
npm install
npm run dev
```

Open your browser and navigate to:
**`http://localhost:5173`**

---

## 18. API Endpoints

### Python AI Service (`http://127.0.0.1:8000`)

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `POST` | `/api/v1/chat` | Main LangGraph chat pipeline (supports query understanding, SQL execution, RAG, and visualization generation). |
| `GET` | `/health` | Basic application liveness check. |
| `GET` | `/ready` | Readiness check (validates database connection and Ollama model availability). |
| `GET` | `/api/v1/stats` | Dataset statistics (active floats, total profiles, measurements, vector chunks). |

### Spring Boot Backend (`http://localhost:8080`)

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `POST` | `/api/v1/auth/register` | Register a new user account. |
| `POST` | `/api/v1/auth/login` | Authenticate with credentials and receive a JWT access token. |
| `POST` | `/api/v1/chat` | Authenticated chat endpoint; proxies to Python AI engine, attaches audit metadata, and persists history. |
| `GET` | `/api/v1/conversations` | Retrieve past conversation sessions for the authenticated user. |
| `GET` | `/api/v1/conversations/{id}`| Retrieve full message history of a specific conversation. |
| `GET` | `/api/v1/dashboard/metrics` | Real-time system metrics, active query count, and latency trends. |
| `GET` | `/api/v1/dashboard/stats` | Aggregated user and query volume statistics. |
| `GET` | `/api/v1/visualizations/recent` | Recent visualization specifications generated for the user. |

---

## 19. Example Queries for Demonstration

Try entering these representative queries in the FloatChat interface:

### 1. Vertical Temperature Depth Profile (Inverted Depth Line Chart)
> *"Show the vertical temperature profile for float 1902671."*
- **Workflow:** `DATA_ONLY`
- **Output:** Inverted vertical profile chart (Pressure on the Y-axis with 0 dbar at the top, Temperature on the X-axis).

### 2. Temperature Measurement Distribution (Histogram)
> *"Analyze the distribution of temperature measurements for float 1902671 and visualize the distribution using appropriate temperature intervals."*
- **Workflow:** `DATA_ONLY`
- **Output:** Bar chart histogram showing frequency counts across binned temperature intervals.

### 3. Salinity Measurement Distribution (Histogram)
> *"Show the distribution of salinity observations for float 5906970."*
- **Workflow:** `DATA_ONLY`
- **Output:** Salinity frequency distribution across practical salinity unit (PSU) bins.

### 4. Temperature vs. Salinity Diagram (T-S Scatter Plot)
> *"Plot temperature versus salinity for float 1902671."*
- **Workflow:** `DATA_ONLY`
- **Output:** Oceanographic T-S scatter diagram showing water mass density characteristics.

### 5. Temporal Trends (Time Series Line Chart)
> *"Show the average temperature over time for float 1902671."*
- **Workflow:** `DATA_ONLY`
- **Output:** Chronological line chart depicting average observed temperature across recorded profile cycles.

### 6. Conceptual Ocean Physics Query
> *"What is an ARGO float and how does it measure ocean salinity?"*
- **Workflow:** `KNOWLEDGE_ONLY`
- **Output:** RAG-grounded scientific explanation detailing CTD (Conductivity, Temperature, Depth) sensors, buoyancy engines, and satellite telemetry, with citations.

### 7. Hybrid Analysis Query
> *"Explain what the thermocline is and show the temperature profile for float 1902671."*
- **Workflow:** `HYBRID`
- **Output:** Combined theoretical explanation of the ocean thermocline alongside an interactive vertical temperature depth profile.

---

## 20. Testing Instructions

FloatChat includes comprehensive test suites across all tiers:

### Python AI Service Test Suite (451 tests)
Run pytest with unit and integration tests:

```bash
pytest tests -v
```

Tests cover:
- Agent state transitions and graph routing
- Deterministic SQL AST validation and injection rejection
- Gazetteer spatial coordinate lookups
- Visualization specification synthesis
- Cooperative cancellation token behavior

### React Frontend Test Suite (124 tests)
Run Vitest with React Testing Library:

```bash
cd frontend
npm test
```

Tests cover:
- Authentication state and JWT session expiry handling
- Dynamic chart type rendering and axis configuration
- Chat message stream formatting and citation rendering
- Route protection and error boundary handling

### Spring Boot Backend Test Suite
Run Maven test lifecycle:

```bash
cd backend
./mvnw test
```

Tests cover:
- Spring Security authentication and JWT token issuance
- AI service integration and fallback mock providers
- Conversation restoration and transaction boundaries

---

## 21. Known Limitations

- **CPU Inference Latency:** Running local LLMs (`qwen2.5:1.5b-instruct`) on standard laptop CPUs typically takes 10–25 seconds per inference turn. Systems with dedicated NVIDIA GPUs or remote Ollama servers experience sub-3-second responses.
- **Dataset Geographic Scope:** The packaged demonstration database contains a 30-float subset focused on the Indian Ocean basin covering 2024–2025 observations.
- **Query Row Ceiling:** Queries are capped at 500 rows to ensure sub-second browser chart rendering and prevent DOM memory exhaustion.

---

## 22. Future Scope

- **Live GTS Data Streaming:** Ingesting live netCDF feeds directly from the Global Telecommunication System (GTS) and INCOIS FTP servers in real time.
- **Multi-Model GPU Serving:** Supporting vLLM or TensorRT-LLM containerized microservices for concurrent high-throughput inference.
- **3D Geospatial Ocean Volume:** Integrating CesiumJS or Mapbox GL for interactive 3D bathymetric and water column visualization.
- **Automated Anomaly Detection:** Real-time alerting for marine heatwaves, oxygen minimum zones (OMZ), and extreme salinity anomalies.

---

## 23. Team & Acknowledgements

FloatChat AI is developed as an open-source oceanographic data exploration platform.

### Acknowledgements
- **INCOIS (Indian National Centre for Ocean Information Services):** For oceanographic data guidance and observation datasets.
- **International ARGO Program:** For pioneering global ocean observation and maintaining open data access.
- **Scripps Institution of Oceanography & Coriolis:** For data standards, calibration quality control guidelines, and documentation.
- **Open Source Communities:** LangGraph, FastAPI, Spring Boot, React, Vite, Chart.js, PostgreSQL/PostGIS, pgvector, and Ollama.
