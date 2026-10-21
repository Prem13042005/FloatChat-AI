# FloatChat Phase 1.4: Independent Output Validation & Data Quality Assurance Report

**Document Version:** 1.0.0  
**Phase:** Phase 1.4 (Independent Output Validation)  
**Status:** **APPROVED & PASSED (100% Quality Assurance Match)**  
**Input Source File:** `Indian_ARGO_Floats_0f9d_516d_c560_U1788882326310.nc`  
**Inspected Outputs:** `data/processed/*.parquet` & `validation_report.json`  
**Test Suite:** `tests/test_validation.py` (16 Automated Assertions Passed)  

---

## 1. Validation Objective & Scope

This report presents the independent data quality assurance and verification results for the intermediate datasets produced by the Phase 1.3 deterministic pipeline (`scripts/normalize_argo_dataset.py`).

The validation was conducted **independently** of the ingestion logic to verify that output datasets are:
- Structurally correct and schema-compliant.
- Referentially consistent across entities (0 orphan references).
- Complete and free from untransformed sentinel values (`99999.0`).
- 100% deterministic and reproducible.
- Fully suitable for Phase 2 PostgreSQL + PostGIS database loading.

---

## 2. File Verification & Physical Schemas

### 2.1 File Existence (Validation 1)
- `data/processed/floats.parquet`: **EXISTS** (769 bytes)
- `data/processed/profiles.parquet`: **EXISTS** (4,374 bytes)
- `data/processed/measurements.parquet`: **EXISTS** (140,883 bytes)
- `data/processed/validation_report.json`: **EXISTS** (1,228 bytes)

### 2.2 Physical Parquet Schemas (Validation 2)

```
FLOATS (data/processed/floats.parquet)
└── platform_number      : string (object)

PROFILES (data/processed/profiles.parquet)
├── profile_id           : string (object)
├── platform_number      : string (object)
├── profile_time         : datetime64[ns, UTC] (Timezone-Aware UTC)
├── latitude             : double (float64)
└── longitude            : double (float64)

MEASUREMENTS (data/processed/measurements.parquet)
├── measurement_id       : int64 (Integer PK)
├── profile_id           : string (object FK)
├── pressure_dbar        : float32 (Nullable)
├── temperature_c        : float32 (Nullable)
└── salinity_psu         : float32 (Nullable)
```

---

## 3. Actual Row Counts & Entity Summaries (Validation 3)

- **`floats.parquet` Row Count:** **21 rows** (21 unique ARGO float platforms).
- **`profiles.parquet` Row Count:** **64 rows** (64 distinct station profile casts).
- **`measurements.parquet` Row Count:** **17,339 rows** (17,339 sub-surface observations).

---

## 4. Referential & Structural Integrity Results

### 4.1 Platform Integrity (Validation 4)
- **Null `platform_number` Count:** **0**
- **Empty String `platform_number` Count:** **0**
- **Duplicate `platform_number` in `floats.parquet`:** **0**
- **Orphan Platform References in `profiles.parquet`:** **0** (All 64 profiles map to an existing float platform).

### 4.2 Profile Integrity & Coordinate Consistency (Validation 5)
- **Null `profile_id` Count:** **0**
- **Duplicate `profile_id` Count:** **0**
- **Orphan Profile References:** **0**
- **WGS84 Latitude Out-of-Bounds (`[-90, 90]`):** **0** (Observed range: `8.02739° N` to `22.65000° N`).
- **WGS84 Longitude Out-of-Bounds (`[-180, 180]`):** **0** (Observed range: `60.33913° E` to `70.21667° E`).
- **Natural Profile Identity `(platform_number, profile_time)` Duplicates:** **0** (64 unique natural profiles).
- **Profile Coordinate Conflicts:** **0** (Every natural profile maps to exactly one geographic coordinate pair).

### 4.3 Measurement Referential Integrity (Validation 6)
- **Null `measurement_id` Count:** **0**
- **Duplicate `measurement_id` Count:** **0**
- **Orphan Measurements Count:** **0** (All 17,339 measurement records map to a valid `profile_id` in `profiles.parquet`).

---

## 5. Value Range, Null & Sentinel Analysis

### 5.1 Sentinel Check (Validation 8)
- Search for raw sentinel value `99999.0`:
  - `pressure_dbar`: **0 remaining sentinels**
  - `temperature_c`: **0 remaining sentinels**
  - `salinity_psu`: **0 remaining sentinels**

### 5.2 Actual NULL Counts (Validation 9)
- `pressure_dbar` NULL Count: **1** (Row index 15,374, float `5907092`).
- `salinity_psu` NULL Count: **4** (Row indices 15209, 15374, 16936, 17265).
- `temperature_c` NULL Count: **0**
- `latitude` / `longitude` / `profile_time` / `platform_number` NULL Count: **0**

### 5.3 Measurement Numeric Ranges (Validation 7)
- **`pressure_dbar`:** Min = `0.0 dbar`, Max = `2034.9 dbar`, Negative count = **0**.
- **`temperature_c`:** Min = `2.837 °C`, Max = `29.902 °C`.
- **`salinity_psu`:** Min = `23.236 PSU`, Max = `38.908 PSU`.

---

## 6. Duplicate Analysis (Validation 10)

- **Exact Duplicate Rows Across All Fields:** **0**
- **Duplicate Candidate Groups (`platform_number`, `profile_time`, `pressure_dbar`):** **0**
- **Conflicting Measurement Records:** **0**
- **Missing Pressure Policy Check:** Exactly 1 record has `pressure_dbar = NULL`. It is correctly assigned a unique `measurement_id` and retained without violating profile uniqueness.

---

## 7. Cross-Table Consistency & Source Reconciliation

### 7.1 Cross-Table Consistency (Validation 11)
- Unique platforms in `profiles.parquet` = **21** (matches `floats.parquet` row count).
- Unique profile IDs in `measurements.parquet` = **64** (matches `profiles.parquet` row count).
- Every measurement maps to exactly 1 profile (100% coverage).

### 7.2 Source Data Reconciliation (Validation 12)

| Metric / Dimension | Raw NetCDF Source Dataset | Normalized Parquet Outputs | Reconciliation Status |
| :--- | :--- | :--- | :--- |
| **Total Row / Measurement Count** | 17,339 rows | 17,339 measurement records | **100% MATCH** |
| **Unique Platform Count** | 21 platforms | 21 float platform records | **100% MATCH** |
| **Unique Profile Casts** | 64 profiles | 64 profile station records | **100% MATCH** |
| **Missing Pressure Count** | 1 sentinel | 1 NULL record (`pressure_dbar`) | **100% MATCH** |
| **Missing Salinity Count** | 4 sentinels | 4 NULL records (`salinity_psu`) | **100% MATCH** |
| **Missing Temperature Count** | 0 sentinels | 0 NULL records (`temperature_c`) | **100% MATCH** |
| **Pressure Range (dbar)** | `[0.0, 2034.9]` | `[0.0, 2034.9]` | **100% MATCH** |
| **Temperature Range (°C)** | `[2.837, 29.902]` | `[2.837, 29.902]` | **100% MATCH** |
| **Salinity Range (PSU)** | `[23.236, 38.908]` | `[23.236, 38.908]` | **100% MATCH** |

---

## 8. Profile Distribution Statistics (Validation 13)

- **Minimum Measurements per Profile:** **58**
- **Maximum Measurements per Profile:** **996**
- **Average Measurements per Profile:** **270.92**
- **Profiles with Measurements:** **64 out of 64 (100%)**

---

## 9. Determinism & Data Immutability Results

### 9.1 Pipeline Determinism (Validation 14)
- Re-execution of the pipeline to a temporary directory (`data/processed_test_determinism/`) yielded **100% exact DataFrame equality** across all output Parquet files (`floats.parquet`, `profiles.parquet`, `measurements.parquet`).
- Determinism Status: **PASSED (100% Reproducible)**.

### 9.2 Data Immutability (Validation 15)
- [x] Original NetCDF file (`Indian_ARGO_Floats_0f9d_516d_c560_U1788882326310.nc`) was **NOT modified**.
- [x] Phase 1.3 output files in `data/processed/` were **NOT modified** during validation.
- [x] Zero records were deleted or rewritten.

---

## 10. Overall Assessment & Phase 2 Recommendations

### Overall Status: **PASS / APPROVED**

### Warnings
- **None.** Zero data integrity, coordinate, or referential warnings.

### Recommendations for Phase 2 (PostgreSQL + PostGIS Database Loading)
1. **Database Schema Setup:** Create PostGIS tables `argo_floats`, `argo_profiles`, `argo_measurements` matching the verified Parquet schemas.
2. **PostGIS Point Construction:** Construct PostGIS geometry points for profiles using `ST_SetSRID(ST_MakePoint(longitude, latitude), 4326)`.
3. **Database Constraints:** Apply `UNIQUE(platform_number, profile_time)` constraint on `argo_profiles`. Apply foreign key constraint `argo_profiles.platform_number -> argo_floats.platform_number` and `argo_measurements.profile_id -> argo_profiles.profile_id`.
4. **Spatial Indexing:** Create GIST index on `argo_profiles.location` for fast bounding box and radial geographic querying.
