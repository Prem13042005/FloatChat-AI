# FloatChat: Query Taxonomy & Benchmark Categories

**Document Version:** 1.0.0  
**Phase:** Phase 0 (Architecture & Specification)  
**Status:** Approved Specification  

---

## Overview

FloatChat V1 supports 10 distinct categories of natural language queries spanning knowledge lookup, numerical observation analysis, spatial querying, and hybrid scientific exploration.

---

## Category 1: Retrieval (Knowledge-Only)
*Queries seeking explanations of ARGO float operations, sensor physics, or documentation definitions.*

- **Example 1.1:** "How does an ARGO float measure water temperature and salinity?"
- **Example 1.2:** "What is the PSS-78 algorithm used for in oceanography?"
- **Example 1.3:** "Explain how CTD sensors are calibrated before deployment."

---

## Category 2: Filtering (Data-Only)
*Queries requesting specific profile or measurement subsets based on coordinate bounds or parameter thresholds.*

- **Example 2.1:** "Find all profiles with salinity values greater than 35.5 PSU."
- **Example 2.2:** "Show profiles where water temperature drops below 5°C."
- **Example 2.3:** "List profiles recorded at ocean pressure greater than 1000 dbar."

---

## Category 3: Aggregation (Data-Only)
*Queries requesting count, sum, or grouped summary metrics across floats or locations.*

- **Example 3.1:** "How many profiles were recorded in the Indian Ocean in 2023?"
- **Example 3.2:** "Count the total number of measurement points recorded by float WMO 2901550."
- **Example 3.3:** "What is the total number of distinct float platforms active in the dataset?"

---

## Category 4: Statistics (Data-Only)
*Queries requesting statistical metrics (mean, min, max, median, standard deviation).*

- **Example 4.1:** "What is the average water temperature recorded at 10 dbar pressure near the Equator?"
- **Example 4.2:** "Find the minimum and maximum salinity recorded across all profiles."
- **Example 4.3:** "Compute the average pressure level for profiles in the Arabian Sea."

---

## Category 5: Temporal Analysis (Data-Only)
*Queries evaluating parameter changes across dates, months, or seasons.*

- **Example 5.1:** "Show the monthly average temperature trend at 50 dbar pressure during 2023."
- **Example 5.2:** "Find all profiles recorded between January 1, 2023 and March 31, 2023."
- **Example 5.3:** "Compare salinity values between winter and summer months in the dataset."

---

## Category 6: Pressure/Depth Analysis (Data-Only)
*Queries exploring parameter changes along vertical pressure profiles.*

- **Example 6.1:** "Show water temperature variation from 0 dbar down to 2000 dbar pressure."
- **Example 6.2:** "At what ocean pressure level does salinity reach its minimum in the profile?"
- **Example 6.3:** "Find the thermocline layer pressure range where temperature drops most rapidly."

---

## Category 7: Float-Specific (Data-Only)
*Queries targeting specific ARGO float platforms by WMO identification number.*

- **Example 7.1:** "Show all profile locations for float WMO 2901550."
- **Example 7.2:** "What is the maximum pressure reached by float WMO 2901550?"
- **Example 7.3:** "List the latest recorded temperature and salinity for float WMO 2901550."

---

## Category 8: Spatial Querying (Data-Only)
*Queries leveraging PostGIS spatial functions (`ST_MakeEnvelope`, `ST_DWithin`) for geographic filtering.*

- **Example 8.1:** "Find all float profiles located within 500 km of coordinates (75.0°E, 0.0°N)."
- **Example 8.2:** "Show profiles recorded inside the bounding box (Lat -10° to 10°, Lon 60° to 80°)."
- **Example 8.3:** "Which floats are operating in the Bay of Bengal region?"

---

## Category 9: Comparison (Data-Only)
*Queries comparing parameters across different floats, regions, or timeframes.*

- **Example 9.1:** "Compare average salinity between the Arabian Sea and the Bay of Bengal."
- **Example 9.2:** "Which float recorded higher water temperatures at 100 dbar pressure: WMO 2901550 or WMO 2901551?"
- **Example 9.3:** "Compare temperature profiles between 2022 and 2023 in the equatorial zone."

---

## Category 10: Combined / Hybrid (RAG + Data)
*Complex queries requiring parallel RAG document context and PostGIS numerical data querying.*

- **Example 10.1:** "Find floats in the Arabian Sea with temperature > 28°C and explain what sensor calibration standards apply to these readings."
- **Example 10.2:** "Show salinity profiles near 1000 dbar pressure and summarize what scientific documentation says about deep-water salinity measurement accuracy."
- **Example 10.3:** "Retrieve temperature profiles for float WMO 2901550 and explain how float buoyancy engines adjust depth."
