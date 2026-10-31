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


PROCESSED_2025_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "data", "processed_2025"))
FLOATS_2025_PATH = os.path.join(PROCESSED_2025_DIR, "floats.parquet")
PROFILES_2025_PATH = os.path.join(PROCESSED_2025_DIR, "profiles.parquet")
MEASUREMENTS_2025_PATH = os.path.join(PROCESSED_2025_DIR, "measurements.parquet")
REPORT_2025_PATH = os.path.join(PROCESSED_2025_DIR, "validation_report.json")


class TestIndependentValidation2025(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.df_f = pd.read_parquet(FLOATS_2025_PATH)
        cls.df_p = pd.read_parquet(PROFILES_2025_PATH)
        cls.df_m = pd.read_parquet(MEASUREMENTS_2025_PATH)

    def test_2025_file_existence(self):
        """2025 Validation 1: Verify all 4 required output files exist in data/processed_2025/."""
        self.assertTrue(os.path.exists(FLOATS_2025_PATH))
        self.assertTrue(os.path.exists(PROFILES_2025_PATH))
        self.assertTrue(os.path.exists(MEASUREMENTS_2025_PATH))
        self.assertTrue(os.path.exists(REPORT_2025_PATH))

    def test_2025_schemas(self):
        """2025 Validation 2: Verify exact physical Parquet schemas match canonical model."""
        self.assertListEqual(list(self.df_f.columns), ["platform_number"])
        self.assertListEqual(list(self.df_p.columns), ["profile_id", "platform_number", "profile_time", "latitude", "longitude"])
        self.assertListEqual(list(self.df_m.columns), ["measurement_id", "profile_id", "pressure_dbar", "temperature_c", "salinity_psu"])

        self.assertEqual(str(self.df_p["profile_time"].dt.tz), "UTC")

    def test_2025_row_counts(self):
        """2025 Validation 3: Verify row counts (24 floats, 43 profiles, 8,707 measurements)."""
        self.assertEqual(len(self.df_f), 24)
        self.assertEqual(len(self.df_p), 43)
        self.assertEqual(len(self.df_m), 8707)

    def test_2025_measurement_id_offsets_and_uniqueness(self):
        """2025 Validation 4: Verify measurement IDs span 17,340 to 26,046 with zero duplicates and zero 2024 collision."""
        self.assertEqual(self.df_m["measurement_id"].isna().sum(), 0)
        self.assertFalse(self.df_m["measurement_id"].duplicated().any())
        self.assertEqual(int(self.df_m["measurement_id"].min()), 17340)
        self.assertEqual(int(self.df_m["measurement_id"].max()), 26046)
        self.assertEqual(len(self.df_m), 8707)

        # Confirm non-overlapping with 2024 measurements
        df_m_2024 = pd.read_parquet(MEASUREMENTS_PATH)
        collision = set(self.df_m["measurement_id"]).intersection(set(df_m_2024["measurement_id"]))
        self.assertEqual(len(collision), 0)

    def test_2025_platform_integrity(self):
        """2025 Validation 5: Verify platform uniqueness, formatting, and referential integrity."""
        self.assertEqual(self.df_f["platform_number"].isna().sum(), 0)
        self.assertEqual((self.df_f["platform_number"] == "").sum(), 0)
        self.assertFalse(self.df_f["platform_number"].duplicated().any())

        orphan_platforms = set(self.df_p["platform_number"]) - set(self.df_f["platform_number"])
        self.assertEqual(len(orphan_platforms), 0)

    def test_2025_profile_integrity(self):
        """2025 Validation 6: Verify profile ID uniqueness, coordinate bounds, and timestamp ordering."""
        self.assertEqual(self.df_p["profile_id"].isna().sum(), 0)
        self.assertFalse(self.df_p["profile_id"].duplicated().any())

        # Coordinate bounds
        self.assertTrue((self.df_p["latitude"] >= 8.0).all() and (self.df_p["latitude"] <= 25.0).all())
        self.assertTrue((self.df_p["longitude"] >= 58.0).all() and (self.df_p["longitude"] <= 75.0).all())

        # Natural identity (platform_number, profile_time) uniqueness
        self.assertFalse(self.df_p.duplicated(subset=["platform_number", "profile_time"]).any())

    def test_2025_measurement_referential_integrity(self):
        """2025 Validation 7: Verify measurement referential integrity referencing valid 2025 profiles."""
        self.assertEqual(self.df_m["measurement_id"].isna().sum(), 0)
        self.assertFalse(self.df_m["measurement_id"].duplicated().any())

        orphan_measurements = set(self.df_m["profile_id"]) - set(self.df_p["profile_id"])
        self.assertEqual(len(orphan_measurements), 0)

    def test_2025_sentinel_absence(self):
        """2025 Validation 8: Verify 0 remaining 99999.0 sentinels in 2025 measurements."""
        for col in ["pressure_dbar", "temperature_c", "salinity_psu"]:
            self.assertEqual((self.df_m[col] == 99999.0).sum(), 0)

    def test_2025_null_counts_and_zero_prevention(self):
        """2025 Validation 9: Verify missing adjusted salinity preserved as NULL (not zeroed or sentinel-filled)."""
        self.assertEqual(self.df_m["pressure_dbar"].isna().sum(), 0)
        self.assertEqual(self.df_m["temperature_c"].isna().sum(), 0)
        self.assertEqual(self.df_m["salinity_psu"].isna().sum(), 4737)
        self.assertEqual((self.df_m["salinity_psu"] == 0.0).sum(), 0)

        self.assertEqual(self.df_p["latitude"].isna().sum(), 0)
        self.assertEqual(self.df_p["longitude"].isna().sum(), 0)

    def test_2025_measurement_ranges(self):
        """2025 Validation 10: Verify numeric observation parameter ranges for 2025 measurements."""
        valid_pres = self.df_m["pressure_dbar"].dropna()
        valid_temp = self.df_m["temperature_c"].dropna()
        valid_psal = self.df_m["salinity_psu"].dropna()

        self.assertTrue((valid_pres >= 0.0).all())
        self.assertAlmostEqual(float(valid_pres.max()), 2033.7, places=1)
        self.assertAlmostEqual(float(valid_temp.min()), 2.728, places=3)
        self.assertAlmostEqual(float(valid_temp.max()), 30.150, places=3)
        self.assertAlmostEqual(float(valid_psal.min()), 34.857, places=2)
        self.assertAlmostEqual(float(valid_psal.max()), 36.648, places=2)

    def test_2025_validation_report_consistency(self):
        """2025 Validation 11: Verify validation_report.json matches actual Parquet datasets."""
        import json
        with open(REPORT_2025_PATH, "r", encoding="utf-8") as f:
            report = json.load(f)

        self.assertEqual(report["output_measurement_count"], 8707)
        self.assertEqual(report["unique_platform_count"], 24)
        self.assertEqual(report["unique_profile_count"], 43)
        self.assertEqual(report["salinity_source_variable"], "PSAL_ADJUSTED")
        self.assertEqual(report["missing_values"]["salinity"], 4737)
        self.assertEqual(report["rejected_record_count"], 0)


if __name__ == "__main__":
    unittest.main()
