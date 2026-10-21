# FloatChat: Database Design & PostGIS / pgvector Specification

**Document Version:** 1.0.0  
**Phase:** Phase 0 (Architecture & Specification)  
**Status:** Approved Specification  

---

## 1. Source of Truth & Dataset Accuracy Principles

FloatChat adheres to strict data integrity principles:
1. **Numerical Source of Truth:** PostgreSQL with PostGIS extension is the absolute source of truth for physical oceanographic observation records.
2. **Authoritative Dataset Verification:** The development NetCDF file (`Indian_ARGO_Floats_0f9d_516d_c560_U1788882326310.nc`) is the authoritative reference dataset.
3. **Physical Parameter Terminology:**
   - `PRES` represents **ocean pressure** (in decibars / dbar), acting as a physical proxy for depth. It is **not** simply labeled as depth.
   - `TEMP` represents **water temperature at the observation pressure**. It is **not** labeled as sea-surface temperature unless the observation pressure is at the surface (e.g. `PRES` near 0 dbar).
4. **Strict Quality Control (QC) Variable Policy:**
   - **Verified NetCDF Observed Fields:** `PLATFORM_NUMBER`, `time`, `latitude`, `longitude`, `PRES`, `TEMP`, `PSAL`.
   - **Unverified Fields Policy:** Quality Control fields (e.g., `PRES_QC`, `TEMP_QC`, `PSAL_QC`, `POSITION_QC`, `JULD_QC`) are **not assumed to exist** prior to Phase 1 data pipeline verification. The database design cleanly separates verified NetCDF fields from proposed normalized table schemas.

---

## 2. Relational & Spatial Entity Model

The physical oceanographic database follows a normalized 3-tier relational hierarchy: `floats -> profiles -> measurements`, supplemented by an unstructured document embedding table for domain knowledge.

```
+-----------------------------------+
|            argo_floats            |  (Float Platform Metadata)
|  - platform_number VARCHAR(64) PK |
|  - created_at TIMESTAMPTZ         |
+-----------------------------------+
                  | 1
                  |
                  | N
+-----------------------------------+
|           argo_profiles           |  (Spatial-Temporal Profile Header)
|  - profile_id VARCHAR(255) PK     |  (Format: PROF_{platform}_{timestamp})
|  - platform_number VARCHAR(64) FK |
|  - profile_time TIMESTAMPTZ       |
|  - latitude DOUBLE PRECISION      |  (CHECK -90 to 90)
|  - longitude DOUBLE PRECISION     |  (CHECK -180 to 180)
|  - location GEOMETRY(Point, 4326) |  (PostGIS Point geometry, conditional)
+-----------------------------------+
                  | 1
                  |
                  | N
+-----------------------------------+
|         argo_measurements         |  (Sub-surface Observation Levels)
|  - measurement_id BIGINT PK       |
|  - profile_id VARCHAR(255) FK     |
|  - pressure_dbar DOUBLE PRECISION |  (Ocean Pressure in dbar, CHECK >= 0)
|  - temperature_c DOUBLE PRECISION |  (Water Temperature in °C)
|  - salinity_psu DOUBLE PRECISION  |  (Practical Salinity in PSU)
+-----------------------------------+

+-----------------------------------+
|        argo_doc_embeddings        |  (Scientific Document Retrieval Index)
|  - chunk_id BIGSERIAL PK          |
|  - document_title VARCHAR(255)    |
|  - section_title VARCHAR(255)     |
|  - chunk_content TEXT             |
|  - embedding vector(1536)         |  (pgvector embedding, conditional)
|  - metadata JSONB                 |
|  - created_at TIMESTAMPTZ         |
+-----------------------------------+
```

*Domain Slot Mapping Notice:* The high-level `QueryIntent.wmo_ids` slot extracted by the Query Understanding Agent maps directly to the physical database column `argo_floats.platform_number` (and foreign key `argo_profiles.platform_number`).

---

## 3. Physical Schema DDL Definitions

### 3.1 NetCDF Source Fields to Physical Database Columns

| NetCDF Observed Field | Physical Table Name | Physical Column Name | Physical Data Type | Constraints & Notes |
| :--- | :--- | :--- | :--- | :--- |
| `PLATFORM_NUMBER` | `argo_floats` | `platform_number` | `VARCHAR(64)` | Primary Key, stripped string |
| *(Generated)* | `argo_floats` | `created_at` | `TIMESTAMPTZ` | `DEFAULT CURRENT_TIMESTAMP` |
| *(Composite Key)* | `argo_profiles` | `profile_id` | `VARCHAR(255)` | Primary Key (`PROF_{platform}_{timestamp}`) |
| `PLATFORM_NUMBER` | `argo_profiles` | `platform_number` | `VARCHAR(64)` | Foreign Key $\to$ `argo_floats(platform_number)` |
| `time` | `argo_profiles` | `profile_time` | `TIMESTAMPTZ` | Not Null, UTC timezone-aware |
| `latitude` | `argo_profiles` | `latitude` | `DOUBLE PRECISION` | Not Null, `CHECK (latitude >= -90 AND <= 90)` |
| `longitude` | `argo_profiles` | `longitude` | `DOUBLE PRECISION` | Not Null, `CHECK (longitude >= -180 AND <= 180)` |
| `latitude`, `longitude` | `argo_profiles` | `location` | `GEOMETRY(Point, 4326)` | PostGIS Point geometry (conditional on extension) |
| *(Natural Sequence)* | `argo_measurements` | `measurement_id` | `BIGINT` | Primary Key |
| *(Composite Ref)* | `argo_measurements` | `profile_id` | `VARCHAR(255)` | Foreign Key $\to$ `argo_profiles(profile_id)` |
| `PRES` | `argo_measurements` | `pressure_dbar` | `DOUBLE PRECISION` | Ocean Pressure (dbar), `CHECK (>= 0 OR NULL)` |
| `TEMP` | `argo_measurements` | `temperature_c` | `DOUBLE PRECISION` | Water Temperature (°C) at observation pressure |
| `PSAL` | `argo_measurements` | `salinity_psu` | `DOUBLE PRECISION` | Practical Salinity (PSU) |

### 3.2 Physical DDL Implementation (`scripts/init-db.sql`)

```sql
-- 1. Enable Required Extensions safely
DO $$ 
BEGIN
    CREATE EXTENSION IF NOT EXISTS postgis;
EXCEPTION WHEN OTHERS THEN
    RAISE NOTICE 'PostGIS extension unavailable on host server; spatial fallback mode.';
END $$;

DO $$ 
BEGIN
    CREATE EXTENSION IF NOT EXISTS vector;
EXCEPTION WHEN OTHERS THEN
    RAISE NOTICE 'pgvector extension unavailable on host server; vector fallback mode.';
END $$;

-- 2. Table 1: Float Platforms (argo_floats)
CREATE TABLE IF NOT EXISTS argo_floats (
    platform_number VARCHAR(64) PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- 3. Table 2: Station Profiles (argo_profiles)
CREATE TABLE IF NOT EXISTS argo_profiles (
    profile_id VARCHAR(255) PRIMARY KEY,
    platform_number VARCHAR(64) NOT NULL REFERENCES argo_floats(platform_number) ON DELETE CASCADE,
    profile_time TIMESTAMPTZ NOT NULL,
    latitude DOUBLE PRECISION NOT NULL,
    longitude DOUBLE PRECISION NOT NULL,
    CONSTRAINT unique_platform_profile_time UNIQUE (platform_number, profile_time),
    CONSTRAINT check_latitude_range CHECK (latitude >= -90.0 AND latitude <= 90.0),
    CONSTRAINT check_longitude_range CHECK (longitude >= -180.0 AND longitude <= 180.0)
);

-- Conditionally add PostGIS location column if PostGIS extension exists
DO $$ 
BEGIN
    IF EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'postgis') THEN
        IF NOT EXISTS (
            SELECT 1 FROM information_schema.columns 
            WHERE table_name='argo_profiles' AND column_name='location'
        ) THEN
            ALTER TABLE argo_profiles ADD COLUMN location GEOMETRY(Point, 4326);
        END IF;
    END IF;
END $$;

-- 4. Table 3: Ocean Sub-surface Measurements (argo_measurements)
CREATE TABLE IF NOT EXISTS argo_measurements (
    measurement_id BIGINT PRIMARY KEY,
    profile_id VARCHAR(255) NOT NULL REFERENCES argo_profiles(profile_id) ON DELETE CASCADE,
    pressure_dbar DOUBLE PRECISION NULL,
    temperature_c DOUBLE PRECISION NULL,
    salinity_psu DOUBLE PRECISION NULL,
    CONSTRAINT check_pressure_non_negative CHECK (pressure_dbar IS NULL OR pressure_dbar >= 0.0)
);

-- 5. Table 4: pgvector Scientific Document Index
CREATE TABLE IF NOT EXISTS argo_doc_embeddings (
    chunk_id BIGSERIAL PRIMARY KEY,
    document_title VARCHAR(255) NOT NULL,
    section_title VARCHAR(255),
    chunk_content TEXT NOT NULL,
    metadata JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Add embedding vector column conditionally if pgvector extension exists
DO $$ 
BEGIN
    IF EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'vector') THEN
        IF NOT EXISTS (
            SELECT 1 FROM information_schema.columns 
            WHERE table_name='argo_doc_embeddings' AND column_name='embedding'
        ) THEN
            ALTER TABLE argo_doc_embeddings ADD COLUMN embedding vector(1536);
        END IF;
    END IF;
END $$;
```

> **Environment Extension Notice:** In local host PostgreSQL environments lacking compiled PostGIS or pgvector extensions, `scripts/init-db.sql` catches extension creation exceptions cleanly and creates relational tables without crashing. In such host environments, `location` and `embedding` columns are skipped, and queries filter coordinates using `latitude BETWEEN ... AND ...` and `longitude BETWEEN ... AND ...`. In the official containerized Docker environment (`docker-compose.yml`), PostGIS and pgvector are fully enabled.

---

## 4. Indexing & Query Patterns

### Spatial & Relational Index Strategy
```sql
-- Spatial GIST Index on Profile Location Geometry (if column exists)
CREATE INDEX IF NOT EXISTS idx_argo_profiles_location ON argo_profiles USING GIST (location);

-- B-Tree Composite Index on Platform Number & Profile Timestamp
CREATE INDEX IF NOT EXISTS idx_argo_profiles_platform_time ON argo_profiles (platform_number, profile_time);

-- B-Tree Composite Index on Profile ID & Pressure
CREATE INDEX IF NOT EXISTS idx_argo_measurements_profile_pres ON argo_measurements (profile_id, pressure_dbar);

-- Partial B-Tree Indexes on Temperature & Salinity for Parameter Range Filtering
CREATE INDEX IF NOT EXISTS idx_argo_measurements_temp ON argo_measurements (temperature_c) WHERE temperature_c IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_argo_measurements_psal ON argo_measurements (salinity_psu) WHERE salinity_psu IS NOT NULL;
```

### Verified SQL Query Patterns

1. **Bounding Box Spatial Query (PostGIS):**
   ```sql
   SELECT p.platform_number, p.profile_time, p.latitude, p.longitude, m.pressure_dbar, m.temperature_c, m.salinity_psu
   FROM argo_profiles p
   JOIN argo_measurements m ON p.profile_id = m.profile_id
   WHERE ST_Within(p.location, ST_MakeEnvelope(60.0, -10.0, 80.0, 10.0, 4326))
     AND m.pressure_dbar BETWEEN 0 AND 200
   LIMIT 500;
   ```

2. **Bounding Box Query (Coordinate Fallback):**
   ```sql
   SELECT p.platform_number, p.profile_time, p.latitude, p.longitude, m.pressure_dbar, m.temperature_c, m.salinity_psu
   FROM argo_profiles p
   JOIN argo_measurements m ON p.profile_id = m.profile_id
   WHERE p.latitude BETWEEN -10.0 AND 10.0
     AND p.longitude BETWEEN 60.0 AND 80.0
     AND m.pressure_dbar BETWEEN 0 AND 200
   LIMIT 500;
   ```

3. **Platform-Specific Profile Retrieval:**
   ```sql
   SELECT p.profile_id, p.profile_time, m.pressure_dbar, m.temperature_c, m.salinity_psu
   FROM argo_profiles p
   JOIN argo_measurements m ON p.profile_id = m.profile_id
   WHERE p.platform_number = '2901550'
   ORDER BY p.profile_time DESC, m.pressure_dbar ASC
   LIMIT 500;
   ```

---

## 5. pgvector Scope & Vector Storage Strategy

- `pgvector` operates inside the **same PostgreSQL database instance**, eliminating the need for external vector databases (such as ChromaDB, Pinecone, or Qdrant).
- `pgvector` acts as **retrieval index infrastructure**, storing document chunk vectors for similarity search.
- The embedding model, chunking strategy, and vector index parameters will be empirically benchmarked during Phase 7/8 (Scientific Knowledge & Response Agent Phase).
