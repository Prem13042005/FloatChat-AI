# FloatChat Phase 1.3: ARGO Deterministic Data Ingestion & Pipeline Specification

**Document Version:** 1.0.0  
**Phase:** Phase 1.3 (Deterministic ARGO Data Pipeline Implementation)  
**Status:** Executed & Verified  
**Input Source File:** `Indian_ARGO_Floats_0f9d_516d_c560_U1788882326310.nc`  
**Output Directory:** `data/processed/`  

---

## 1. Pipeline Architecture

FloatChat Phase 1.3 provides a clean, reproducible, non-destructive Python data pipeline that reads the raw NetCDF oceanographic observation file, normalizes source variables, validates structural and coordinate integrity, constructs normalized intermediate entities, and outputs binary Parquet files alongside a machine-readable validation report JSON.

```
+-----------------------------------------------------------------------+
|                    RAW NETCDF INPUT DATASET                           |
|       (Indian_ARGO_Floats_0f9d_516d_c560_U1788882326310.nc)           |
+-----------------------------------------------------------------------+
                                   |  (Read-Only Mode)
                                   v
+-----------------------------------------------------------------------+
|           NORMALIZATION ENGINE (scripts/normalize_argo_dataset.py)     |
| - PLATFORM_NUMBER: UTF-8 decode & whitespace strip                    |
| - time: Seconds since 1970-01-01 -> UTC TIMESTAMPTZ                   |
| - PRES / TEMP / PSAL: 99999.0 sentinels -> NULL                       |
+-----------------------------------------------------------------------+
                                   |
                                   v
+-----------------------------------------------------------------------+
|           VALIDATION MODULE (scripts/validate_argo_data.py)           |
| - Structural & Schema Check                                           |
| - WGS84 Coordinate Range & Profile Consistency Check                  |
| - Timestamp UTC Range Validation                                      |
| - Duplicate & Conflicting Measurement Audit                           |
+-----------------------------------------------------------------------+
                                   |
                                   v
+-----------------------------------------------------------------------+
|                       PARQUET & JSON OUTPUTS                          |
| - data/processed/floats.parquet        (21 float platforms)           |
| - data/processed/profiles.parquet      (64 profile casts)             |
| - data/processed/measurements.parquet  (17,339 measurements)         |
| - data/processed/validation_report.json (Validation Metrics)        |
+-----------------------------------------------------------------------+
```

---

## 2. Input Dataset Specification

- **File Path:** `Indian_ARGO_Floats_0f9d_516d_c560_U1788882326310.nc`
- **File Size:** 751,672 bytes
- **Format:** ERDDAP flattened 1D NetCDF table (`row: 17339`).
- **Verified Variables (7):** `PLATFORM_NUMBER`, `time`, `latitude`, `longitude`, `PRES`, `TEMP`, `PSAL`.

---

## 3. Normalization Operations

1. **`PLATFORM_NUMBER` Normalization:**
   - Source: `PLATFORM_NUMBER` (`char[7]`).
   - Operation: Decoded to string, whitespace padding trimmed (`strip()`).
   - Output Field: `platform_number` (String).
2. **`time` Normalization:**
   - Source: `time` (`float64` seconds since 1970-01-01 epoch).
   - Operation: Converted to UTC ISO-8601 timestamp (`pd.to_datetime(unit='s', utc=True)`).
   - Output Field: `profile_time` (`TIMESTAMPTZ UTC`).
3. **`latitude` & `longitude` Normalization:**
   - Source: `latitude`, `longitude` (`float64`).
   - Operation: Validated against WGS84 bounds (`[-90, 90]` lat, `[-180, 180]` lon). Retained at `float64` precision.
4. **`PRES` Normalization:**
   - Source: `PRES` (`float32` in `decibar`).
   - Operation: Sentinel value `99999.0` converted to `NULL` (`np.nan`). Preserved in decibars (`pressure_dbar`).
5. **`TEMP` Normalization:**
   - Source: `TEMP` (`float32` in `degree_Celsius`).
   - Operation: Sentinel value `99999.0` converted to `NULL` (`np.nan`). Preserved in °C (`temperature_c`).
6. **`PSAL` Normalization:**
   - Source: `PSAL` (`float32` in `PSU`).
   - Operation: Sentinel value `99999.0` converted to `NULL` (`np.nan`). Preserved in PSU (`salinity_psu`).

---

## 4. Validation Operations

- **Structural Integrity:** Verifies all 7 required source columns exist and data row count > 0.
- **Coordinate Integrity:** Validates lat/lon limits and verifies 0 coordinate discrepancies across profile casts.
- **Timestamp Integrity:** Validates non-null timestamps and checks min/max temporal range.
- **Duplicate Analysis:** Evaluates exact duplicate rows and candidate duplicates on `(platform_number, profile_time, pressure_dbar)`.

---

## 5. Intermediate Data Model & Parquet Schemas

### 5.1 `data/processed/floats.parquet`
| Field Name | Type | Description |
| :--- | :--- | :--- |
| `platform_number` | `string` | Unique WMO float platform identifier (Primary Key) |

### 5.2 `data/processed/profiles.parquet`
| Field Name | Type | Description |
| :--- | :--- | :--- |
| `profile_id` | `string` | Deterministic profile identifier (`PROF_<platform>_<timestamp>`) |
| `platform_number` | `string` | Foreign key referencing `floats.parquet` |
| `profile_time` | `datetime64[ns, UTC]` | Profile observation timestamp (UTC) |
| `latitude` | `double` | Station latitude coordinate (°N) |
| `longitude` | `double` | Station longitude coordinate (°E) |

### 5.3 `data/processed/measurements.parquet`
| Field Name | Type | Description |
| :--- | :--- | :--- |
| `measurement_id` | `int64` | Measurement row primary key (`1..17339`) |
| `profile_id` | `string` | Foreign key referencing `profiles.parquet` |
| `pressure_dbar` | `float32` (nullable) | Ocean pressure (dbar) |
| `temperature_c` | `float32` (nullable) | In-situ water temperature (°C) |
| `salinity_psu` | `float32` (nullable) | Practical salinity (PSU) |

---

## 6. Missing-Value & Duplicate Policy

- **Missing Value Sentinel Handling:** `99999.0` is converted exclusively to `NULL` (`np.nan`). No arbitrary replacements (`0`, `-1`) are inserted.
- **QC Limitation:** Zero QC variables exist in this ERDDAP dataset. No QC flag filtering is claimed or performed.
- **Duplicate Strategy:** Exact duplicate rows are reported. Duplicate candidates matching on `(platform_number, profile_time, pressure_dbar)` are checked. Conflicting observations are retained with separate `measurement_id` keys and logged. Observations with `pressure_dbar = NULL` are retained as station-level records.

---

## 7. Execution Guide

To run the pipeline and generate processed Parquet files:

```bash
python scripts/normalize_argo_dataset.py Indian_ARGO_Floats_0f9d_516d_c560_U1788882326310.nc data/processed
```

To run the pipeline test suite:

```bash
python -m unittest discover -s tests -p "test_*.py"
```

---

## 8. Expected Validation Results

- `input_row_count`: **17,339**
- `output_measurement_count`: **17,339**
- `unique_platform_count`: **21**
- `unique_profile_count`: **64**
- `rejected_record_count`: **0**
- `missing_values.pressure`: **1**
- `missing_values.salinity`: **4**
- `missing_values.temperature`: **0**
- `duplicate_analysis.exact_duplicates`: **0**
- `duplicate_analysis.duplicate_candidate_groups`: **0**

---

## 9. Future Phase 2 Loading Step

In **Phase 2 (PostgreSQL + PostGIS Database Foundation)**, the generated Parquet files (`floats.parquet`, `profiles.parquet`, `measurements.parquet`) will be loaded directly into PostgreSQL tables (`argo_floats`, `argo_profiles`, `argo_measurements`) with PostGIS geometry points constructed via `ST_SetSRID(ST_MakePoint(longitude, latitude), 4326)`.
