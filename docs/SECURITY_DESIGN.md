# FloatChat: Deterministic Security & SQL Safety Specification

**Document Version:** 1.0.0  
**Phase:** Phase 0 (Architecture & Specification)  
**Status:** Approved Specification  

---

## 1. Security Architecture Principles

FloatChat enforces security at the **deterministic software boundary**. The system does **NOT** rely on LLMs or probabilistic self-policing for safety.

> **CRITICAL RULE:** Security is handled strictly by a deterministic Python AST parser and validator. There is **NO Security Agent**. Security is a non-AI deterministic software gate.

```
+--------------------+       +-------------------------------+       +-------------------------------+       +---------------------+
|  Data Query Agent  | ----> |  DETERMINISTIC SQL VALIDATOR  | ----> | CONTROLLED DB EXECUTION LAYER | ----> | PostgreSQL/PostGIS  |
|  (Candidate SQL)   |       |  (Non-LLM sqlglot AST Parser) |       | (Read-Only Session + Timeout) |       | (Physical Engine)   |
+--------------------+       +-------------------------------+       +-------------------------------+       +---------------------+
                                             |
                                             v (If Unsafe)
                                     [ REJECT & RETRY ]
```

---

## 2. Deterministic SQL Validator Specification

The SQL Validator is a non-LLM Python module built on `sqlglot` (`src/security/sql_validator.py`) that inspects the Abstract Syntax Tree (AST) of every candidate SQL string prior to database submission.

### 2.1 Security Controls & Rules

| Control ID | Constraint Type | Rule Enforcement Description | Action on Failure |
| :--- | :--- | :--- | :--- |
| **SEC-01** | **Statement Type** | AST root must strictly be `SELECT`. Any statement containing `INSERT`, `UPDATE`, `DELETE`, `DROP`, `ALTER`, `TRUNCATE`, `GRANT`, `REVOKE`, `EXEC`, `COPY`, `SELECT INTO` is rejected immediately. | Immediate Query Rejection |
| **SEC-02** | **Table Allowlist** | Queries may target **only** approved tables: `argo_floats`, `argo_profiles`, `argo_measurements`. Queries targeting system tables (`pg_catalog`, `information_schema`) or internal embedding tables are rejected. | Rejection & Retry |
| **SEC-03** | **Column Allowlist** | Queries may reference only verified, physical schema columns (`platform_number`, `profile_id`, `profile_time`, `latitude`, `longitude`, `location`, `measurement_id`, `pressure_dbar`, `temperature_c`, `salinity_psu`, `created_at`). | Rejection & Retry |
| **SEC-04** | **Dangerous Functions** | Prohibits invocation of file access, system execution, or administrative SQL functions (`pg_read_file`, `pg_ls_dir`, `pg_sleep`, `pg_terminate_backend`, `eval`, `query_to_xml`). | Immediate Rejection |
| **SEC-05** | **Forced LIMIT** | Ensures every query includes an explicit `LIMIT` clause capped at `MAX_LIMIT = 1000` to prevent memory exhaustion / denial of service. Auto-injects default `LIMIT 500` if missing. | Injected / Capped in AST |
| **SEC-06** | **Execution Timeout** | Database session statement timeout enforced at `STATEMENT_TIMEOUT_MS = 5000` (5 seconds). Enforced at runtime by the Controlled Database Execution Layer (Phase 6) via `SET statement_timeout = 5000;`. | DB Connection Abort |

> **Architectural Separation:** The `DeterministicSQLValidator` performs static AST security validation and query normalisation. Physical runtime execution safeguards (session parameters, read-only connection credentials, and runtime statement timeouts) are enforced downstream by the Controlled Database Execution Layer (Phase 6).

---

## 3. SQL Validation Implementation Architecture (`src/security/sql_validator.py`)

```python
ALLOWED_TABLES = {"argo_floats", "argo_profiles", "argo_measurements"}

ALLOWED_COLUMNS_BY_TABLE = {
    "argo_floats": {"platform_number", "created_at"},
    "argo_profiles": {"profile_id", "platform_number", "profile_time", "latitude", "longitude", "location"},
    "argo_measurements": {"measurement_id", "profile_id", "pressure_dbar", "temperature_c", "salinity_psu"},
}

ALLOWED_STANDARD_FUNCTIONS = {
    "count", "avg", "min", "max", "sum", "coalesce", "round",
    "date_trunc", "extract", "cast", "to_char", "abs", "floor", "ceil"
}

ALLOWED_POSTGIS_FUNCTIONS = {
    "st_dwithin", "st_within", "st_intersects", "st_distance",
    "st_makepoint", "st_point", "st_setsrid", "st_makeenvelope",
    "st_area", "st_length", "st_asgeojson", "st_astext", "st_contains", "st_centroid", "st_isvalid"
}
```

---

## 4. Prompt Injection & Tool Restrictions

- **System Prompt Framing:** Agent prompts use system-level delimiters to isolate user inputs from instructions.
- **No Unrestricted Code Execution:** Agents have zero access to shell environments, file writing tools, or network sockets during runtime execution.
- **Secret Management:** Database passwords, LLM provider API keys (e.g., Gemini API key), and JWT secrets are injected via environment variables (`.env`) and never exposed in client payloads or code repositories.
