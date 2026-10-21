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

if __name__ == "__main__":
    unittest.main()
