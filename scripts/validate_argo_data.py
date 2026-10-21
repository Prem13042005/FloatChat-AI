#!/usr/bin/env python3
"""
scripts/validate_argo_data.py

FloatChat Phase 1.3 — Deterministic ARGO Data Validation Module.
Contains validation logic for structural integrity, coordinate bounds,
timestamp ranges, duplicate detection, and missing-value statistics.
"""

import logging
import pandas as pd

logger = logging.getLogger("floatchat.validator")

def validate_structural_integrity(df: pd.DataFrame) -> None:
    """
    Verifies that all required source columns exist and have non-empty valid types.
    Raises ValueError if structural assumptions are violated.
    """
    required_cols = ["platform_number", "profile_time", "latitude", "longitude", "pressure_dbar", "temperature_c", "salinity_psu"]
    missing_cols = [c for c in required_cols if c not in df.columns]
    if missing_cols:
        raise ValueError(f"Structural Validation Failed: Missing required columns {missing_cols}")

    if len(df) == 0:
        raise ValueError("Structural Validation Failed: Input dataset contains 0 rows.")

    logger.info("Structural integrity validation PASSED: All 7 required columns present.")

def validate_coordinates(df: pd.DataFrame) -> dict:
    """
    Validates latitude (-90 to +90) and longitude (-180 to +180).
    Checks profile coordinate consistency.
    """
    invalid_lat_mask = (df['latitude'] < -90.0) | (df['latitude'] > 90.0) | df['latitude'].isna()
    invalid_lon_mask = (df['longitude'] < -180.0) | (df['longitude'] > 180.0) | df['longitude'].isna()

    invalid_lat_count = int(invalid_lat_mask.sum())
    invalid_lon_count = int(invalid_lon_mask.sum())

    if invalid_lat_count > 0 or invalid_lon_count > 0:
        raise ValueError(f"Coordinate Validation Failed: Invalid Lat={invalid_lat_count}, Lon={invalid_lon_count}")

    # Check profile coordinate consistency: (platform_number, profile_time) -> lat/lon
    coord_groups = df.groupby(['platform_number', 'profile_time'])[['latitude', 'longitude']].nunique()
    inconsistent_profiles = coord_groups[(coord_groups['latitude'] > 1) | (coord_groups['longitude'] > 1)]
    conflict_count = len(inconsistent_profiles)

    if conflict_count > 0:
        raise ValueError(f"Profile Coordinate Validation Failed: Found {conflict_count} profiles with inconsistent coordinates.")

    logger.info("Coordinate validation PASSED: Lat/Lon within WGS84 bounds; 0 profile coordinate conflicts.")
    return {
        "invalid_latitude_count": invalid_lat_count,
        "invalid_longitude_count": invalid_lon_count,
        "profile_coordinate_conflicts": conflict_count
    }

def validate_timestamps(df: pd.DataFrame) -> dict:
    """
    Validates UTC timestamps.
    """
    invalid_ts_mask = df['profile_time'].isna()
    invalid_ts_count = int(invalid_ts_mask.sum())

    if invalid_ts_count > 0:
        raise ValueError(f"Timestamp Validation Failed: Found {invalid_ts_count} null or invalid timestamps.")

    min_ts = df['profile_time'].min().isoformat()
    max_ts = df['profile_time'].max().isoformat()

    logger.info(f"Timestamp validation PASSED: Min={min_ts}, Max={max_ts}")
    return {
        "invalid_timestamp_count": invalid_ts_count,
        "minimum_timestamp": min_ts,
        "maximum_timestamp": max_ts
    }

def perform_duplicate_analysis(df: pd.DataFrame) -> dict:
    """
    Performs duplicate analysis:
    1. Exact duplicate rows across all normalized fields.
    2. Duplicate candidate measurements on (platform_number, profile_time, pressure_dbar) for non-null pressures.
    3. Conflicting measurement detection.
    """
    # 1. Exact duplicate rows
    cols_all = ["platform_number", "profile_time", "latitude", "longitude", "pressure_dbar", "temperature_c", "salinity_psu"]
    exact_duplicates_count = int(df.duplicated(subset=cols_all, keep=False).sum())

    # 2. Duplicate candidates (excluding null pressure)
    valid_pres_df = df[df['pressure_dbar'].notna()]
    dup_candidates_mask = valid_pres_df.duplicated(subset=["platform_number", "profile_time", "pressure_dbar"], keep=False)
    dup_candidate_rows_count = int(dup_candidates_mask.sum())

    dup_groups_count = 0
    conflicting_measurements_count = 0

    if dup_candidate_rows_count > 0:
        dup_df = valid_pres_df[dup_candidates_mask]
        dup_grouped = dup_df.groupby(["platform_number", "profile_time", "pressure_dbar"])
        dup_groups_count = len(dup_grouped)

        # Check for conflicting temp or psal in duplicate groups
        for _, group in dup_grouped:
            if group['temperature_c'].nunique() > 1 or group['salinity_psu'].nunique() > 1:
                conflicting_measurements_count += len(group)

    logger.info(f"Duplicate Analysis: Exact={exact_duplicates_count}, Candidate Groups={dup_groups_count}, Conflicting={conflicting_measurements_count}")

    return {
        "exact_duplicates": exact_duplicates_count,
        "duplicate_candidate_groups": dup_groups_count,
        "conflicting_measurements": conflicting_measurements_count
    }

def compute_summary_statistics(df: pd.DataFrame) -> dict:
    """
    Computes min, max, and null counts for numeric measurement parameters.
    """
    def _stat(series):
        valid = series.dropna()
        return {
            "minimum": float(valid.min()) if len(valid) > 0 else None,
            "maximum": float(valid.max()) if len(valid) > 0 else None,
            "null_count": int(series.isna().sum())
        }

    return {
        "pressure_summary": _stat(df['pressure_dbar']),
        "temperature_summary": _stat(df['temperature_c']),
        "salinity_summary": _stat(df['salinity_psu'])
    }
