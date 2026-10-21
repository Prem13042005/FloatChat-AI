#!/usr/bin/env python3
"""
scripts/inspect_argo_dataset.py

FloatChat Phase 1.1 — ARGO Dataset Forensics Inspection Utility.
Reproducible, non-destructive NetCDF inspection utility for ARGO observation files.

Usage:
    python scripts/inspect_argo_dataset.py [path-to-netcdf]
"""

import sys
import os
import numpy as np

def inspect_dataset(nc_path):
    if not os.path.exists(nc_path):
        print(f"ERROR: Dataset file not found at '{nc_path}'", file=sys.stderr)
        sys.exit(1)

    print(f"=" * 80)
    print(f"FLOATCHAT PHASE 1.1 — ARGO DATASET FORENSICS INSPECTION")
    print(f"Target File: {nc_path}")
    print(f"File Size: {os.path.getsize(nc_path):,} bytes")
    print(f"=" * 80)

    # Try netCDF4 first, then scipy.io.netcdf, then xarray
    reader_used = None
    netcdf_obj = None

    try:
        import netCDF4 as nc
        ds = nc.Dataset(nc_path, 'r')
        reader_used = "netCDF4"
        netcdf_obj = ds
    except Exception as e1:
        try:
            import scipy.io as io
            ds = io.netcdf_file(nc_path, 'r')
            reader_used = "scipy.io.netcdf"
            netcdf_obj = ds
        except Exception as e2:
            try:
                import xarray as xr
                ds = xr.open_dataset(nc_path)
                reader_used = "xarray"
                netcdf_obj = ds
            except Exception as e3:
                print(f"ERROR: Failed to open dataset using netCDF4, scipy, or xarray.", file=sys.stderr)
                print(f"Details: {e1} | {e2} | {e3}", file=sys.stderr)
                sys.exit(1)

    print(f"NetCDF Library Engine Used: {reader_used}\n")

    report_data = {
        "file_info": {
            "path": nc_path,
            "size_bytes": os.path.getsize(nc_path),
            "engine": reader_used
        },
        "dimensions": {},
        "global_attributes": {},
        "variables": {},
        "qc_variables": [],
        "categorization": {
            "identifiers": [],
            "temporal": [],
            "geographic": [],
            "measurements": [],
            "qc_flags": []
        }
    }

    # Extract Dimensions
    if reader_used == "netCDF4":
        dims = {name: len(dim) for name, dim in ds.dimensions.items()}
        global_attrs = {attr: str(getattr(ds, attr)) for attr in ds.ncattrs()}
        var_names = list(ds.variables.keys())
    elif reader_used == "scipy.io.netcdf":
        dims = {name: dim for name, dim in ds.dimensions.items()}
        global_attrs = {attr: str(getattr(ds, attr)) for attr in dir(ds) if not attr.startswith('_') and attr not in ['dimensions', 'variables', 'close']}
        var_names = list(ds.variables.keys())
    else: # xarray
        dims = {str(name): int(size) for name, size in ds.dims.items()}
        global_attrs = {str(k): str(v) for k, v in ds.attrs.items()}
        var_names = list(ds.data_vars.keys()) + list(ds.coords.keys())

    report_data["dimensions"] = dims
    report_data["global_attributes"] = global_attrs

    print("--- DATASET DIMENSIONS ---")
    if not dims:
        print("  (No explicit dimensions detected or 0-D dataset)")
    for dim_name, dim_len in dims.items():
        print(f"  - {dim_name}: length = {dim_len}")
    print()

    print("--- GLOBAL ATTRIBUTES ---")
    if not global_attrs:
        print("  (No global attributes present)")
    for g_key, g_val in global_attrs.items():
        print(f"  - {g_key}: {g_val}")
    print()

    print("--- DETECTED VARIABLES FORENSICS ---")
    
    for var_name in var_names:
        if reader_used == "netCDF4":
            v = ds.variables[var_name]
            v_dims = v.dimensions
            v_shape = v.shape
            v_dtype = str(v.dtype)
            
            # Attributes
            units = getattr(v, 'units', 'N/A')
            long_name = getattr(v, 'long_name', getattr(v, 'standard_name', 'N/A'))
            fill_value = getattr(v, '_FillValue', getattr(v, 'missing_value', 'N/A'))
            
            # Data array
            raw_data = v[:]
            if hasattr(raw_data, 'filled'):
                raw_data = raw_data.filled(np.nan)
        elif reader_used == "scipy.io.netcdf":
            v = ds.variables[var_name]
            v_dims = v.dimensions
            v_shape = v.shape
            v_dtype = str(v.typecode)
            units = getattr(v, 'units', 'N/A')
            long_name = getattr(v, 'long_name', getattr(v, 'standard_name', 'N/A'))
            fill_value = getattr(v, '_FillValue', getattr(v, 'missing_value', 'N/A'))
            raw_data = v.data
        else: # xarray
            v = ds[var_name]
            v_dims = tuple(v.dims)
            v_shape = v.shape
            v_dtype = str(v.dtype)
            units = v.attrs.get('units', 'N/A')
            long_name = v.attrs.get('long_name', v.attrs.get('standard_name', 'N/A'))
            fill_value = v.attrs.get('_FillValue', v.attrs.get('missing_value', 'N/A'))
            raw_data = v.values

        # Flat clean array for stats calculation
        flat_data = np.asarray(raw_data).flatten()
        total_obs = len(flat_data)
        
        # Check fill/missing values
        if fill_value != 'N/A' and not (isinstance(fill_value, float) and np.isnan(fill_value)):
            valid_mask = (flat_data != fill_value) & (~np.isnan(flat_data))
        else:
            valid_mask = ~np.isnan(flat_data) if np.issubdtype(flat_data.dtype, np.floating) else np.ones(total_obs, dtype=bool)

        valid_data = flat_data[valid_mask]
        valid_count = len(valid_data)
        missing_count = total_obs - valid_count

        # Numerical range / unique values
        min_val, max_val, unique_count = "N/A", "N/A", "N/A"
        samples = []

        if valid_count > 0:
            try:
                if np.issubdtype(valid_data.dtype, np.number):
                    min_val = float(np.min(valid_data))
                    max_val = float(np.max(valid_data))
                    unique_count = int(len(np.unique(valid_data)))
                    samples = [float(x) for x in valid_data[:5]]
                else:
                    unique_count = int(len(np.unique(valid_data)))
                    samples = [str(x) for x in valid_data[:5]]
            except Exception:
                samples = [str(x) for x in valid_data[:5]]

        # Category classification
        var_upper = var_name.upper()
        if "QC" in var_upper or "FLAG" in var_upper or "QUALITY" in var_upper:
            report_data["categorization"]["qc_flags"].append(var_name)
            report_data["qc_variables"].append(var_name)
        elif var_upper in ["PLATFORM_NUMBER", "FLOAT_ID", "WMO", "CYCLE_NUMBER", "PLATFORM", "WMO_ID"]:
            report_data["categorization"]["identifiers"].append(var_name)
        elif var_upper in ["TIME", "JULD", "DATE", "TIMESTAMPTZ"]:
            report_data["categorization"]["temporal"].append(var_name)
        elif var_upper in ["LATITUDE", "LONGITUDE", "LAT", "LON", "POSITION"]:
            report_data["categorization"]["geographic"].append(var_name)
        else:
            report_data["categorization"]["measurements"].append(var_name)

        var_meta = {
            "name": var_name,
            "dimensions": v_dims,
            "shape": list(v_shape),
            "dimensionality": f"{len(v_shape)}D" if len(v_shape) > 0 else "Scalar",
            "dtype": v_dtype,
            "units": str(units),
            "long_name": str(long_name),
            "fill_value": str(fill_value),
            "total_observations": total_obs,
            "valid_observations": valid_count,
            "missing_observations": missing_count,
            "min_value": min_val,
            "max_value": max_val,
            "unique_count": unique_count,
            "sample_values": samples
        }
        report_data["variables"][var_name] = var_meta

        print(f"Variable: {var_name}")
        print(f"  - Dimensions: {v_dims} | Shape: {v_shape} | Dtype: {v_dtype}")
        print(f"  - Dimensionality: {var_meta['dimensionality']}")
        print(f"  - Units: {units} | Long Name: {long_name}")
        print(f"  - FillValue: {fill_value}")
        print(f"  - Observations: Total={total_obs:,}, Valid={valid_count:,}, Missing/Fill={missing_count:,}")
        print(f"  - Value Range: Min={min_val}, Max={max_val}, Unique={unique_count}")
        print(f"  - Samples: {samples}")
        print()

    print("--- QC VARIABLES INVESTIGATION ---")
    if report_data["qc_variables"]:
        print(f"  DETECTED QC Variables: {report_data['qc_variables']}")
        for qc_v in report_data["qc_variables"]:
            meta = report_data["variables"][qc_v]
            print(f"    * {qc_v}: unique values = {meta['sample_values']}")
    else:
        print("  NO QC / Quality Flag / Flag variables detected in dataset.")
    print()

    print("--- DATASET STRUCTURE & RELATIONSHIPS ---")
    print(f"  - Dimensions present: {dims}")
    print(f"  - Variable Count: {len(var_names)}")
    print(f"  - Variable List: {var_names}")

    return report_data

if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "Indian_ARGO_Floats_0f9d_516d_c560_U1788882326310.nc"
    inspect_dataset(target)
