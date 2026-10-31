#!/usr/bin/env python3
"""
tests/test_pipeline.py

Unit and integration test suite for FloatChat Phase 1.3 ARGO Data Pipeline.
Ensures deterministic normalization, validation rules, Parquet generation,
and validation report creation without modifying the source NetCDF dataset.
"""

import sys
import os
import json
import unittest
import numpy as np
import pandas as pd

# Add scripts directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "scripts")))

from normalize_argo_dataset import load_and_normalize_netcdf, run_pipeline
from validate_argo_data import (
    validate_structural_integrity,
    validate_coordinates,
    validate_timestamps,
    perform_duplicate_analysis,
    compute_summary_statistics
)

NC_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "Indian_ARGO_Floats_0f9d_516d_c560_U1788882326310.nc"))
TEST_OUTPUT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "data", "processed"))

class TestARGOPipeline(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.raw_df = load_and_normalize_netcdf(NC_PATH)

    def test_platform_string_normalization(self):
        """Verify platform numbers are strings, stripped of whitespace padding, matching WMO format."""
        platforms = self.raw_df["platform_number"].unique()
        self.assertEqual(len(platforms), 21)
        for p in platforms:
            self.assertIsInstance(p, str)
            self.assertEqual(p, p.strip())
            self.assertTrue(len(p) >= 5)

    def test_timestamp_utc_conversion(self):
        """Verify timestamps are converted to timezone-aware UTC datetime."""
        profile_times = self.raw_df["profile_time"]
        self.assertTrue(pd.api.types.is_datetime64_any_dtype(profile_times))
        self.assertEqual(str(profile_times.dt.tz), "UTC")
        self.assertFalse(profile_times.isna().any())

    def test_sentinel_to_null_conversion(self):
        """Verify 99999.0 sentinels convert to NaN/NULL."""
        self.assertEqual(self.raw_df["pressure_dbar"].isna().sum(), 1)
        self.assertEqual(self.raw_df["salinity_psu"].isna().sum(), 4)
        self.assertEqual(self.raw_df["temperature_c"].isna().sum(), 0)

    def test_latitude_longitude_validation(self):
        """Verify coordinates are within WGS84 bounds."""
        coord_res = validate_coordinates(self.raw_df)
        self.assertEqual(coord_res["invalid_latitude_count"], 0)
        self.assertEqual(coord_res["invalid_longitude_count"], 0)
        self.assertEqual(coord_res["profile_coordinate_conflicts"], 0)

    def test_profile_grouping(self):
        """Verify profile grouping yields exactly 64 profiles."""
        groups = self.raw_df.groupby(["platform_number", "profile_time"])
        self.assertEqual(len(groups), 64)

    def test_duplicate_detection(self):
        """Verify duplicate detection identifies 0 exact and candidate duplicates."""
        dup_res = perform_duplicate_analysis(self.raw_df)
        self.assertEqual(dup_res["exact_duplicates"], 0)
        self.assertEqual(dup_res["duplicate_candidate_groups"], 0)
        self.assertEqual(dup_res["conflicting_measurements"], 0)

    def test_pipeline_execution_and_parquet_output(self):
        """Integration test executing run_pipeline and verifying Parquet files + JSON report."""
        report = run_pipeline(NC_PATH, TEST_OUTPUT_DIR)
        
        # Check expected counts
        self.assertEqual(report["input_row_count"], 17339)
        self.assertEqual(report["output_measurement_count"], 17339)
        self.assertEqual(report["unique_platform_count"], 21)
        self.assertEqual(report["unique_profile_count"], 64)
        self.assertEqual(report["rejected_record_count"], 0)
        
        self.assertEqual(report["missing_values"]["pressure"], 1)
        self.assertEqual(report["missing_values"]["salinity"], 4)
        self.assertEqual(report["missing_values"]["temperature"], 0)

        # Check output Parquet file existence
        floats_p = os.path.join(TEST_OUTPUT_DIR, "floats.parquet")
        profiles_p = os.path.join(TEST_OUTPUT_DIR, "profiles.parquet")
        measurements_p = os.path.join(TEST_OUTPUT_DIR, "measurements.parquet")
        report_json_p = os.path.join(TEST_OUTPUT_DIR, "validation_report.json")

        self.assertTrue(os.path.exists(floats_p))
        self.assertTrue(os.path.exists(profiles_p))
        self.assertTrue(os.path.exists(measurements_p))
        self.assertTrue(os.path.exists(report_json_p))

        # Check schema of Parquet files
        df_f = pd.read_parquet(floats_p)
        df_p = pd.read_parquet(profiles_p)
        df_m = pd.read_parquet(measurements_p)

        self.assertEqual(len(df_f), 21)
        self.assertEqual(len(df_p), 64)
        self.assertEqual(len(df_m), 17339)

        self.assertIn("platform_number", df_f.columns)
        self.assertIn("profile_id", df_p.columns)
        self.assertIn("measurement_id", df_m.columns)


NC_PATH_2025 = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "Indian_ARGO_Floats_2a67_0428_3464_U1792860969237.nc"))
PROCESSED_2025_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "data", "processed_2025"))


class TestIncrementalPipelinePreparation(unittest.TestCase):
    """
    Focused test suite for Phase E1:
    - PSAL vs PSAL_ADJUSTED source variable normalization
    - Preservation of missing adjusted salinity as nulls
    - Collision-safe measurement ID generation and collision guardrails
    - Preservation of original Phase 1 processed Parquet files
    """

    def test_psal_source_variable_normalization(self):
        """Verify normalization uses PSAL when present (2024 file)."""
        df_2024 = load_and_normalize_netcdf(NC_PATH)
        self.assertEqual(df_2024.attrs.get("salinity_source_variable"), "PSAL")
        self.assertIn("salinity_psu", df_2024.columns)
        self.assertEqual(df_2024["salinity_psu"].isna().sum(), 4)

    def test_psal_adjusted_source_variable_normalization(self):
        """Verify normalization dynamically detects PSAL_ADJUSTED and maps to salinity_psu (2025 file)."""
        df_2025 = load_and_normalize_netcdf(NC_PATH_2025)
        self.assertEqual(df_2025.attrs.get("salinity_source_variable"), "PSAL_ADJUSTED")
        self.assertIn("salinity_psu", df_2025.columns)
        self.assertNotIn("PSAL_ADJUSTED", df_2025.columns)

    def test_missing_adjusted_salinity_preserved_as_null(self):
        """Verify 4,737 missing adjusted salinity values remain null (no zeroes or sentinels)."""
        df_2025 = load_and_normalize_netcdf(NC_PATH_2025)
        null_count = df_2025["salinity_psu"].isna().sum()
        self.assertEqual(null_count, 4737)
        # Ensure no remaining 99999.0 sentinels or 0.0 placeholders
        self.assertEqual((df_2025["salinity_psu"] == 99999.0).sum(), 0)
        self.assertEqual((df_2025["salinity_psu"] == 0.0).sum(), 0)

    def test_measurement_id_collision_prevention(self):
        """Verify explicit and auto-detected offsets produce non-colliding IDs and reject unsafe offsets."""
        # 1. Unsafe offset raises ValueError
        with self.assertRaises(ValueError) as ctx:
            run_pipeline(NC_PATH_2025, PROCESSED_2025_DIR, id_start_offset=1000, reference_dir=TEST_OUTPUT_DIR)
        self.assertIn("Measurement ID Collision Risk", str(ctx.exception))

        # 2. Safe offset produces IDs starting at offset + 1
        report = run_pipeline(NC_PATH_2025, PROCESSED_2025_DIR, id_start_offset=17339, reference_dir=TEST_OUTPUT_DIR)
        self.assertEqual(report["measurement_id_range"]["start_offset"], 17339)
        self.assertEqual(report["measurement_id_range"]["min_id"], 17340)
        self.assertEqual(report["measurement_id_range"]["max_id"], 26046)

        df_m_2025 = pd.read_parquet(os.path.join(PROCESSED_2025_DIR, "measurements.parquet"))
        df_m_2024 = pd.read_parquet(os.path.join(TEST_OUTPUT_DIR, "measurements.parquet"))
        overlap = set(df_m_2025["measurement_id"]).intersection(set(df_m_2024["measurement_id"]))
        self.assertEqual(len(overlap), 0)

    def test_preservation_of_original_processed_files(self):
        """Verify original data/processed/ files remain completely unmodified."""
        floats_p = os.path.join(TEST_OUTPUT_DIR, "floats.parquet")
        profiles_p = os.path.join(TEST_OUTPUT_DIR, "profiles.parquet")
        measurements_p = os.path.join(TEST_OUTPUT_DIR, "measurements.parquet")

        self.assertTrue(os.path.exists(floats_p))
        self.assertTrue(os.path.exists(profiles_p))
        self.assertTrue(os.path.exists(measurements_p))

        self.assertEqual(len(pd.read_parquet(floats_p)), 21)
        self.assertEqual(len(pd.read_parquet(profiles_p)), 64)
        self.assertEqual(len(pd.read_parquet(measurements_p)), 17339)


if __name__ == "__main__":
    unittest.main()
