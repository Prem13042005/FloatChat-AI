#!/usr/bin/env python3
"""
tests/test_database_ingestion.py

Phase 2.2 — Automated Database Ingestion & Reconciliation Test Suite.
Verifies PostgreSQL/PostGIS database table state, row counts, foreign key integrity,
NULL preservation, numeric ranges, PostGIS geometries, and repeat loading idempotency.
"""

import sys
import os
import unittest
import pandas as pd

# Add scripts to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "scripts")))

from load_parquet_to_postgis import get_db_connection, run_loader

DATA_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "data", "processed"))
NC_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "Indian_ARGO_Floats_0f9d_516d_c560_U1788882326310.nc"))

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
            WHERE table_schema = 'public' AND table_name IN ('argo_floats', 'argo_profiles', 'argo_measurements');
        """)
        tables = [r[0] for r in cur.fetchall()]
        cur.close()
        self.assertEqual(len(tables), 3)

    def test_02_database_row_counts(self):
        """Verify exact expected row counts in PostgreSQL tables."""
        cur = self.conn.cursor()
        cur.execute("SELECT COUNT(*) FROM argo_floats;")
        floats_cnt = cur.fetchone()[0]

        cur.execute("SELECT COUNT(*) FROM argo_profiles;")
        profiles_cnt = cur.fetchone()[0]

        cur.execute("SELECT COUNT(*) FROM argo_measurements;")
        meas_cnt = cur.fetchone()[0]
        cur.close()

        self.assertEqual(floats_cnt, 21)
        self.assertEqual(profiles_cnt, 64)
        self.assertEqual(meas_cnt, 17339)

    def test_03_foreign_key_referential_integrity(self):
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

    def test_04_null_preservation_and_sentinel_absence(self):
        """Verify exact NULL counts and zero 99999.0 sentinels in DB."""
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

        self.assertEqual(null_pres, 1)
        self.assertEqual(null_temp, 0)
        self.assertEqual(null_psal, 4)
        self.assertEqual(sentinels, 0)

    def test_05_numeric_ranges(self):
        """Verify numeric observation parameter ranges in PostgreSQL."""
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
        self.assertAlmostEqual(float(min_t), 2.837, places=2)
        self.assertAlmostEqual(float(max_t), 29.902, places=2)
        self.assertAlmostEqual(float(min_s), 23.236, places=2)
        self.assertAlmostEqual(float(max_s), 38.908, places=2)

    def test_06_postgis_geometry_validity(self):
        """Verify PostGIS point geometry validity and SRID = 4326 if location column exists."""
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

    def test_07_idempotency_repeat_loading(self):
        """Verify re-running run_loader leaves database row counts 100% identical."""
        rec = run_loader(DATA_DIR)
        self.assertEqual(rec["count_floats"], 21)
        self.assertEqual(rec["count_profiles"], 64)
        self.assertEqual(rec["count_measurements"], 17339)

    def test_08_data_immutability(self):
        """Verify Phase 1 NetCDF dataset and processed Parquet files remain untouched."""
        self.assertTrue(os.path.exists(NC_PATH))
        self.assertEqual(os.path.getsize(NC_PATH), 751672)

        df_m = pd.read_parquet(os.path.join(DATA_DIR, "measurements.parquet"))
        self.assertEqual(len(df_m), 17339)

if __name__ == "__main__":
    unittest.main()
