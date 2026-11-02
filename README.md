# FloatChat AI 🌊
### Agentic Conversational Platform for Oceanographic Data Discovery & Analysis

![Architecture](https://img.shields.io/badge/Architecture-3--Tier%20Microservices-blue)
![Frontend](https://img.shields.io/badge/Frontend-React%2018%20%7C%20Vite%206-61dafb)
![Backend](https://img.shields.io/badge/Backend-Spring%20Boot%203.3.5%20%7C%20Java%2021-6db33f)
![AI Engine](https://img.shields.io/badge/AI%20Engine-FastAPI%20%7C%20LangGraph-009688)
![Database](https://img.shields.io/badge/Database-PostgreSQL%2015%20%7C%20PostGIS%20%7C%20pgvector-336791)
![Inference](https://img.shields.io/badge/Inference-Ollama%20(Local%20CPU)-black)

FloatChat AI is an agentic conversational platform that enables researchers, oceanographers, and analysts to explore and analyze oceanographic observation data collected by the international **ARGO float program**. By coordinating multi-agent LangGraph workflows with deterministic Abstract Syntax Tree (AST) SQL validation, vector-grounded retrieval-augmented generation (RAG), and interactive scientific visualizations, FloatChat provides a natural-language interface for querying high-dimensional ocean data.

Users can conversationally inspect vertical temperature and salinity depth profiles, analyze measurement distributions, examine water mass characteristics through temperature-salinity diagrams, review temporal trends, and explore oceanographic literature without manually constructing complex SQL or parsing netCDF files.

---

## Table of Contents

1. [Project Overview](#1-project-overview)
2. [Problem Statement](#2-problem-statement)
3. [Objectives](#3-objectives)
4. [Key Features](#4-key-features)
5. [System Architecture](#5-system-architecture)
6. [Three-Agent Architecture](#6-three-agent-architecture)
7. [Workflow Explanation](#7-workflow-explanation)
8. [Technology Stack](#8-technology-stack)
9. [Database Architecture](#9-database-architecture)
10. [Dataset Information](#10-dataset-information)
11. [Repository Structure](#11-repository-structure)
12. [Prerequisites and Installation](#12-prerequisites-and-installation)
13. [Environment Configuration](#13-environment-configuration)
14. [Running the Application](#14-running-the-application)
15. [API Endpoints](#15-api-endpoints)
16. [Example Demonstration Queries](#16-example-demonstration-queries)
17. [Testing](#17-testing)
18. [Known Limitations](#18-known-limitations)
19. [Future Scope](#19-future-scope)
20. [Team and Acknowledgements](#20-team-and-acknowledgements)

---

## 1. Project Overview

FloatChat AI bridges the gap between complex oceanographic datasets and domain practitioners. Built on a three-tier microservice architecture—a React 18 single-page application, a Spring Boot 3.3 application backend, and a FastAPI AI engine coordinated by LangGraph—the platform translates natural language inquiries into schema-validated PostGIS queries, retrieves relevant domain literature using `pgvector`, and produces structured scientific responses with dynamic chart specifications.

---

## 2. Problem Statement

ARGO profiling floats collect essential physical oceanography data across the global ocean, descending to depths of 2,000 meters and recording vertical profiles of pressure, temperature, and salinity:

- **Complex Schema & Formats:** Data is traditionally archived in multi-dimensional netCDF files or normalized relational tables with spatial geometries, requiring specialized data tools or advanced SQL for spatial filtering (`ST_DWithin`, `ST_MakePoint`).
- **Domain Context Requirement:** Interpreting observational measurements often requires cross-referencing domain literature (e.g., mixed-layer depth, thermocline gradients, water mass definitions) alongside numerical records.
- **SQL Reliability & Safety Risks:** Direct LLM-to-SQL generation can hallucinate schema elements, create inefficient cartesian joins, or produce non-executable queries without strict validation gates.
- **Visual Presentation Needs:** Numerical tables alone do not convey oceanographic patterns as effectively as domain-specific charts (such as vertical profiles with inverted depth axes).

---

## 3. Objectives

- **Natural Language Discovery:** Enable users to query Indian Ocean ARGO float observations and ocean physics using conversational natural language.
- **Deterministic SQL Safety:** Validate generated SQL through AST parsing (`sqlglot`), schema/table/column whitelisting, automatic join injection, hard statement timeouts, and a dedicated unprivileged database role (`floatchat_ai_user`).
- **Evidence-Grounded Explanations:** Pair numerical database observations with semantic vector retrieval over oceanographic literature (`pgvector` with `nomic-embed-text`) to ground scientific explanations.
- **Dynamic Oceanographic Visualizations:** Automatically select and configure appropriate chart types (vertical profiles, histograms, scatter plots, time series) following physical oceanography conventions.
- **Resilient Multi-Tier Coordination:** Provide JWT-based user authentication, role management (`USER`, `ADMIN`, `SUPER_ADMIN`), conversation persistence, in-memory rate limiting, and cooperative cancellation tokens to halt orphaned background workflows cleanly.

---

## 4. Key Features

- **Three Specialized LangGraph Agents:** Coordinated query understanding, SQL data querying, and scientific response synthesis.
- **Deterministic AST SQL Validator:** Parses candidate queries with `sqlglot`, restricts operations to `SELECT`, whitelists tables and columns, injects safe row limits (default 500, max 1000), and auto-joins `argo_measurements` and `argo_profiles` on `profile_id`.
- **Vector-Grounded Oceanographic RAG:** Cosine similarity vector search over curated oceanographic documentation stored in `argo_doc_embeddings`.
- **Dynamic Visualizations:** Generates specifications rendered in Recharts and Leaflet for vertical depth profiles (inverted pressure axis), parameter distribution histograms, T-S scatter diagrams, time-series lines, and geographic maps.
- **Cooperative Cancellation:** Employs thread-safe `CancellationToken` checkpoints between LangGraph nodes to prevent unnecessary processing after HTTP client timeouts or disconnections.
- **Enterprise Application Backend:** Spring Boot 3.3 provides token authentication, conversation session tracking, and rate limiting.
- **Responsive React 18 UI:** Clean marine-themed web application with interactive chart rendering, conversation history restoration, and citation drawers.

---

## 5. System Architecture

```mermaid
flowchart TD
    subgraph Client_Tier ["Client Tier"]
        UI["React 18 + Vite SPA<br/>(Port 5173)"]
    end

    subgraph Backend_Tier ["Application Backend Tier (Spring Boot 3.3.5)"]
        GW["REST API Gateway & Security<br/>(Port 8080)"]
        AUTH["JWT Authentication & Rate Limiting"]
        PERSIST["Conversation Persistence Service"]
        AI_CLIENT["AI Service Client"]
    end

    subgraph AI_Tier ["AI Engine Tier (FastAPI + LangGraph)"]
        API["FastAPI AI Service<br/>(Port 8000)"]
        ORCH["LangGraph Orchestrator<br/>(CancellationToken Checkpoints)"]
        Q_AGENT["1. Query Understanding Agent"]
        D_AGENT["2. Data Query Agent"]
        VAL["Deterministic SQL AST Validator<br/>(sqlglot Whitelist & Auto-Join)"]
        R_AGENT["3. Scientific Response Agent"]
    end

    subgraph Inference_Tier ["Local Inference (Ollama)"]
        LLM["qwen2.5:1.5b-instruct<br/>(Local Generation)"]
        EMBED["nomic-embed-text<br/>(768-dim Embeddings)"]
    end

    subgraph Data_Tier ["Data Tier (PostgreSQL 15 + PostGIS + pgvector)"]
        APP_DB[("Application Store<br/>users, query_history, conversations")]
        ARGO_DB[("Relational ARGO Store<br/>argo_floats, argo_profiles, argo_measurements")]
        VEC_STORE[("Vector Store<br/>argo_doc_embeddings")]
    end

    UI <-->|HTTP / JSON / JWT| GW
    GW --> AUTH
    GW --> PERSIST
    PERSIST <--> APP_DB
    GW --> AI_CLIENT
    AI_CLIENT <-->|HTTP POST /api/v1/chat| API

    API --> ORCH
    ORCH --> Q_AGENT
    Q_AGENT <--> LLM
    Q_AGENT -->|DATA_ONLY| D_AGENT
    Q_AGENT -->|KNOWLEDGE_ONLY| VEC_STORE
    Q_AGENT -->|HYBRID (Parallel Fan-out)| D_AGENT
    Q_AGENT -->|HYBRID (Parallel Fan-out)| VEC_STORE

    D_AGENT <--> LLM
    D_AGENT --> VAL
    VAL -->|Read-Only SQL (floatchat_ai_user)| ARGO_DB

    D_AGENT --> R_AGENT
    VEC_STORE --> R_AGENT
    R_AGENT <--> LLM
    R_AGENT --> API
```

---

## 6. Three-Agent Architecture

FloatChat AI organizes reasoning into **three specialized agents** within a compiled LangGraph state graph:

```
[User Query]
      │
      ▼
┌─────────────────────────────────┐
│ 1. QueryUnderstandingAgent      │ ── Extracts temporal, spatial, float IDs & parameters
└─────────────────────────────────┘ ── Resolves region names via Indian Ocean Gazetteer
      │                            ── Determines workflow: KNOWLEDGE_ONLY | DATA_ONLY | HYBRID
      ├───────────────────────────────┬───────────────────────────────┐
      │ (DATA_ONLY)                   │ (HYBRID - Parallel Fan-out)   │ (KNOWLEDGE_ONLY)
      ▼                               ▼                               │
┌──────────────────────────────┐ ┌──────────────────────────────┐     │
│ 2. DataQueryAgent            │ │ 2. DataQueryAgent            │     │
│  - Few-shot SQL generation   │ │  + Vector RAG Retrieval      │     │
│  - AST validation (sqlglot)  │ └──────────────┬───────────────┘     │
│  - Auto-join & Read-only DB  │                ▼                     │
└──────────────┬───────────────┘       [ join_node barrier ]          │
               │                                │                     │
               └────────────────────────────────┼─────────────────────┘
                                                │
                                                ▼
┌─────────────────────────────────────────────────────────────────────┐
│ 3. ScientificResponseAgent                                          │
│  - Synthesizes observational rows and/or retrieved vector chunks    │
│  - Computes deterministic statistics (sample size, means, ranges)   │
│  - Emits literature citations and visualization specifications      │
└─────────────────────────────────────────────────────────────────────┘
                                                │
                                                ▼
                                    [Structured Response JSON]
```

### 1. `QueryUnderstandingAgent`
- **Function:** Parses user queries into a structured `QueryIntent` object.
- **Gazetteer Matching:** Contains an Indian Ocean Gazetteer mapping geographical names (e.g., *"Arabian Sea"*, *"Bay of Bengal"*, *"Equatorial Indian Ocean"*) to latitude/longitude bounding boxes.
- **Routing:** Classifies queries into `KNOWLEDGE_ONLY`, `DATA_ONLY`, or `HYBRID`, extracting float identifiers, target ocean parameters, pressure ranges, and time windows.

### 2. `DataQueryAgent`
- **Function:** Produces schema-compliant SQL for observational questions.
- **AST Security Gate:** Uses `sqlglot` to inspect candidate SQL syntax trees before execution.
- **Whitelist Enforcement:** Restricts queries to `SELECT`, whitelisting tables (`argo_floats`, `argo_profiles`, `argo_measurements`) and their physical columns.
- **Query Auto-Refinement:** When queries request measurement columns (`temperature_c`, `salinity_psu`, `pressure_dbar`) alongside profile filters, the validator verifies or injects the inner join `argo_measurements.profile_id = argo_profiles.profile_id`.
- **Execution Limits:** Injects a default limit of 500 rows (capped at 1000) and applies a 5,000 ms statement timeout.

### 3. `ScientificResponseAgent`
- **Function:** Translates raw database rows and retrieved literature passages into clear scientific explanations.
- **Deterministic Statistics:** Computes sample sizes, mean temperature, mean salinity, and pressure depth ranges directly from the returned database records to prevent arithmetic errors.
- **Dynamic Visualization Specification:** Generates chart specifications matching query intent (vertical inverted line chart for depth profiles, histograms for distributions, scatter plots for parameter relationships, and chronological line charts for temporal series).

---

## 7. Workflow Explanation

| Workflow | Routing Criteria | Execution Flow | Example Query |
| :--- | :--- | :--- | :--- |
| **`KNOWLEDGE_ONLY`** | Conceptual, physical oceanography, or instrumentation questions without float/observational filters. | Bypasses SQL generation and database execution. Dispatches semantic vector retrieval against `argo_doc_embeddings` and generates an explanation with literature citations. | *"What is an ARGO float and how does it measure ocean salinity?"* |
| **`DATA_ONLY`** | Empirical questions targeting float numbers, geographic coordinates, depth ranges, or time windows. | Dispatches `DataQueryAgent` -> AST validation -> execution on `floatchat_db` -> generates data summary and chart specification. | *"Show the vertical temperature profile for float 1902671."* |
| **`HYBRID`** | Questions combining conceptual ocean physics inquiries with specific observational data requests. | Concurrently dispatches `DataQueryAgent` and vector RAG retrieval via LangGraph parallel fan-out. Both branches synchronize at `join_node` before `ScientificResponseAgent` generates a combined response. | *"Explain what the thermocline is and show the temperature profile for float 1902671."* |

---

## 8. Technology Stack

### Frontend Client
- **Framework:** React 18 (`^18.3.1`)
- **Build Tool:** Vite 6 (`^6.0.7`)
- **Charting Library:** Recharts (`^2.15.0`)
- **Mapping Library:** Leaflet (`^1.9.4`) and React-Leaflet (`^4.2.1`)
- **Icons & UI:** Lucide React (`^1.61.0`)
- **Routing & Networking:** React Router DOM (`^6.28.1`), Axios (`^1.7.9`)
- **Test Runner:** Node Test Runner (`node --test`)

### Application Backend Tier
- **Framework:** Spring Boot 3.3.5 (Java 21+)
- **Security:** Spring Security 6, JJWT (`0.12.6`)
- **Persistence:** Spring Data JPA, Hibernate, PostgreSQL JDBC Driver
- **Build Tool:** Apache Maven (Wrapper included: `./mvnw`, `mvnw.cmd`)

### AI & Orchestration Engine
- **Framework:** Python 3.10+, FastAPI (`>=0.100.0`), Uvicorn (`>=0.20.0`)
- **Orchestration:** LangGraph (`>=0.2.0`)
- **SQL Parsing:** `sqlglot` (`>=20.0.0`)
- **Data Validation:** Pydantic (`>=2.0.0`)
- **Database Driver:** `psycopg2-binary` (`>=2.9.0`)
- **Scientific Formats:** `netCDF4` (`>=1.6.0`), `pandas` (`>=2.0.0`), `pyarrow` (`>=14.0.0`)

### Local Inference & Storage
- **LLM Engine:** Ollama (Local CPU/GPU inference)
  - **Generation Model:** `qwen2.5:1.5b-instruct`
  - **Embedding Model:** `nomic-embed-text` (768-dimensional embeddings)
- **Database:** PostgreSQL 15 with **PostGIS** and **pgvector** extensions

---

## 9. Database Architecture

The database environment is containerized via Docker Compose on PostgreSQL 15:

### 1. Relational ARGO Schema (`floatchat_db`)
- `argo_floats`: Float platform metadata (`platform_number VARCHAR(64) PRIMARY KEY`, `created_at`).
- `argo_profiles`: Profile metadata (`profile_id VARCHAR(255) PRIMARY KEY`, `platform_number REFERENCES argo_floats`, `profile_time TIMESTAMPTZ`, `latitude`, `longitude`, `location GEOMETRY(Point, 4326)`).
- `argo_measurements`: Vertical subsurface observations (`measurement_id BIGINT PRIMARY KEY`, `profile_id REFERENCES argo_profiles`, `pressure_dbar`, `temperature_c`, `salinity_psu`).
- **Join Relationship:** `argo_measurements.profile_id = argo_profiles.profile_id` and `argo_profiles.platform_number = argo_floats.platform_number`.

### 2. Scientific Vector Store (`argo_doc_embeddings`)
- Stores domain literature and ARGO technical guides.
- Schema: `chunk_id BIGSERIAL PRIMARY KEY`, `document_title`, `section_title`, `chunk_content`, `metadata JSONB`, `embedding vector(768)`.
- Retrieval uses cosine distance (`<=>`) against 768-dimensional embeddings generated by `nomic-embed-text`.

### 3. Application Database (`floatchat_app`)
- Managed by Spring Boot JPA.
- `users`: User credentials, BCrypt password hashes, and user roles (`USER`, `ADMIN`, `SUPER_ADMIN`).
- `query_history`: Historical log of executed queries, response payloads, workflows, and latency.
- `conversations`: Conversation sessions and message threads.

### 4. Database Roles and Permissions
- `floatchat_user`: Database superuser used for container administration and initial DDL setup.
- `floatchat_app_user`: Application user owning and managing `floatchat_app` tables.
- `floatchat_ai_user`: Dedicated unprivileged role for the Python AI query engine. Granted strictly `SELECT` permissions on `argo_floats`, `argo_profiles`, `argo_measurements`, and `argo_doc_embeddings`. `INSERT`, `UPDATE`, `DELETE`, and `TRUNCATE` are revoked, and connections to `floatchat_app` are restricted.

---

## 10. Dataset Information

The bundled demonstration dataset contains verified real ARGO observations from the **Indian Ocean**:

| Table | Count | Description |
| :--- | :--- | :--- |
| **`argo_floats`** | **30** | WMO-registered profiling floats operating in the Indian Ocean |
| **`argo_profiles`** | **107** | Ascending and descending sampling profiles with validated GPS coordinates |
| **`argo_measurements`** | **26,046** | Vertical depth records of pressure, temperature, and salinity |
| **`argo_doc_embeddings`** | **12** | Curated oceanographic literature chunks (768-dim embeddings) |

- **Temporal Coverage:** January 2, 2024 to April 1, 2025 (UTC).
- **Geographic Coverage:** Indian Ocean basin.
- *Note:* This represents a regional demonstration subset prepared for local development and testing, not the complete global ARGO repository.

---

## 11. Repository Structure

```
FLOATCHAT/
├── .env.example                     # Root environment template
├── .gitignore                        # Git exclusion rules
├── docker-compose.yml                # PostgreSQL 15 + PostGIS + pgvector service
├── pyproject.toml                    # Python package configuration and dependencies
├── README.md                         # Project documentation
├── backend/                          # Spring Boot 3 Java Application Backend
│   ├── mvnw / mvnw.cmd               # Maven wrappers
│   ├── pom.xml                       # Maven build file (Spring Boot 3.3.5, Java 21)
│   ├── run.ps1                       # Windows backend startup script
│   └── src/
│       ├── main/
│       │   ├── java/com/floatchat/backend/
│       │   │   ├── config/           # Security, CORS, and Web MVC configuration
│       │   │   ├── controller/       # REST controllers (Auth, Chat, Dashboard, Health)
│       │   │   ├── dto/              # Request / Response Data Transfer Objects
│       │   │   ├── entity/           # JPA entities (User, QueryHistory, Conversation)
│       │   │   ├── integration/      # Python AI service client
│       │   │   ├── repository/       # Spring Data JPA repositories
│       │   │   └── service/          # Business logic and persistence services
│       │   └── resources/
│       │       └── application.properties # Spring Boot configuration
│       └── test/                     # Backend integration and controller tests
├── frontend/                         # React 18 + Vite 6 Frontend Application
│   ├── .env.example                  # Frontend environment template
│   ├── index.html                    # Single-page application entry point
│   ├── package.json                  # Frontend dependencies and scripts
│   ├── vite.config.js                # Vite build and dev-server proxy configuration
│   └── src/
│       ├── components/               # UI components (Navbar, DataVisualization)
│       ├── context/                  # React contexts (AuthContext)
│       ├── pages/                    # Route pages (Chat, Dashboard, Visualizations)
│       ├── services/                 # API client modules
│       ├── styles/                   # CSS styling
│       └── tests/                    # Frontend test suite
├── src/                              # Python AI Service (FastAPI + LangGraph)
│   ├── config.py                     # Service configuration and environment loading
│   ├── agents/                       # Specialized LangGraph agents
│   │   ├── query_understanding/      # Query understanding agent and Indian Ocean gazetteer
│   │   ├── data_query/               # Data query agent and prompt templates
│   │   └── response/                 # Response agent and visualization builder
│   ├── api/                          # FastAPI application and route handlers
│   ├── llm/                          # LLM provider implementations (Ollama, Gemini)
│   ├── orchestration/                # LangGraph workflow and cooperative CancellationToken
│   ├── rag/                          # Embeddings, vector storage, and retriever
│   └── security/                     # Deterministic SQL AST validator
├── tests/                            # Python pytest test suite
├── docker/                           # Dockerfiles for custom container builds
├── data/                             # Reference NetCDF datasets and benchmark logs
├── docs/                             # Technical documentation and phase specifications
└── scripts/                          # Ingestion, benchmarking, and database setup scripts
```

---

## 12. Prerequisites and Installation

### Prerequisites
1. **Docker & Docker Compose:** Version 24.0+
2. **Python:** Version 3.10 or 3.11
3. **Java Development Kit (JDK):** Version 21 or higher
4. **Node.js & npm:** Node.js v18.0+ and npm v9.0+
5. **Ollama:** Installed locally from [ollama.com](https://ollama.com)

### 1. Download Required Ollama Models
Ensure Ollama is running, then pull the generation and embedding models:

```bash
ollama pull qwen2.5:1.5b-instruct
ollama pull nomic-embed-text
```

### 2. Python Environment Setup

```bash
# Windows (PowerShell)
py -3.10 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .

# Linux / macOS
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

### 3. Frontend Dependencies Setup

```bash
cd frontend
npm install
cd ..
```

---

## 13. Environment Configuration

FloatChat separates environment configuration across tiers and uses `.env.example` templates to avoid committing credentials.

### Root Environment Setup
1. Copy `.env.example` in the project root to `.env`:
   ```bash
   cp .env.example .env
   ```
2. Configure local database credentials, Ollama endpoint, and service secrets in `.env`.
3. Provide secure, random strings for `JWT_SECRET` and `FLOATCHAT_INTERNAL_SECRET` (at least 32 characters).
4. *Security Notice:* Never commit `.env` or files containing live credentials. The root `.gitignore` excludes `.env` and `.env.*.local`.

### Frontend Environment Setup
1. Copy `frontend/.env.example` to `frontend/.env`:
   ```bash
   cp frontend/.env.example frontend/.env
   ```
2. In local development, `VITE_API_BASE_URL` can remain empty because Vite's development server automatically proxies `/api` requests to `http://localhost:8080`.

---

## 14. Running the Application

Launch the services in four terminal sessions:

### Step 1: Start PostgreSQL Container
```bash
docker compose up -d --build
```
*The database accepts connections on host port **5433** (forwarded to container port 5432).*

### Step 2: Start Python AI Service
```bash
# Activate virtual environment first
# Windows: .\.venv\Scripts\Activate.ps1
# Linux/macOS: source .venv/bin/activate

uvicorn src.api.main:app --host 127.0.0.1 --port 8000 --reload
```
*Verify readiness at: `http://127.0.0.1:8000/ready`*

### Step 3: Start Spring Boot Backend
```powershell
# Windows (PowerShell helper)
powershell -ExecutionPolicy Bypass -File backend\run.ps1

# Cross-platform alternative (Maven)
cd backend
./mvnw spring-boot:run
```
*The backend service starts on `http://localhost:8080`.*

### Step 4: Start Frontend Development Server
```bash
cd frontend
npm run dev
```
*Open your browser and navigate to `http://localhost:5173`.*

---

## 15. API Endpoints

### Python AI Engine (`http://127.0.0.1:8000`)

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `POST` | `/api/v1/chat` | Main LangGraph chat pipeline (supports cancellation and visualization spec generation). |
| `POST` | `/api/v1/query` | Compatibility alias for `/api/v1/chat`. |
| `GET` | `/health` | Application liveness probe. |
| `GET` | `/ready` | Readiness probe (verifies database connectivity and Ollama model availability). |
| `GET` | `/api/v1/stats` | Dataset statistics (counts of floats, profiles, measurements, and vector chunks). |

### Spring Boot Backend (`http://localhost:8080`)

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `POST` | `/api/v1/auth/signup` | Register a new user account. |
| `POST` | `/api/v1/auth/login` | Authenticate with credentials and receive a JWT token. |
| `GET` | `/api/v1/auth/me` | Fetch authenticated user profile and assigned role. |
| `POST` | `/api/v1/auth/bootstrap-super-admin` | Initialize the first `SUPER_ADMIN` account. |
| `POST` | `/api/v1/chat` | Authenticated chat endpoint; proxies to AI service and persists conversation history. |
| `GET` | `/api/v1/conversations` | List conversation sessions for the authenticated user. |
| `GET` | `/api/v1/conversations/{id}` | Retrieve full message thread for a conversation. |
| `DELETE` | `/api/v1/conversations/{id}` | Delete a conversation session. |
| `GET` | `/api/v1/history` | Paginated query history log for the user. |
| `GET` | `/api/v1/user/dashboard` | Dashboard metrics for `USER` role. |
| `GET` | `/api/v1/admin/dashboard` | Management metrics for `ADMIN` role. |
| `GET` | `/api/v1/super-admin/dashboard` | System metrics for `SUPER_ADMIN` role. |
| `GET` | `/api/v1/visualizations` | Retrieve recent visualization specifications. |
| `GET` | `/api/v1/visualizations/{id}` | Retrieve a specific visualization specification. |
| `GET` | `/api/v1/health` | Backend service health check. |
| `GET` | `/api/v1/ai/status` | Upstream AI service status check. |

---

## 16. Example Demonstration Queries

### 1. Vertical Depth Profile (Inverted Line Chart)
> *"Show the vertical temperature profile for float 1902671."*
- **Workflow:** `DATA_ONLY`
- **Output:** Inverted vertical profile chart (Pressure on Y-axis with 0 dbar at the surface, Temperature on X-axis).

### 2. Temperature Measurement Distribution (Histogram)
> *"Analyze the distribution of temperature measurements for float 1902671 and visualize the distribution using appropriate temperature intervals."*
- **Workflow:** `DATA_ONLY`
- **Output:** Frequency histogram showing measurement counts across binned temperature intervals.

### 3. Salinity Measurement Distribution (Histogram)
> *"Show the distribution of salinity observations for float 5906970."*
- **Workflow:** `DATA_ONLY`
- **Output:** Frequency histogram showing observation counts across practical salinity unit (PSU) bins.

### 4. Temperature vs. Salinity Diagram (T-S Scatter Plot)
> *"Plot temperature versus salinity for float 1902671."*
- **Workflow:** `DATA_ONLY`
- **Output:** Scatter plot displaying the relationship between salinity (PSU) and temperature (°C).

### 5. Temporal Trends (Time Series Line Chart)
> *"Show the average temperature over time for float 1902671."*
- **Workflow:** `DATA_ONLY`
- **Output:** Chronological line chart showing average temperature values across profile observation dates.

### 6. Conceptual Oceanographic Knowledge Query
> *"What is an ARGO float and how does it measure ocean salinity?"*
- **Workflow:** `KNOWLEDGE_ONLY`
- **Output:** RAG-grounded scientific explanation describing CTD sensors, buoyancy cycles, and satellite transmission, with literature citations.

### 7. Hybrid Query
> *"Explain what the thermocline is and show the temperature profile for float 1902671."*
- **Workflow:** `HYBRID`
- **Output:** Theoretical overview of the ocean thermocline alongside an interactive vertical temperature depth profile.

---

## 17. Testing

FloatChat maintains automated test suites across all three application layers:

### Python AI Service Test Suite
Run unit, validation, and LangGraph workflow tests with `pytest`:

```bash
pytest tests -v
```

- **Scope:** SQL AST validation rules, query intent extraction, Indian Ocean gazetteer bounding-box matching, RAG retriever logic, visualization spec builders, and cooperative cancellation tokens.
- **Verification Status:** **451 tests passing**, 1 skipped (optional cloud Gemini integration).

### Frontend Test Suite
Run the frontend component, routing, and visualization tests:

```bash
cd frontend
npm test
```

- **Scope:** Authentication lifecycle, Axios 401 interception, route guards, conversation restoration, chart type selection, timestamp formatting, and depth axis orientation.
- **Verification Status:** **124 tests passing** across 9 test suites.

### Backend Test Suite
Run Spring Boot tests using Maven:

```bash
cd backend
./mvnw test
```

- **Scope:** Security configuration, JWT token issuance, conversation transaction boundaries, and AI provider integration fallbacks.

---

## 18. Known Limitations

- **Local CPU Inference Latency:** Running local LLMs (`qwen2.5:1.5b-instruct`) on laptop CPUs typically requires 8–25 seconds per conversational turn depending on query type and CPU thread availability.
- **Cooperative Cancellation Scope:** The `CancellationToken` checks for cancellation between LangGraph nodes and processing steps. It does not forcibly terminate in-flight synchronous HTTP network requests while Ollama is actively processing a token generation step.
- **Demonstration Dataset Boundary:** The local PostgreSQL database is loaded with an Indian Ocean regional subset (30 floats, 107 profiles, 26,046 measurements) covering 2024 to early 2025. It does not represent the full global ARGO repository.
- **SQL Row Ceiling:** Observational queries enforce a default result limit of 500 rows (hard ceiling of 1000) to protect browser memory and maintain responsive chart rendering.

---

## 19. Future Scope

- **Real-Time GTS Data Ingestion:** Automated netCDF ingestion from the Global Telecommunication System (GTS) and national ocean data centers.
- **GPU Inference Serving:** Support for high-throughput serving frameworks (such as vLLM or TensorRT-LLM) for faster inference times.
- **3D Geospatial Visualizations:** Integration of 3D globe and bathymetric volume rendering for ocean current dynamics.
- **Automated Marine Anomaly Detection:** Automated detection and alerting for marine heatwaves and extreme salinity events.

---

## 20. Team and Acknowledgements

FloatChat AI is developed as an open-source oceanographic data exploration platform.

### Acknowledgements
- **INCOIS (Indian National Centre for Ocean Information Services):** For oceanographic observation data and domain guidance.
- **International ARGO Program:** For global ocean observation data access.
- **Scripps Institution of Oceanography & Coriolis:** For data standards, calibration quality control guidelines, and documentation.
- **Open Source Communities:** FastAPI, LangGraph, Spring Boot, React, Vite, Recharts, Leaflet, PostgreSQL/PostGIS, pgvector, and Ollama.
