#!/usr/bin/env python3
"""
tests/test_validation.py

Phase 1.4 — Independent Quality Assurance Test Suite.
Performs automated assertions against data/processed/ output files:
- Physical schema verification
- Row counts
- Platform & Profile referential integrity
- Measurement referential integrity
- Coordinate bounds & profile consistency
- Sentinel absence (no remaining 99999.0)
- Exact NULL counts
- Measurement numeric ranges
"""

import sys
import os
import unittest
import pandas as pd

PROCESSED_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "data", "processed"))
FLOATS_PATH = os.path.join(PROCESSED_DIR, "floats.parquet")
PROFILES_PATH = os.path.join(PROCESSED_DIR, "profiles.parquet")
MEASUREMENTS_PATH = os.path.join(PROCESSED_DIR, "measurements.parquet")
REPORT_PATH = os.path.join(PROCESSED_DIR, "validation_report.json")

class TestIndependentValidation(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.df_f = pd.read_parquet(FLOATS_PATH)
        cls.df_p = pd.read_parquet(PROFILES_PATH)
        cls.df_m = pd.read_parquet(MEASUREMENTS_PATH)

    def test_file_existence(self):
        """Validation 1: Verify all 4 required output files exist."""
        self.assertTrue(os.path.exists(FLOATS_PATH))
        self.assertTrue(os.path.exists(PROFILES_PATH))
        self.assertTrue(os.path.exists(MEASUREMENTS_PATH))
        self.assertTrue(os.path.exists(REPORT_PATH))

    def test_schemas(self):
        """Validation 2: Verify exact physical Parquet schemas."""
        self.assertListEqual(list(self.df_f.columns), ["platform_number"])
        self.assertListEqual(list(self.df_p.columns), ["profile_id", "platform_number", "profile_time", "latitude", "longitude"])
        self.assertListEqual(list(self.df_m.columns), ["measurement_id", "profile_id", "pressure_dbar", "temperature_c", "salinity_psu"])

        self.assertEqual(str(self.df_p["profile_time"].dt.tz), "UTC")

    def test_row_counts(self):
        """Validation 3: Verify row counts (21 floats, 64 profiles, 17,339 measurements)."""
        self.assertEqual(len(self.df_f), 21)
        self.assertEqual(len(self.df_p), 64)
        self.assertEqual(len(self.df_m), 17339)

    def test_platform_integrity(self):
        """Validation 4: Verify platform uniqueness and string formatting."""
        self.assertEqual(self.df_f["platform_number"].isna().sum(), 0)
        self.assertEqual((self.df_f["platform_number"] == "").sum(), 0)
        self.assertFalse(self.df_f["platform_number"].duplicated().any())
        
        orphan_platforms = set(self.df_p["platform_number"]) - set(self.df_f["platform_number"])
        self.assertEqual(len(orphan_platforms), 0)

    def test_profile_integrity(self):
        """Validation 5: Verify profile ID uniqueness, coordinates, and natural identity."""
        self.assertEqual(self.df_p["profile_id"].isna().sum(), 0)
        self.assertFalse(self.df_p["profile_id"].duplicated().any())
        
        # Coordinate bounds
        self.assertTrue((self.df_p["latitude"] >= -90.0).all() and (self.df_p["latitude"] <= 90.0).all())
        self.assertTrue((self.df_p["longitude"] >= -180.0).all() and (self.df_p["longitude"] <= 180.0).all())

        # Natural identity (platform_number, profile_time) uniqueness
        self.assertFalse(self.df_p.duplicated(subset=["platform_number", "profile_time"]).any())

    def test_measurement_referential_integrity(self):
        """Validation 6: Verify measurement ID uniqueness and foreign key references."""
        self.assertEqual(self.df_m["measurement_id"].isna().sum(), 0)
        self.assertFalse(self.df_m["measurement_id"].duplicated().any())
        
        orphan_measurements = set(self.df_m["profile_id"]) - set(self.df_p["profile_id"])
        self.assertEqual(len(orphan_measurements), 0)

    def test_sentinel_absence(self):
        """Validation 8: Verify 0 remaining 99999.0 sentinels."""
        for col in ["pressure_dbar", "temperature_c", "salinity_psu"]:
            self.assertEqual((self.df_m[col] == 99999.0).sum(), 0)

    def test_null_counts(self):
        """Validation 9: Verify exact expected NULL counts."""
        self.assertEqual(self.df_m["pressure_dbar"].isna().sum(), 1)
        self.assertEqual(self.df_m["salinity_psu"].isna().sum(), 4)
        self.assertEqual(self.df_m["temperature_c"].isna().sum(), 0)
        self.assertEqual(self.df_p["latitude"].isna().sum(), 0)
        self.assertEqual(self.df_p["longitude"].isna().sum(), 0)

    def test_measurement_ranges(self):
        """Validation 7: Verify measurement numeric ranges."""
        valid_pres = self.df_m["pressure_dbar"].dropna()
        valid_temp = self.df_m["temperature_c"].dropna()
        valid_psal = self.df_m["salinity_psu"].dropna()

        self.assertTrue((valid_pres >= 0.0).all())
        self.assertAlmostEqual(float(valid_pres.max()), 2034.9, places=1)
        self.assertAlmostEqual(float(valid_temp.min()), 2.837, places=2)
        self.assertAlmostEqual(float(valid_temp.max()), 29.902, places=2)
        self.assertAlmostEqual(float(valid_psal.min()), 23.236, places=2)
        self.assertAlmostEqual(float(valid_psal.max()), 38.908, places=2)

if __name__ == "__main__":
    unittest.main()
