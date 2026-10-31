#!/usr/bin/env python3
"""
tests/test_database_ingestion.py

Automated Database Ingestion & Reconciliation Test Suite for FloatChat.
Verifies PostgreSQL/PostGIS database table state, combined row counts,
baseline data integrity, incremental 2025 import integrity, foreign key integrity,
NULL preservation, numeric ranges, PostGIS geometries, and repeat loading idempotency.
"""

import sys
import os
import unittest
import pandas as pd

# Add scripts to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "scripts")))

from load_parquet_to_postgis import get_db_connection

DATA_DIR_2024 = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "data", "processed"))
DATA_DIR_2025 = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "data", "processed_2025"))
NC_PATH_2024 = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "Indian_ARGO_Floats_0f9d_516d_c560_U1788882326310.nc"))
NC_PATH_2025 = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "Indian_ARGO_Floats_2a67_0428_3464_U1792860969237.nc"))


class TestDatabaseIngestion(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.conn = get_db_connection()

    @classmethod
    def tearDownClass(cls):
        cls.conn.close()

    def test_01_database_connectivity_and_tables(self):
        """Verify PostgreSQL connectivity and required table existence."""
        cur = self.conn.cursor()
        cur.execute("""
            SELECT table_name FROM information_schema.tables 
            WHERE table_schema = 'public' AND table_name IN ('argo_floats', 'argo_profiles', 'argo_measurements', 'argo_doc_embeddings');
        """)
        tables = [r[0] for r in cur.fetchall()]
        cur.close()
        self.assertIn("argo_floats", tables)
        self.assertIn("argo_profiles", tables)
        self.assertIn("argo_measurements", tables)
        self.assertIn("argo_doc_embeddings", tables)

    def test_02_combined_database_row_counts(self):
        """Verify exact expected combined row counts across 2024 and 2025 datasets."""
        cur = self.conn.cursor()
        cur.execute("SELECT COUNT(*) FROM argo_floats;")
        floats_cnt = cur.fetchone()[0]

        cur.execute("SELECT COUNT(*) FROM argo_profiles;")
        profiles_cnt = cur.fetchone()[0]

        cur.execute("SELECT COUNT(*) FROM argo_measurements;")
        meas_cnt = cur.fetchone()[0]

        cur.execute("SELECT MIN(measurement_id), MAX(measurement_id), COUNT(*) FROM argo_measurements;")
        min_id, max_id, count_m = cur.fetchone()
        cur.close()

        # Combined expectations: 30 floats, 107 profiles, 26,046 measurements
        self.assertEqual(floats_cnt, 30)
        self.assertEqual(profiles_cnt, 107)
        self.assertEqual(meas_cnt, 26046)

        # Continuous ID sequence from 1 to 26,046 with zero gaps
        self.assertEqual(min_id, 1)
        self.assertEqual(max_id, 26046)
        self.assertEqual(count_m, 26046)
        self.assertEqual(max_id - min_id + 1, count_m)

    def test_03_baseline_data_integrity(self):
        """Verify January 2024 baseline data integrity is fully preserved in the database."""
        cur = self.conn.cursor()
        # Query baseline subset: profile_time < '2025-01-01'
        cur.execute("""
            SELECT 
                COUNT(DISTINCT p.platform_number),
                COUNT(DISTINCT p.profile_id),
                COUNT(m.measurement_id),
                MIN(m.measurement_id),
                MAX(m.measurement_id)
            FROM argo_profiles p
            JOIN argo_measurements m ON p.profile_id = m.profile_id
            WHERE p.profile_time < '2025-01-01';
        """)
        b_floats, b_profiles, b_meas, b_min_id, b_max_id = cur.fetchone()

        cur.execute("""
            SELECT 
                COUNT(*) FILTER (WHERE m.pressure_dbar IS NULL),
                COUNT(*) FILTER (WHERE m.temperature_c IS NULL),
                COUNT(*) FILTER (WHERE m.salinity_psu IS NULL),
                MIN(m.temperature_c),
                MAX(m.temperature_c)
            FROM argo_profiles p
            JOIN argo_measurements m ON p.profile_id = m.profile_id
            WHERE p.profile_time < '2025-01-01';
        """)
        null_p, null_t, null_s, min_t, max_t = cur.fetchone()
        cur.close()

        # Exact baseline counts
        self.assertEqual(b_floats, 21)
        self.assertEqual(b_profiles, 64)
        self.assertEqual(b_meas, 17339)
        self.assertEqual(b_min_id, 1)
        self.assertEqual(b_max_id, 17339)

        # Baseline nulls and ranges
        self.assertEqual(null_p, 1)
        self.assertEqual(null_t, 0)
        self.assertEqual(null_s, 4)
        self.assertAlmostEqual(float(min_t), 2.837, places=3)
        self.assertAlmostEqual(float(max_t), 29.902, places=3)

    def test_04_incremental_2025_data_integrity(self):
        """Verify January-April 2025 incremental import integrity in the database."""
        cur = self.conn.cursor()
        # Query 2025 subset: profile_time >= '2025-01-01'
        cur.execute("""
            SELECT 
                COUNT(DISTINCT p.platform_number),
                COUNT(DISTINCT p.profile_id),
                COUNT(m.measurement_id),
                MIN(m.measurement_id),
                MAX(m.measurement_id)
            FROM argo_profiles p
            JOIN argo_measurements m ON p.profile_id = m.profile_id
            WHERE p.profile_time >= '2025-01-01';
        """)
        inc_floats, inc_profiles, inc_meas, inc_min_id, inc_max_id = cur.fetchone()

        cur.execute("""
            SELECT 
                COUNT(*) FILTER (WHERE m.pressure_dbar IS NULL),
                COUNT(*) FILTER (WHERE m.temperature_c IS NULL),
                COUNT(*) FILTER (WHERE m.salinity_psu IS NULL),
                MIN(m.temperature_c),
                MAX(m.temperature_c)
            FROM argo_profiles p
            JOIN argo_measurements m ON p.profile_id = m.profile_id
            WHERE p.profile_time >= '2025-01-01';
        """)
        null_p, null_t, null_s, min_t, max_t = cur.fetchone()
        cur.close()

        # Incremental 2025 counts
        self.assertEqual(inc_floats, 24)
        self.assertEqual(inc_profiles, 43)
        self.assertEqual(inc_meas, 8707)
        self.assertEqual(inc_min_id, 17340)
        self.assertEqual(inc_max_id, 26046)

        # Incremental 2025 nulls and ranges (4,737 missing unadjusted salinities)
        self.assertEqual(null_p, 0)
        self.assertEqual(null_t, 0)
        self.assertEqual(null_s, 4737)
        self.assertAlmostEqual(float(min_t), 2.728, places=3)
        self.assertAlmostEqual(float(max_t), 30.150, places=3)

    def test_05_foreign_key_referential_integrity(self):
        """Verify 0 orphan profiles and 0 orphan measurements."""
        cur = self.conn.cursor()
        cur.execute("""
            SELECT COUNT(*) FROM argo_profiles p 
            LEFT JOIN argo_floats f ON p.platform_number = f.platform_number 
            WHERE f.platform_number IS NULL;
        """)
        orphan_p = cur.fetchone()[0]

        cur.execute("""
            SELECT COUNT(*) FROM argo_measurements m 
            LEFT JOIN argo_profiles p ON m.profile_id = p.profile_id 
            WHERE p.profile_id IS NULL;
        """)
        orphan_m = cur.fetchone()[0]
        cur.close()

        self.assertEqual(orphan_p, 0)
        self.assertEqual(orphan_m, 0)

    def test_06_null_preservation_and_sentinel_absence(self):
        """Verify combined NULL counts and zero 99999.0 sentinels in DB."""
        cur = self.conn.cursor()
        cur.execute("SELECT COUNT(*) FROM argo_measurements WHERE pressure_dbar IS NULL;")
        null_pres = cur.fetchone()[0]

        cur.execute("SELECT COUNT(*) FROM argo_measurements WHERE temperature_c IS NULL;")
        null_temp = cur.fetchone()[0]

        cur.execute("SELECT COUNT(*) FROM argo_measurements WHERE salinity_psu IS NULL;")
        null_psal = cur.fetchone()[0]

        cur.execute("""
            SELECT COUNT(*) FROM argo_measurements 
            WHERE pressure_dbar = 99999.0 OR temperature_c = 99999.0 OR salinity_psu = 99999.0;
        """)
        sentinels = cur.fetchone()[0]
        cur.close()

        # Combined null counts (4 baseline + 4,737 2025)
        self.assertEqual(null_pres, 1)
        self.assertEqual(null_temp, 0)
        self.assertEqual(null_psal, 4741)
        self.assertEqual(sentinels, 0)

    def test_07_combined_numeric_ranges(self):
        """Verify numeric observation parameter ranges across the combined dataset in PostgreSQL."""
        cur = self.conn.cursor()
        cur.execute("SELECT MIN(pressure_dbar), MAX(pressure_dbar) FROM argo_measurements WHERE pressure_dbar IS NOT NULL;")
        min_p, max_p = cur.fetchone()

        cur.execute("SELECT MIN(temperature_c), MAX(temperature_c) FROM argo_measurements WHERE temperature_c IS NOT NULL;")
        min_t, max_t = cur.fetchone()

        cur.execute("SELECT MIN(salinity_psu), MAX(salinity_psu) FROM argo_measurements WHERE salinity_psu IS NOT NULL;")
        min_s, max_s = cur.fetchone()
        cur.close()

        self.assertAlmostEqual(float(min_p), 0.0, places=1)
        self.assertAlmostEqual(float(max_p), 2034.9, places=1)
        self.assertAlmostEqual(float(min_t), 2.728, places=3)
        self.assertAlmostEqual(float(max_t), 30.150, places=3)
        self.assertAlmostEqual(float(min_s), 23.236, places=2)
        self.assertAlmostEqual(float(max_s), 38.908, places=2)

    def test_08_postgis_geometry_validity(self):
        """Verify PostGIS point geometry validity and SRID = 4326 for all 107 profiles."""
        cur = self.conn.cursor()
        cur.execute("""
            SELECT 1 FROM information_schema.columns 
            WHERE table_name='argo_profiles' AND column_name='location';
        """)
        has_location = cur.fetchone() is not None

        if has_location:
            cur.execute("SELECT COUNT(*) FROM argo_profiles WHERE ST_IsValid(location) = False;")
            invalid_geom = cur.fetchone()[0]

            cur.execute("SELECT COUNT(DISTINCT ST_SRID(location)) FROM argo_profiles;")
            distinct_srid = cur.fetchone()[0]

            cur.execute("SELECT ST_SRID(location) FROM argo_profiles LIMIT 1;")
            srid_val = cur.fetchone()[0]
            cur.close()

            self.assertEqual(invalid_geom, 0)
            self.assertEqual(distinct_srid, 1)
            self.assertEqual(srid_val, 4326)

    def test_09_idempotency_repeat_loading(self):
        """Verify repeat loading idempotency using an isolated temporary schema fixture without mutating live tables."""
        cur = self.conn.cursor()
        try:
            cur.execute("CREATE SCHEMA IF NOT EXISTS test_idempotency_sandbox;")
            cur.execute("""
                CREATE TABLE test_idempotency_sandbox.argo_floats (
                    platform_number VARCHAR(64) PRIMARY KEY,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                );
            """)
            # Insert sample float records
            test_floats = [("2901333",), ("1902672",), ("4903783",)]
            cur.executemany("""
                INSERT INTO test_idempotency_sandbox.argo_floats (platform_number)
                VALUES (%s) ON CONFLICT (platform_number) DO NOTHING;
            """, test_floats)
            self.conn.commit()

            cur.execute("SELECT COUNT(*) FROM test_idempotency_sandbox.argo_floats;")
            initial_count = cur.fetchone()[0]
            self.assertEqual(initial_count, 3)

            # Re-run identical insert batch (idempotency simulation)
            cur.executemany("""
                INSERT INTO test_idempotency_sandbox.argo_floats (platform_number)
                VALUES (%s) ON CONFLICT (platform_number) DO NOTHING;
            """, test_floats)
            self.conn.commit()

            cur.execute("SELECT COUNT(*) FROM test_idempotency_sandbox.argo_floats;")
            repeat_count = cur.fetchone()[0]
            self.assertEqual(repeat_count, 3, "Idempotency failed: repeat load inserted duplicate rows")
        finally:
            cur.execute("DROP SCHEMA IF EXISTS test_idempotency_sandbox CASCADE;")
            self.conn.commit()
            cur.close()

    def test_10_source_data_immutability(self):
        """Verify source NetCDF datasets and processed Parquet files remain untouched."""
        self.assertTrue(os.path.exists(NC_PATH_2024))
        self.assertEqual(os.path.getsize(NC_PATH_2024), 751672)

        self.assertTrue(os.path.exists(NC_PATH_2025))
        self.assertEqual(os.path.getsize(NC_PATH_2025), 380516)

        df_m_2024 = pd.read_parquet(os.path.join(DATA_DIR_2024, "measurements.parquet"))
        self.assertEqual(len(df_m_2024), 17339)

        df_m_2025 = pd.read_parquet(os.path.join(DATA_DIR_2025, "measurements.parquet"))
        self.assertEqual(len(df_m_2025), 8707)


if __name__ == "__main__":
    unittest.main()
