#!/usr/bin/env python3
"""
scripts/normalize_argo_dataset.py

FloatChat Phase 1.3 — Deterministic ARGO Data Ingestion, Normalization & Validation Pipeline.

Reads original NetCDF observation file, cleans/normalizes variables, runs strict validation,
constructs intermediate normalized DataFrames (floats, profiles, measurements), and outputs
Parquet files and a machine-readable validation report JSON.

Usage:
    python scripts/normalize_argo_dataset.py [path-to-netcdf] [output-dir]
"""

import sys
import os
import json
import logging
import numpy as np
import pandas as pd
import netCDF4 as nc

from validate_argo_data import (
    validate_structural_integrity,
    validate_coordinates,
    validate_timestamps,
    perform_duplicate_analysis,
    compute_summary_statistics
)

# Configure Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("floatchat.pipeline")

SENTINEL_FILL_VALUE = 99999.0

def extract_numeric_var(var: nc.Variable) -> np.ndarray:
    """
    Extracts numeric variable array, converting masked elements and literal 99999.0 sentinels to np.nan.
    """
    raw_data = var[:]
    if isinstance(raw_data, np.ma.MaskedArray):
        clean_arr = raw_data.astype(np.float64).filled(np.nan)
    else:
        clean_arr = np.array(raw_data, dtype=np.float64)

    # Also handle literal 99999.0 sentinels if unmasked
    clean_arr[np.isclose(clean_arr, SENTINEL_FILL_VALUE)] = np.nan
    return clean_arr

def load_and_normalize_netcdf(nc_path: str) -> pd.DataFrame:
    """
    Reads original NetCDF dataset, extracts and normalizes verified source fields.
    Source NetCDF file is accessed in read-only mode and NEVER modified.
    """
    if not os.path.exists(nc_path):
        logger.error(f"Input NetCDF file not found: '{nc_path}'")
        raise FileNotFoundError(f"Dataset file missing at '{nc_path}'")

    logger.info(f"Opening NetCDF dataset in read-only mode: {nc_path}")
    ds = nc.Dataset(nc_path, "r")

    # 1. PLATFORM_NUMBER Normalization
    raw_p = ds.variables["PLATFORM_NUMBER"][:]
    platforms = []
    for row in raw_p:
        if isinstance(row, np.ndarray):
            s = "".join([c.decode("utf-8") if isinstance(c, bytes) else str(c) for c in row]).strip()
        else:
            s = str(row).strip()
        platforms.append(s)

    # 2. TIME Normalization (Seconds since 1970-01-01T00:00:00Z -> UTC ISO Datetime)
    raw_time = ds.variables["time"][:]
    profile_times = pd.to_datetime(raw_time, unit="s", utc=True)

    # 3. LATITUDE & LONGITUDE
    lats = ds.variables["latitude"][:].astype(np.float64)
    lons = ds.variables["longitude"][:].astype(np.float64)

    # 4. PRES Normalization (99999.0 / Masked -> NaN / NULL)
    pres_clean = extract_numeric_var(ds.variables["PRES"]).astype(np.float32)

    # 5. TEMP Normalization (99999.0 / Masked -> NaN / NULL)
    temp_clean = extract_numeric_var(ds.variables["TEMP"]).astype(np.float32)

    # 6. PSAL Normalization (99999.0 / Masked -> NaN / NULL)
    psal_clean = extract_numeric_var(ds.variables["PSAL"]).astype(np.float32)

    ds.close()

    df = pd.DataFrame({
        "platform_number": platforms,
        "profile_time": profile_times,
        "latitude": lats,
        "longitude": lons,
        "pressure_dbar": pres_clean,
        "temperature_c": temp_clean,
        "salinity_psu": psal_clean
    })

    logger.info(f"Successfully loaded and normalized {len(df):,} observation records from NetCDF.")
    return df

def run_pipeline(nc_path: str, output_dir: str) -> dict:
    """
    Executes complete ingestion, normalization, validation, and output generation pipeline.
    """
    os.makedirs(output_dir, exist_ok=True)
    logger.info(f"Output directory initialized: {os.path.abspath(output_dir)}")

    # 1. Load and Normalize Raw NetCDF Data
    raw_df = load_and_normalize_netcdf(nc_path)
    input_row_count = len(raw_df)

    # 2. Execute Validation Suite
    validate_structural_integrity(raw_df)
    coord_val = validate_coordinates(raw_df)
    ts_val = validate_timestamps(raw_df)
    dup_val = perform_duplicate_analysis(raw_df)
    stats_val = compute_summary_statistics(raw_df)

    # 3. Construct Normalized Intermediate Entities (floats, profiles, measurements)
    
    # Entity 1: FLOATS
    unique_platforms = sorted(raw_df["platform_number"].unique())
    floats_df = pd.DataFrame({"platform_number": unique_platforms})
    unique_platform_count = len(floats_df)

    # Entity 2: PROFILES
    profile_groups = raw_df.groupby(["platform_number", "profile_time"], as_index=False).first()
    
    # Deterministic profile_id string generation: PROF_{platform_number}_{formatted_timestamp}
    profiles_list = []
    profile_id_map = {}
    
    for idx, row in profile_groups.iterrows():
        p_num = row["platform_number"]
        p_time = row["profile_time"]
        ts_str = p_time.strftime("%Y%m%dT%H%M%SZ")
        p_id = f"PROF_{p_num}_{ts_str}"
        
        profiles_list.append({
            "profile_id": p_id,
            "platform_number": p_num,
            "profile_time": p_time,
            "latitude": float(row["latitude"]),
            "longitude": float(row["longitude"])
        })
        profile_id_map[(p_num, p_time)] = p_id

    profiles_df = pd.DataFrame(profiles_list)
    unique_profile_count = len(profiles_df)

    # Entity 3: MEASUREMENTS
    measurements_list = []
    for idx, row in raw_df.iterrows():
        p_id = profile_id_map[(row["platform_number"], row["profile_time"])]
        measurements_list.append({
            "measurement_id": int(idx + 1),
            "profile_id": p_id,
            "pressure_dbar": row["pressure_dbar"] if pd.notna(row["pressure_dbar"]) else None,
            "temperature_c": row["temperature_c"] if pd.notna(row["temperature_c"]) else None,
            "salinity_psu": row["salinity_psu"] if pd.notna(row["salinity_psu"]) else None
        })

    measurements_df = pd.DataFrame(measurements_list)
    
    # Enforce float32/float64 dtypes for measurements
    measurements_df["measurement_id"] = measurements_df["measurement_id"].astype(np.int64)
    measurements_df["pressure_dbar"] = measurements_df["pressure_dbar"].astype(np.float32)
    measurements_df["temperature_c"] = measurements_df["temperature_c"].astype(np.float32)
    measurements_df["salinity_psu"] = measurements_df["salinity_psu"].astype(np.float32)

    output_measurement_count = len(measurements_df)

    # 4. Write Normalized Intermediate Parquet Files
    floats_path = os.path.join(output_dir, "floats.parquet")
    profiles_path = os.path.join(output_dir, "profiles.parquet")
    measurements_path = os.path.join(output_dir, "measurements.parquet")

    floats_df.to_parquet(floats_path, index=False, engine="pyarrow")
    profiles_df.to_parquet(profiles_path, index=False, engine="pyarrow")
    measurements_df.to_parquet(measurements_path, index=False, engine="pyarrow")

    logger.info(f"Parquet files written successfully:")
    logger.info(f"  - Floats:       {floats_path} ({len(floats_df)} records)")
    logger.info(f"  - Profiles:     {profiles_path} ({len(profiles_df)} records)")
    logger.info(f"  - Measurements: {measurements_path} ({len(measurements_df)} records)")

    # 5. Build and Write Machine-Readable Validation Report JSON
    validation_report = {
        "input_file": os.path.abspath(nc_path),
        "input_row_count": input_row_count,
        "output_measurement_count": output_measurement_count,
        "unique_platform_count": unique_platform_count,
        "unique_profile_count": unique_profile_count,
        "missing_values": {
            "pressure": stats_val["pressure_summary"]["null_count"],
            "temperature": stats_val["temperature_summary"]["null_count"],
            "salinity": stats_val["salinity_summary"]["null_count"],
            "latitude": coord_val["invalid_latitude_count"],
            "longitude": coord_val["invalid_longitude_count"],
            "time": ts_val["invalid_timestamp_count"],
            "platform_number": 0
        },
        "duplicate_analysis": dup_val,
        "coordinate_validation": coord_val,
        "timestamp_validation": ts_val,
        "pressure_summary": stats_val["pressure_summary"],
        "temperature_summary": stats_val["temperature_summary"],
        "salinity_summary": stats_val["salinity_summary"],
        "rejected_record_count": 0
    }

    report_path = os.path.join(output_dir, "validation_report.json")
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(validation_report, f, indent=2)

    logger.info(f"Validation Report JSON written to: {report_path}")
    logger.info("Phase 1.3 Data Pipeline Execution COMPLETED SUCCESSFULLY.")

    return validation_report

if __name__ == "__main__":
    nc_input = sys.argv[1] if len(sys.argv) > 1 else "Indian_ARGO_Floats_0f9d_516d_c560_U1788882326310.nc"
    out_dir = sys.argv[2] if len(sys.argv) > 2 else os.path.join("data", "processed")
    
    run_pipeline(nc_input, out_dir)
