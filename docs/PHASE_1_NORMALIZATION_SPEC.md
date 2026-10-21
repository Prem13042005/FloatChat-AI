# FloatChat Phase 1.2: ARGO Data Normalization & Cleaning Specification

**Document Version:** 1.1.0 (Approved with Corrections)  
**Phase:** Phase 1.2 (Normalization & Cleaning Specification)  
**Status:** Approved Specification  
**Target File:** `Indian_ARGO_Floats_0f9d_516d_c560_U1788882326310.nc`  

---

## 1. Dataset Summary & Verified Source Schema

### 1.1 Verified Dataset Facts
- **Source File:** `Indian_ARGO_Floats_0f9d_516d_c560_U1788882326310.nc`
- **Dataset Type:** ERDDAP flattened 1D observation table (`row: 17339`).
- **Time Scope:** January 2024 (2024-01-02T13:22:00Z to 2024-01-31T13:58:23Z).
- **Geographic Scope:** Arabian Sea / Equatorial Indian Ocean (Lat 8.03°N to 22.65°N, Lon 60.34°E to 70.22°E).
- **Exact Variable Count:** **7 variables**.

### 1.2 Source Variable Traceability Matrix

| Normalized Field Name | Verified NetCDF Source Variable | Raw Dtype | Units | Data Description |
| :--- | :--- | :--- | :--- | :--- |
| `platform_number` | `PLATFORM_NUMBER` | `|S1` (char[7]) | N/A | Float unique WMO platform identifier |
| `profile_time` | `time` | `float64` | `seconds since 1970-01-01T00:00:00Z` | Station profile timestamp (UTC) |
| `latitude` | `latitude` | `float64` | `degrees_north` | Station latitude coordinate |
| `longitude` | `longitude` | `float64` | `degrees_east` | Station longitude coordinate |
| `pressure_dbar` | `PRES` | `float32` | `decibar` | Ocean pressure at observation level |
| `temperature_c` | `TEMP` | `float32` | `degree_Celsius` | In-situ water temperature at pressure |
| `salinity_psu` | `PSAL` | `float32` | `PSU` | Practical salinity |

*Note: All 7 fields are normalized representations of verified NetCDF source variables. Zero additional source variables are invented.*

---

## 2. Profile Identity Specification

### Empirical Uniqueness Findings
Grouping all 17,339 observation records by `(PLATFORM_NUMBER, time)` yields **exactly 64 unique profile groups**.
- **Coordinate Consistency:** Every `(PLATFORM_NUMBER, time)` pair maps to **exactly 1** unique `(latitude, longitude)` geographic point (0 coordinate discrepancies).

### Profile Identity & Primary Key Policy
1. **Natural Identity:** `(platform_number, profile_time)` is the verified natural profile identity.
2. **Surrogate Key Flexibility:** A database-generated surrogate key (such as `BIGINT` or `UUID`) may be used in Phase 2 for physical database primary keys. Mandatory SHA256 hashing is **not** required.
3. **Uniqueness Constraint:** Phase 2 database schema will enforce a `UNIQUE(platform_number, profile_time)` constraint.
4. **Physical Implementation Deferred:** The exact physical primary key implementation is deferred to Phase 2.

---

## 3. Empirical Duplicate Analysis & Policy

### Empirical Duplicate Audit Results
An exhaustive empirical duplicate check was performed across all 17,339 dataset rows:

1. **Exact Duplicate Rows (All 7 Variables):** **0 exact duplicate rows** exist in the dataset.
2. **Duplicate Candidate Measurements (`PLATFORM_NUMBER`, `time`, `PRES`):** **0 duplicate candidate rows** exist.
3. **Duplicate Groups Count:** **0 duplicate groups** exist.
4. **Conflicting Measurements:** **0 conflicting TEMP or PSAL records** exist.
5. **Missing Pressure (`PRES = 99999.0`):** Exactly **1 record** (row 15,374, float `5907092`) has missing pressure.

### Deterministic Duplicate Policy

The normalization specification defines a 3-tier duplicate policy for handling incoming data streams:

1. **Exact Duplicate Observations:** Records identical across all 7 variables.
   - *Policy:* Retain a single observation instance; log duplicate count.
2. **Conflicting Measurements:** Records matching on `(platform_number, profile_time, pressure_dbar)` but containing differing `temperature_c` or `salinity_psu` values.
   - *Policy:* Retain **both** records under distinct surrogate `measurement_id` keys and log a data integrity warning. Never silently delete conflicting scientific observations.
3. **Observations with Missing Pressure (`pressure_dbar = NULL`):**
   - *Policy:* Retain the record with `pressure_dbar = NULL`, assign a surrogate `measurement_id`, and exclude it from physical pressure-level uniqueness index checks (since SQL `NULL != NULL`).

---

## 4. Platform Identifier Normalization

- **Source Variable:** `PLATFORM_NUMBER` (`char[7]`).
- **Normalization:** Decode char array to UTF-8 string, strip whitespace padding (e.g. `'1902671 '` -> `'1902671'`).
- **Type:** Store as a **String / Text** identifier. Do not alter numerically or strip leading zeros.

---

## 5. Time Normalization

- **Source Variable:** `time` (`float64` seconds since Unix epoch).
- **Normalization:** Convert seconds to an ISO-8601 UTC string / PostgreSQL `TIMESTAMPTZ` (e.g., `1704635313.0` -> `2024-01-07T13:48:33+00:00`).
- **Policy:** **Strictly preserve UTC**. Silent conversion to local system timezones is prohibited.

---

## 6. Geographic Normalization

- **Source Variables:** `latitude` (`degrees_north`), `longitude` (`degrees_east`).
- **Normalization:** Retain exact decimal precision (`float64`).
- **Validation Range:** `-90.0 <= latitude <= 90.0` and `-180.0 <= longitude <= 180.0`. Observed ranges: Lat `[8.027393°, 22.650000°]`, Lon `[60.339128°, 70.216667°]`.
- **PostGIS Compatibility:** Formatted directly for WGS84 `GEOMETRY(Point, 4326)` insertion without spatial distortion.

---

## 7. Pressure Normalization

- **Source Variable:** `PRES` (`float32` in `decibar`).
- **Sentinel Rule:** Convert sentinel value `99999.0` to **`NULL`** (1 occurrence in dataset).
- **Unit Rule:** Preserved in decibars (`decibar`). Do **not** rename `PRES` to depth or convert to meters in Phase 1.
- **Validation:** Flag values `PRES < 0.0` or `PRES > 2200.0 dbar` as suspicious in validation logs, but do not delete.

---

## 8. Temperature Normalization

- **Source Variable:** `TEMP` (`float32` in `degree_Celsius`).
- **Sentinel Rule:** Convert `99999.0` to **`NULL`** (0 occurrences in dataset).
- **Unit Rule:** Preserved in °C (ITS-90 scale). Described as **in-situ water temperature at pressure**.
- **Validation:** Valid oceanographic range: `-2.5 °C <= TEMP <= 40.0 °C`. Observed range: `[2.837 °C, 29.902 °C]`.

---

## 9. Salinity Normalization

- **Source Variable:** `PSAL` (`float32` in `PSU`).
- **Sentinel Rule:** Convert `99999.0` to **`NULL`** (4 occurrences in dataset).
- **Retention Rule:** Low surface salinity values (e.g. `23.236 PSU`) are valid coastal observations and are preserved.
- **Validation:** Valid oceanographic range: `2.0 PSU <= PSAL <= 45.0 PSU`. Observed range: `[23.236 PSU, 38.908 PSU]`.

---

## 10. Null & Sentinel Policy

FloatChat enforces a single deterministic missing value pipeline:

```
NetCDF Sentinel (99999.0)  --->  Python None / np.nan  --->  Database NULL
```

- **Prohibited:** Never use arbitrary sentinel numbers (`0`, `-1`, `99999`) for missing data.

---

## 11. Data Cleaning vs. Data Validation Boundaries

FloatChat strictly separates cleaning transformations from validation checks:

### Data Cleaning (Deterministic Transformations)
- Convert known sentinel values (`99999.0`) to `NULL`.
- Strip whitespace padding from `platform_number` strings.
- Convert Unix seconds to timezone-aware UTC ISO timestamps.
- Preserve all valid observation tuples.

### Data Validation (Quality & Structural Checks)
- Detect impossible geographic coordinates (outside WGS84 limits).
- Detect structurally corrupt records (missing platform ID or unparseable timestamp).
- Detect duplicate or conflicting measurement records.
- Report physically suspicious scientific values in validation logs.
- *Rule:* Do **not** perform aggressive scientific outlier deletion in V1.

---

## 12. Intermediate Normalized Data Model

Conceptual entities representing the normalized output schema:

```
FLOAT
  └── platform_number (String, PK)         ← PLATFORM_NUMBER

PROFILE
  ├── profile_id (Surrogate PK)            ← Phase 2 BIGINT/UUID
  ├── platform_number (String, FK)        ← PLATFORM_NUMBER
  ├── profile_time (TIMESTAMPTZ UTC)       ← time
  ├── latitude (Float64)                   ← latitude
  └── longitude (Float64)                  ← longitude

MEASUREMENT
  ├── measurement_id (Surrogate PK)        ← Phase 2 BIGINT/UUID
  ├── profile_id (Surrogate FK)            ← FK to PROFILE
  ├── pressure_dbar (Float32, Nullable)    ← PRES (99999.0 -> NULL)
  ├── temperature_c (Float32, Nullable)    ← TEMP (99999.0 -> NULL)
  └── salinity_psu (Float32, Nullable)     ← PSAL (99999.0 -> NULL)
```

---

## 13. Pressure / Depth Conceptual Policy

1. **Authoritative Variable:** `PRES` (`pressure_dbar`) measured in decibars (`dbar`) is the authoritative source variable.
2. **Phase 1 Scope:** **No pressure-to-depth conversion is performed in Phase 1.** Phase 1 does not execute natural-language query translation.
3. **Conceptual V1 Interpretation Policy:**
   - In V1 query execution (Phases 5–6), pressure will be used as an approximate proxy for depth (e.g., natural-language phrases like *"below 500 meters"* may be interpreted approximately as `pressure_dbar >= 500.0`).
   - This interpretation is explicitly an **approximation** (`1 dbar ≈ 1 meter`) and must not be described as an exact conversion.
   - The user-facing system should be capable of disclosing this approximation where relevant.
   - Scientifically rigorous pressure-to-depth conversion algorithms (e.g., UNESCO PSS-78 / Saunders & Fofonoff) are deferred to a future implementation phase.

---

## 14. Validation Rules Summary

```python
VALIDATION_RULES = {
    "latitude": lambda lat: -90.0 <= lat <= 90.0,
    "longitude": lambda lon: -180.0 <= lon <= 180.0,
    "pressure_dbar": lambda pres: pres is None or (0.0 <= pres <= 11000.0),
    "temperature_c": lambda temp: temp is None or (-2.5 <= temp <= 40.0),
    "salinity_psu": lambda psal: psal is None or (2.0 <= psal <= 45.0),
}
```

---

## 15. Explicit Non-Goals for Phase 1.2

- **NO Pipeline Code Implementation:** Pipeline implementation is deferred to Phase 1.3.
- **NO Database Creation:** PostgreSQL schema creation deferred to Phase 2.
- **NO NetCDF File Mutation:** Original NetCDF dataset remains untouched.
- **NO Scientific Outlier Deletion:** No deletion of unusual but valid observations.
