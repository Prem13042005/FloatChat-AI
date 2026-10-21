# FloatChat Phase 1.1: ARGO Dataset Forensics & Inspection Report

**Document Version:** 1.0.0  
**Phase:** Phase 1.1 (ARGO Dataset Forensics)  
**Target File:** `Indian_ARGO_Floats_0f9d_516d_c560_U1788882326310.nc`  
**Inspection Utility:** `scripts/inspect_argo_dataset.py` (Reproducible Execution)  

---

## 1. Executive Summary

This report presents empirical forensics on the primary development NetCDF dataset for FloatChat. Inspection was executed using `scripts/inspect_argo_dataset.py` powered by `netCDF4` (v1.7.4) and `xarray` (v2025.6.1).

### Key Findings
1. **Dataset Origin:** The NetCDF file is an ERDDAP tabular export from the INCOIS ERDDAP server (`https://erddap.incois.gov.in/erddap/tabledap/Indian_ARGO_Floats.nc`), covering Indian Ocean float observations recorded between **2024-01-02** and **2024-01-31**.
2. **Flattened Row Structure:** The dataset contains **17,339 observation records** flattened along a single dimension named `row`. It does *not* use a multi-dimensional matrix layout (`N_PROF` × `N_LEVELS`).
3. **Exact Variable Count:** The dataset contains **EXACTLY 7 VARIABLES** (`PLATFORM_NUMBER`, `time`, `latitude`, `longitude`, `PRES`, `TEMP`, `PSAL`).
4. **Complete Absence of Quality Control (QC) Variables:** Zero QC flag variables (`PRES_QC`, `TEMP_QC`, `PSAL_QC`, `POSITION_QC`, `JULD_QC`) exist in this NetCDF file.
5. **Data Coverage:** Contains 21 distinct ARGO float platforms (`PLATFORM_NUMBER`) across 64 distinct profile casts in the Arabian Sea / Equatorial Indian Ocean region (Latitude 8.03°N to 22.65°N, Longitude 60.34°E to 70.22°E).

---

## 2. Dataset Dimensions & Global Attributes

### Dimensions

| Dimension Name | Length | Description |
| :--- | :--- | :--- |
| `row` | **17,339** | Number of individual sub-surface measurement observations. |
| `PLATFORM_NUMBER_strlen` | **7** | Fixed string character length for 7-digit WMO float platform IDs. |

### Global Attributes

| Attribute Name | Value | Description / Scientific Significance |
| :--- | :--- | :--- |
| `title` | `INDIAN ARGO Floats Data` | Official INCOIS ERDDAP dataset title. |
| `institution` | `INCOIS` | Indian National Centre for Ocean Information Services. |
| `featureType` | `Point` | CF Convention feature type representing discrete point observation series. |
| `Conventions` | `CF-1.6, COARDS, ACDD-1.3` | Climate and Forecast (CF) Metadata Conventions. |
| `geospatial_lat_min` | `8.027393333333332` | Southernmost latitude coordinate (°N). |
| `geospatial_lat_max` | `22.65` | Northernmost latitude coordinate (°N). |
| `geospatial_lon_min` | `60.339128333333335` | Westernmost longitude coordinate (°E). |
| `geospatial_lon_max` | `70.21666666666667` | Easternmost longitude coordinate (°E). |
| `time_coverage_start` | `2024-01-02T13:22:00Z` | Earliest station observation timestamp. |
| `time_coverage_end` | `2024-01-31T13:58:23Z` | Latest station observation timestamp. |
| `user_manual_version` | `3.1` | Target ARGO user manual metadata version. |

---

## 3. Comprehensive Variable Forensics

The dataset contains **7 variables**. Below is the detailed breakdown of every variable:

| Variable Name | Dimensions | Shape | Dtype | Units | Long Name | _FillValue |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `PLATFORM_NUMBER` | (`row`, `PLATFORM_NUMBER_strlen`) | (17339, 7) | `|S1` (char) | N/A | Float unique identifier | N/A |
| `time` | (`row`,) | (17339,) | `float64` | `seconds since 1970-01-01T00:00:00Z` | Julian day (UTC) of station | N/A |
| `latitude` | (`row`,) | (17339,) | `float64` | `degrees_north` | Latitude of the station | `99999.0` |
| `longitude` | (`row`,) | (17339,) | `float64` | `degrees_east` | Longitude of the station | `99999.0` |
| `PRES` | (`row`,) | (17339,) | `float32` | `decibar` | Sea water pressure (0 at sea-level) | `99999.0` |
| `TEMP` | (`row`,) | (17339,) | `float32` | `degree_Celsius` | Sea temperature in-situ ITS-90 scale | `99999.0` |
| `PSAL` | (`row`,) | (17339,) | `float32` | `PSU` | Practical salinity | `99999.0` |

---

## 4. Data Quality & Statistical Observation Analysis

Detailed empirical analysis of all observation parameters across the 17,339 records:

### 4.1 Platform Identifier (`PLATFORM_NUMBER`)
- **Format:** 2D character array of 7-character string WMO float identifiers.
- **Unique Float Count:** **21 unique float platforms**.
- **Missing / Fill Observations:** 0 missing records (100% valid).
- **Representative Float WMO IDs:** `'1902671'`, `'1902672'`, `'2902693'`, `'2902694'`, `'2902701'`.

### 4.2 Temporal Parameter (`time`)
- **Format:** Unix Epoch timestamp in seconds (`seconds since 1970-01-01T00:00:00Z`).
- **Unique Timestamps Count:** **64 distinct station timestamps** (representing 64 profile casts across the month).
- **Minimum Timestamp:** `1704201720.0` (2024-01-02 13:22:00 UTC).
- **Maximum Timestamp:** `1706709503.0` (2024-01-31 13:58:23 UTC).
- **Missing / Fill Observations:** 0 missing records.

### 4.3 Geographic Parameters (`latitude`, `longitude`)
- **Latitude Range:** `8.02739° N` to `22.65000° N` (64 unique values).
- **Longitude Range:** `60.33913° E` to `70.21667° E` (60 unique values).
- **Missing / Fill Observations:** 0 missing records (`_FillValue = 99999.0` is never triggered for coordinates).

### 4.4 Ocean Pressure (`PRES`)
- **Definition:** Sea water pressure measured in decibars (`decibar`). Equals `0.0 dbar` at sea surface; acts as the physical proxy for ocean depth (1 dbar ≈ 1 meter depth).
- **Minimum Value:** `0.0 dbar` (surface observation).
- **Maximum Value:** `2034.90 dbar` (deep ocean observation ~2035 meters).
- **Unique Pressure Levels:** **9,223 unique pressure levels**.
- **Missing / Invalid Observations:** Exactly **1 record** contains `_FillValue = 99999.0` (17,338 valid records).

### 4.5 Water Temperature (`TEMP`)
- **Definition:** Sea water temperature at observation pressure measured on the in-situ ITS-90 scale in degrees Celsius (`degree_Celsius`). It is **not** sea-surface temperature unless measured near 0 dbar.
- **Minimum Value:** `2.837 °C` (deep water cold observation).
- **Maximum Value:** `29.902 °C` (warm surface layer observation).
- **Unique Values:** **15,757 unique temperature readings**.
- **Missing / Invalid Observations:** Exactly **0 missing records** (100% valid observations).

### 4.6 Practical Salinity (`PSAL`)
- **Definition:** Practical salinity measured in Practical Salinity Units (`PSU`).
- **Minimum Value:** `23.236 PSU` (coastal / low salinity surface layer).
- **Maximum Value:** `38.908 PSU` (high-salinity Arabian Sea subsurface water mass).
- **Unique Values:** **8,594 unique salinity readings**.
- **Missing / Invalid Observations:** Exactly **4 records** contain `_FillValue = 99999.0` (17,335 valid records).

---

## 5. Quality Control (QC) Variables Investigation

An exhaustive search was conducted for variables containing keywords `QC`, `QUALITY`, or `FLAG`:

* **Result:** **ZERO QC variables exist in this dataset.**
* **Absence Confirmed:** Variables such as `PRES_QC`, `TEMP_QC`, `PSAL_QC`, `POSITION_QC`, `JULD_QC` do **NOT** exist in `Indian_ARGO_Floats_0f9d_516d_c560_U1788882326310.nc`.
* **Explanation:** This file is a clean pre-filtered ERDDAP export containing pre-validated data observations.
* **Engineering Impact:** Phase 1 data ingestion pipelines must **not** attempt to filter on non-existent QC columns. Filter logic must check for numerical `_FillValue = 99999.0` or `NaN` values instead.

---

## 6. Structural & Relationship Analysis

```
+-----------------------------------------------------------------------+
|                 ERDDAP FLATTENED TABLE (17,339 ROWS)                  |
+-----------------------------------------------------------------------+
| PLATFORM_NUMBER | time       | latitude | longitude | PRES  | TEMP  | PSAL  |
| "1902671"       | 1704635313 | 17.100   | 70.216    | 0.3   | 27.67 | 36.40 |
| "1902671"       | 1704635313 | 17.100   | 70.216    | 1.2   | 27.67 | 36.40 |
| ...             | ...        | ...      | ...       | ...   | ...   | ...   |
+-----------------------------------------------------------------------+
```

1. **Profile Identification:** A single profile cast is implicitly defined by the compound tuple `(PLATFORM_NUMBER, time, latitude, longitude)`.
2. **Profile Count:** Grouping the 17,339 rows by `(PLATFORM_NUMBER, time)` yields **exactly 64 profile casts** across 21 floats.
3. **Sub-surface Measurement Count:** Each profile cast contains between ~100 and ~1000 vertical pressure level measurements.

---

## 7. Differences from Phase 0 Assumptions

| Item | Phase 0 Assumption | Phase 1.1 Empirical Fact |
| :--- | :--- | :--- |
| **QC Flag Variables** | Assumed `PRES_QC`, `TEMP_QC`, `PSAL_QC` existed. | **Absent.** Zero QC variables exist in this NetCDF file. |
| **Dataset Dimensions** | Assumed 2D matrix (`N_PROF`, `N_LEVELS`). | **Flattened 1D Table.** Uses `row: 17339` dimension. |
| **Time Variable** | Assumed Julian Day `JULD`. | Variable name is `time` (Unix timestamp in seconds). |
| **Depth Variable** | Assumed `depth` parameter. | Variable name is `PRES` (Units: `decibar`). |
| **Data Scope** | Assumed multi-year float dataset. | Single month export (January 2024: 2024-01-02 to 2024-01-31). |

---

## 8. Verification & Compliance Checklist

- [x] Executed reproducible inspection script (`scripts/inspect_argo_dataset.py`).
- [x] Original NetCDF file was **NOT modified** (read-only mode `'r'`).
- [x] PostgreSQL database was **NOT created or modified**.
- [x] No data cleaning, filtering, or deletion was performed.
- [x] No AI agents, LangGraph workflows, or RAG components were implemented.
- [x] Phase 1.2 has **NOT** started.
