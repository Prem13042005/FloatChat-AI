# FloatChat Phase 2.1: PostgreSQL / PostGIS Database Foundation Specification

**Document Version:** 1.0.0  
**Phase:** Phase 2.1 (Database Foundation Planning & Environment Setup)  
**Status:** Approved Architectural Specification  
**Target Engine:** PostgreSQL 15+ with PostGIS 3.3+ and `pgvector` Extensions  

---

## 1. Database Objective

The objective of Phase 2 is to establish the physical database foundation for FloatChat, providing an immutable, highly-indexed **Numerical Source of Truth** for physical oceanographic profile observations and a single unified database engine for future vector similarity retrieval.

Phase 2.1 focuses strictly on **architecture verification, DDL schema design, index strategy, container environment setup, and schema validation**. Data loading into PostgreSQL is explicitly deferred to Phase 2.2.

---

## 2. PostgreSQL / PostGIS Architecture

FloatChat uses a single, unified database instance (`postgis/postgis:15-3.3`) incorporating spatial geometry and vector indexing capabilities.

```
+-------------------------------------------------------------------------------+
|                       UNIFIED POSTGRESQL 15 DATABASE                          |
|                               (floatchat_db)                                  |
+-------------------------------------------------------------------------------+
       │                                       │
       ▼ (Relational & PostGIS Engine)          ▼ (pgvector Engine)
+------------------------------------+   +------------------------------------+
|  OCEANOGRAPHIC OBSERVATION SCHEMAS |   | SCIENTIFIC DOCUMENTATION SCHEMAS   |
| - argo_floats                      |   | - argo_doc_embeddings              |
| - argo_profiles (Spatial Location) |   |   (Vector search for Phase 7 RAG)  |
| - argo_measurements (Sub-surface)  |   +------------------------------------+
+------------------------------------+
```

---

## 3. Physical Table Specifications

### 3.1 Table 1: `argo_floats` (Platform Metadata)
Stores platform-level identification metadata for ARGO floats.
- **Primary Key:** `platform_number` (`VARCHAR(64)`)
- **Columns:**
  - `platform_number` (`VARCHAR(64)` NOT NULL): Unique WMO float platform identifier (e.g. `'1902671'`).
  - `created_at` (`TIMESTAMPTZ` NOT NULL DEFAULT `CURRENT_TIMESTAMP`): Record creation timestamp.

### 3.2 Table 2: `argo_profiles` (Spatial-Temporal Station Headers)
Stores station header metadata for individual float profile casts.
- **Primary Key:** `profile_id` (`VARCHAR(255)`)
- **Natural Key Constraint:** `UNIQUE(platform_number, profile_time)`
- **Foreign Key:** `platform_number` REFERENCES `argo_floats(platform_number)` ON DELETE CASCADE
- **Columns:**
  - `profile_id` (`VARCHAR(255)` NOT NULL): Deterministic profile ID (e.g. `'PROF_1902671_20240107T134833Z'`).
  - `platform_number` (`VARCHAR(64)` NOT NULL): Reference to float platform.
  - `profile_time` (`TIMESTAMPTZ` NOT NULL): Station profile observation timestamp in UTC.
  - `latitude` (`DOUBLE PRECISION` NOT NULL): Station latitude coordinate in degrees north (`degrees_north`).
  - `longitude` (`DOUBLE PRECISION` NOT NULL): Station longitude coordinate in degrees east (`degrees_east`).
  - `location` (`GEOMETRY(Point, 4326)` NOT NULL): PostGIS WGS84 spatial point geometry.

### 3.3 Table 3: `argo_measurements` (Ocean Physical Observations)
Stores discrete sub-surface physical measurements recorded at specific pressure levels.
- **Primary Key:** `measurement_id` (`BIGINT`)
- **Foreign Key:** `profile_id` REFERENCES `argo_profiles(profile_id)` ON DELETE CASCADE
- **Columns:**
  - `measurement_id` (`BIGINT` NOT NULL): Unique observation measurement identifier.
  - `profile_id` (`VARCHAR(255)` NOT NULL): Reference to station profile header.
  - `pressure_dbar` (`DOUBLE PRECISION` NULL): Ocean pressure in decibars (`decibar`). NULL for missing value.
  - `temperature_c` (`DOUBLE PRECISION` NULL): Water temperature at pressure in °C (`degree_Celsius`). NULL for missing value.
  - `salinity_psu` (`DOUBLE PRECISION` NULL): Practical salinity in PSU (`PSU`). NULL for missing value.

### 3.4 Table 4: `argo_doc_embeddings` (Future RAG Index)
Placeholder table for vector similarity retrieval over ingested ARGO manuals (Phase 7 RAG).
- **Primary Key:** `chunk_id` (`BIGSERIAL`)
- **Columns:** `document_title` (`VARCHAR(255)`), `section_title` (`VARCHAR(255)`), `chunk_content` (`TEXT`), `embedding` (`vector(1536)`), `metadata` (`JSONB`), `created_at` (`TIMESTAMPTZ`).

---

## 4. Entity Relationships & Cardinality

```
+------------------+             +--------------------+             +-------------------+
|   argo_floats    | 1         N |   argo_profiles    | 1         N | argo_measurements |
| platform_number  |<------------| platform_number    |<------------| profile_id        |
+------------------+ (1:N Rel)   | profile_id         | (1:N Rel)   | measurement_id    |
                                 +--------------------+             +-------------------+
```

- **Float to Profiles:** `1 : N` (One float platform records multiple profile station casts across its lifecycle).
- **Profile to Measurements:** `1 : N` (One profile cast contains between ~50 and ~1000 vertical pressure level measurements).

---

## 5. Constraints & Integrity Rules

1. **`unique_platform_profile_time`:** Enforces `UNIQUE(platform_number, profile_time)` on `argo_profiles`. Guaranteed by Phase 1 empirical verification (0 duplicates).
2. **`check_latitude_range`:** Enforces `-90.0 <= latitude <= 90.0` on `argo_profiles`.
3. **`check_longitude_range`:** Enforces `-180.0 <= longitude <= 180.0` on `argo_profiles`.
4. **`check_pressure_non_negative`:** Enforces `pressure_dbar IS NULL OR pressure_dbar >= 0.0` on `argo_measurements`.
5. **Foreign Key Cascade:** `ON DELETE CASCADE` enforced on all child table references.

---

## 6. Index Strategy & Optimization Rationale

| Index Name | Target Table | Target Columns | Index Type | Optimization Purpose |
| :--- | :--- | :--- | :--- | :--- |
| `idx_argo_profiles_location` | `argo_profiles` | `location` | **GIST** | Essential for PostGIS bounding box (`ST_Within`, `ST_MakeEnvelope`) and radial distance (`ST_DWithin`) queries. |
| `idx_argo_profiles_platform_time` | `argo_profiles` | `(platform_number, profile_time)` | **B-Tree** | Accelerates trajectory lookups and date-range filtering for specific float platforms. |
| `idx_argo_measurements_profile_pres` | `argo_measurements` | `(profile_id, pressure_dbar)` | **B-Tree** | Accelerates sub-surface profile joining and depth/pressure level filtering. |
| `idx_argo_measurements_temp` | `argo_measurements` | `temperature_c` | **Partial B-Tree** (`WHERE temp IS NOT NULL`) | Accelerates temperature threshold queries (e.g. `temperature_c > 28.0°C`). |
| `idx_argo_measurements_psal` | `argo_measurements` | `salinity_psu` | **Partial B-Tree** (`WHERE psal IS NOT NULL`) | Accelerates salinity threshold queries (e.g. `salinity_psu < 30.0 PSU`). |

---

## 7. PostGIS Spatial Strategy

- **Spatial Representation:** `GEOMETRY(Point, 4326)` representing WGS84 geographic coordinate points.
- **Dual Representation Strategy:** Both explicit numeric columns (`latitude`, `longitude`) and PostGIS geometry points (`location`) are stored in `argo_profiles`. This avoids forcing spatial decoding functions for basic tabular displays while enabling full spatial index acceleration for bounding box and radius queries.
- **Population:** Constructed via `ST_SetSRID(ST_MakePoint(longitude, latitude), 4326)`.

---

## 8. Source-to-Database Traceability Matrix

| Verified NetCDF Source Variable | Phase 1 Normalized Field | Target PostgreSQL Table | Target Database Column | Database Data Type |
| :--- | :--- | :--- | :--- | :--- |
| `PLATFORM_NUMBER` | `platform_number` | `argo_floats` / `argo_profiles` | `platform_number` | `VARCHAR(64)` |
| `time` | `profile_time` | `argo_profiles` | `profile_time` | `TIMESTAMPTZ` (UTC) |
| `latitude` | `latitude` | `argo_profiles` | `latitude` | `DOUBLE PRECISION` |
| `longitude` | `longitude` | `argo_profiles` | `longitude` | `DOUBLE PRECISION` |
| N/A (Derived Point) | N/A | `argo_profiles` | `location` | `GEOMETRY(Point, 4326)` |
| `PRES` | `pressure_dbar` | `argo_measurements` | `pressure_dbar` | `DOUBLE PRECISION` (Nullable) |
| `TEMP` | `temperature_c` | `argo_measurements` | `temperature_c` | `DOUBLE PRECISION` (Nullable) |
| `PSAL` | `salinity_psu` | `argo_measurements` | `salinity_psu` | `DOUBLE PRECISION` (Nullable) |

---

## 9. Security & AST Validation Considerations

- **Read-Only Database Role:** AI-generated SQL execution is executed using a restricted `floatchat_readonly` database user role granted `SELECT` permissions only.
- **Deterministic AST Security Gate:** As specified in `SECURITY_DESIGN.md`, all LLM-generated SQL queries are parsed by `sqlglot` prior to execution, rejecting any statement containing non-`SELECT` operations or non-whitelisted tables.

---

## 10. Container Environment Setup

Local development PostgreSQL + PostGIS container setup is managed via `docker-compose.yml`:
- **Image:** `postgis/postgis:15-3.3`
- **Container Name:** `floatchat_postgis_db`
- **Port Mapping:** `5432:5432`
- **Initialization DDL:** Automatically mounts `scripts/init-db.sql` into `/docker-entrypoint-initdb.d/init-db.sql`.

---

## 11. Future pgvector Boundary

- The `argo_doc_embeddings` table and `vector` extension are declared in `scripts/init-db.sql` for unified database infrastructure.
- Population of document vectors and vector search query integration are strictly deferred to **Phase 7 (Scientific RAG System)**.

---

## 12. Phase 2 Remaining Steps

- **Phase 2.1 (Current):** Database foundation planning, DDL schema, Docker Compose setup, schema validation tests. (COMPLETE)
- **Phase 2.2 (Next Step):** Data loading pipeline script (`scripts/load_parquet_to_postgis.py`) to bulk import `data/processed/*.parquet` into PostgreSQL tables, populate PostGIS `location` points, and verify database row counts.
