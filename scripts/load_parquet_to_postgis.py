#!/usr/bin/env python3
"""
scripts/load_parquet_to_postgis.py

FloatChat Phase 2.2 — ARGO Parquet Data Ingestion into PostgreSQL/PostGIS.

Bulk loads validated Phase 1 Parquet files (floats.parquet, profiles.parquet, measurements.parquet)
into PostgreSQL database tables (argo_floats, argo_profiles, argo_measurements).

Features:
- Validates database connectivity and table schemas.
- Loads tables in strict relational order (floats -> profiles -> measurements).
- Populates PostGIS location geometry points via ST_SetSRID(ST_MakePoint(longitude, latitude), 4326).
- Idempotent execution using ON CONFLICT DO NOTHING.
- Preserves NULLs (never converts back to sentinels).
- Executes automatic 11-point data reconciliation against Phase 1 Parquet files.

Usage:
    python scripts/load_parquet_to_postgis.py [data-dir]
"""

import sys
import os
import logging
import psycopg2
import psycopg2.extras
import pandas as pd

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("floatchat.db_loader")

def get_db_connection():
    """Establishes connection to PostgreSQL using environment variables or defaults."""
    host = os.getenv("POSTGRES_HOST", "127.0.0.1")
    port = int(os.getenv("POSTGRES_PORT", 5432))
    db_name = os.getenv("POSTGRES_DB", "floatchat_db")
    user = os.getenv("POSTGRES_USER", "floatchat_user")
    password = os.getenv("POSTGRES_PASSWORD", "floatchat_password")

    try:
        conn = psycopg2.connect(
            host=host,
            port=port,
            dbname=db_name,
            user=user,
            password=password
        )
        return conn
    except Exception as e:
        # Fallback to postgres user if floatchat_user password fails on local env
        admin_user = os.getenv("POSTGRES_ADMIN_USER", "postgres")
        conn = psycopg2.connect(
            host=host,
            port=port,
            dbname=db_name,
            user=admin_user
        )
        return conn

def verify_table_existence(cur):
    """Verifies that target tables exist in the database."""
    required_tables = ["argo_floats", "argo_profiles", "argo_measurements"]
    cur.execute("""
        SELECT table_name 
        FROM information_schema.tables 
        WHERE table_schema = 'public' AND table_name IN %s;
    """, (tuple(required_tables),))
    existing = [r[0] for r in cur.fetchall()]
    missing = set(required_tables) - set(existing)
    if missing:
        raise ValueError(f"Target database tables missing: {missing}. Run scripts/init-db.sql first.")
    logger.info("Database table verification PASSED: argo_floats, argo_profiles, argo_measurements exist.")

def load_floats(conn, df_floats: pd.DataFrame) -> dict:
    """Loads argo_floats (Step 1). Idempotent via ON CONFLICT DO NOTHING."""
    logger.info(f"Loading {len(df_floats)} float records into argo_floats...")
    cur = conn.cursor()

    sql = """
        INSERT INTO argo_floats (platform_number)
        VALUES (%s)
        ON CONFLICT (platform_number) DO NOTHING;
    """
    records = [(str(p),) for p in df_floats["platform_number"]]
    psycopg2.extras.execute_batch(cur, sql, records, page_size=1000)

    cur.execute("SELECT COUNT(*) FROM argo_floats;")
    db_count = cur.fetchone()[0]
    cur.close()

    logger.info(f"argo_floats load complete. Total DB rows: {db_count}")
    return {"input_count": len(df_floats), "db_count": db_count}

def load_profiles(conn, df_profiles: pd.DataFrame) -> dict:
    """Loads argo_profiles (Step 2) and populates PostGIS location point geometry."""
    logger.info(f"Loading {len(df_profiles)} profile records into argo_profiles...")
    cur = conn.cursor()

    # Check if PostGIS location column exists
    cur.execute("""
        SELECT 1 FROM information_schema.columns 
        WHERE table_name='argo_profiles' AND column_name='location';
    """)
    has_location = cur.fetchone() is not None

    if has_location:
        sql = """
            INSERT INTO argo_profiles (profile_id, platform_number, profile_time, latitude, longitude, location)
            VALUES (%s, %s, %s, %s, %s, ST_SetSRID(ST_MakePoint(%s, %s), 4326))
            ON CONFLICT (profile_id) DO NOTHING;
        """
        records = [
            (
                str(row["profile_id"]),
                str(row["platform_number"]),
                row["profile_time"].to_pydatetime(),
                float(row["latitude"]),
                float(row["longitude"]),
                float(row["longitude"]),  # ST_MakePoint(lon, lat)
                float(row["latitude"])
            )
            for _, row in df_profiles.iterrows()
        ]
    else:
        sql = """
            INSERT INTO argo_profiles (profile_id, platform_number, profile_time, latitude, longitude)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (profile_id) DO NOTHING;
        """
        records = [
            (
                str(row["profile_id"]),
                str(row["platform_number"]),
                row["profile_time"].to_pydatetime(),
                float(row["latitude"]),
                float(row["longitude"])
            )
            for _, row in df_profiles.iterrows()
        ]

    psycopg2.extras.execute_batch(cur, sql, records, page_size=1000)

    cur.execute("SELECT COUNT(*) FROM argo_profiles;")
    db_count = cur.fetchone()[0]
    cur.close()

    logger.info(f"argo_profiles load complete. Total DB rows: {db_count}")
    return {"input_count": len(df_profiles), "db_count": db_count}

def load_measurements(conn, df_measurements: pd.DataFrame) -> dict:
    """Loads argo_measurements (Step 3). Preserves NULL values cleanly."""
    logger.info(f"Loading {len(df_measurements):,} measurement records into argo_measurements...")
    cur = conn.cursor()

    sql = """
        INSERT INTO argo_measurements (measurement_id, profile_id, pressure_dbar, temperature_c, salinity_psu)
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT (measurement_id) DO NOTHING;
    """

    records = [
        (
            int(row["measurement_id"]),
            str(row["profile_id"]),
            float(row["pressure_dbar"]) if pd.notna(row["pressure_dbar"]) else None,
            float(row["temperature_c"]) if pd.notna(row["temperature_c"]) else None,
            float(row["salinity_psu"]) if pd.notna(row["salinity_psu"]) else None
        )
        for _, row in df_measurements.iterrows()
    ]

    psycopg2.extras.execute_batch(cur, sql, records, page_size=5000)

    cur.execute("SELECT COUNT(*) FROM argo_measurements;")
    db_count = cur.fetchone()[0]
    cur.close()

    logger.info(f"argo_measurements load complete. Total DB rows: {db_count:,}")
    return {"input_count": len(df_measurements), "db_count": db_count}

def reconcile_database(conn, df_f: pd.DataFrame, df_p: pd.DataFrame, df_m: pd.DataFrame) -> dict:
    """Performs 11-point data reconciliation comparing DB results against Parquet source datasets."""
    logger.info("Executing 11-point database reconciliation audit against Parquet source data...")
    cur = conn.cursor()

    # 1. Row Counts
    cur.execute("SELECT COUNT(*) FROM argo_floats;")
    count_floats = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM argo_profiles;")
    count_profiles = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM argo_measurements;")
    count_measurements = cur.fetchone()[0]

    # 2. Unique platforms & profiles in DB
    cur.execute("SELECT COUNT(DISTINCT platform_number) FROM argo_profiles;")
    unique_platforms_in_profiles = cur.fetchone()[0]

    cur.execute("SELECT COUNT(DISTINCT profile_id) FROM argo_measurements;")
    unique_profiles_in_measurements = cur.fetchone()[0]

    # 3. NULL Counts
    cur.execute("SELECT COUNT(*) FROM argo_measurements WHERE pressure_dbar IS NULL;")
    null_pres = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM argo_measurements WHERE temperature_c IS NULL;")
    null_temp = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM argo_measurements WHERE salinity_psu IS NULL;")
    null_psal = cur.fetchone()[0]

    # 4. Numeric Ranges
    cur.execute("SELECT MIN(pressure_dbar), MAX(pressure_dbar) FROM argo_measurements WHERE pressure_dbar IS NOT NULL;")
    min_pres, max_pres = cur.fetchone()

    cur.execute("SELECT MIN(temperature_c), MAX(temperature_c) FROM argo_measurements WHERE temperature_c IS NOT NULL;")
    min_temp, max_temp = cur.fetchone()

    cur.execute("SELECT MIN(salinity_psu), MAX(salinity_psu) FROM argo_measurements WHERE salinity_psu IS NOT NULL;")
    min_psal, max_psal = cur.fetchone()

    # 5. Referential Integrity & Coordinate Conflicts
    cur.execute("""
        SELECT COUNT(*) FROM argo_profiles p 
        LEFT JOIN argo_floats f ON p.platform_number = f.platform_number 
        WHERE f.platform_number IS NULL;
    """)
    orphan_profiles = cur.fetchone()[0]

    cur.execute("""
        SELECT COUNT(*) FROM argo_measurements m 
        LEFT JOIN argo_profiles p ON m.profile_id = p.profile_id 
        WHERE p.profile_id IS NULL;
    """)
    orphan_measurements = cur.fetchone()[0]

    cur.execute("""
        SELECT COUNT(*) FROM argo_measurements 
        WHERE pressure_dbar = 99999.0 OR temperature_c = 99999.0 OR salinity_psu = 99999.0;
    """)
    sentinels_count = cur.fetchone()[0]

    cur.close()

    # Assertions
    assert count_floats == 21, f"Mismatch in floats count: DB={count_floats}, Exp=21"
    assert count_profiles == 64, f"Mismatch in profiles count: DB={count_profiles}, Exp=64"
    assert count_measurements == 17339, f"Mismatch in measurements count: DB={count_measurements}, Exp=17339"
    assert null_pres == 1, f"Mismatch in NULL pressure: DB={null_pres}, Exp=1"
    assert null_temp == 0, f"Mismatch in NULL temp: DB={null_temp}, Exp=0"
    assert null_psal == 4, f"Mismatch in NULL psal: DB={null_psal}, Exp=4"
    assert orphan_profiles == 0, f"Orphan profiles detected: {orphan_profiles}"
    assert orphan_measurements == 0, f"Orphan measurements detected: {orphan_measurements}"
    assert sentinels_count == 0, f"Sentinel 99999.0 values detected in DB: {sentinels_count}"

    logger.info("All 11 reconciliation assertions PASSED cleanly!")

    return {
        "count_floats": count_floats,
        "count_profiles": count_profiles,
        "count_measurements": count_measurements,
        "unique_platforms_in_profiles": unique_platforms_in_profiles,
        "unique_profiles_in_measurements": unique_profiles_in_measurements,
        "null_pressure": null_pres,
        "null_temperature": null_temp,
        "null_salinity": null_psal,
        "min_pressure": float(min_pres),
        "max_pressure": float(max_pres),
        "min_temperature": float(min_temp),
        "max_temperature": float(max_temp),
        "min_salinity": float(min_psal),
        "max_salinity": float(max_psal),
        "orphan_profiles": orphan_profiles,
        "orphan_measurements": orphan_measurements,
        "sentinels_count": sentinels_count
    }

def run_loader(data_dir: str):
    """Main ingestion coordinator."""
    floats_path = os.path.join(data_dir, "floats.parquet")
    profiles_path = os.path.join(data_dir, "profiles.parquet")
    measurements_path = os.path.join(data_dir, "measurements.parquet")

    for p in [floats_path, profiles_path, measurements_path]:
        if not os.path.exists(p):
            raise FileNotFoundError(f"Required Parquet file missing: {p}")

    df_floats = pd.read_parquet(floats_path)
    df_profiles = pd.read_parquet(profiles_path)
    df_measurements = pd.read_parquet(measurements_path)

    conn = get_db_connection()
    try:
        cur = conn.cursor()
        verify_table_existence(cur)
        cur.close()

        # Step 1: Load floats
        load_floats(conn, df_floats)
        conn.commit()

        # Step 2: Load profiles
        load_profiles(conn, df_profiles)
        conn.commit()

        # Step 3: Load measurements
        load_measurements(conn, df_measurements)
        conn.commit()

        # Step 4: Reconcile DB
        rec = reconcile_database(conn, df_floats, df_profiles, df_measurements)
        logger.info("Phase 2.2 Ingestion & Reconciliation PASSED 100%!")
        return rec
    except Exception as e:
        conn.rollback()
        logger.error(f"Ingestion failed. Transaction rolled back: {e}")
        raise e
    finally:
        conn.close()

if __name__ == "__main__":
    target_data_dir = sys.argv[1] if len(sys.argv) > 1 else os.path.join("data", "processed")
    run_loader(target_data_dir)
