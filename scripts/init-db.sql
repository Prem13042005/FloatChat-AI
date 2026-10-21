-- ===================================================================
-- FloatChat Database Foundation Initialization DDL (Phase 2.1 / Phase 2.2)
-- PostgreSQL 15+ with PostGIS & pgvector
-- Target Engine: PostgreSQL 15+
-- ===================================================================

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
-- Maps from: PLATFORM_NUMBER
CREATE TABLE IF NOT EXISTS argo_floats (
    platform_number VARCHAR(64) PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- 3. Table 2: Station Profiles (argo_profiles)
-- Maps from: PLATFORM_NUMBER, time, latitude, longitude
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
-- Maps from: PRES, TEMP, PSAL
CREATE TABLE IF NOT EXISTS argo_measurements (
    measurement_id BIGINT PRIMARY KEY,
    profile_id VARCHAR(255) NOT NULL REFERENCES argo_profiles(profile_id) ON DELETE CASCADE,
    pressure_dbar DOUBLE PRECISION NULL,
    temperature_c DOUBLE PRECISION NULL,
    salinity_psu DOUBLE PRECISION NULL,
    CONSTRAINT check_pressure_non_negative CHECK (pressure_dbar IS NULL OR pressure_dbar >= 0.0)
);

-- 5. Table 4: pgvector Scientific Document Index (Future RAG Phase 7 Infrastructure)
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
            ALTER TABLE argo_doc_embeddings ADD COLUMN embedding vector(768);
        END IF;
    END IF;
END $$;

-- ===================================================================
-- Index Strategy
-- ===================================================================

-- Index 1: PostGIS Spatial GIST Index on Profile Geometry Point (if column exists)
DO $$ 
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name='argo_profiles' AND column_name='location'
    ) THEN
        EXECUTE 'CREATE INDEX IF NOT EXISTS idx_argo_profiles_location ON argo_profiles USING GIST (location);';
    END IF;
END $$;

-- Index 2: B-Tree Index on Platform ID & Timestamp for Temporal Range Filtering
CREATE INDEX IF NOT EXISTS idx_argo_profiles_platform_time 
ON argo_profiles (platform_number, profile_time);

-- Index 3: B-Tree Composite Index on Profile ID & Pressure for Sub-surface Filtering
CREATE INDEX IF NOT EXISTS idx_argo_measurements_profile_pres 
ON argo_measurements (profile_id, pressure_dbar);

-- Index 4: Partial B-Tree Indexes on Temperature & Salinity for Parameter Range Queries
CREATE INDEX IF NOT EXISTS idx_argo_measurements_temp 
ON argo_measurements (temperature_c) WHERE temperature_c IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_argo_measurements_psal 
ON argo_measurements (salinity_psu) WHERE salinity_psu IS NOT NULL;
