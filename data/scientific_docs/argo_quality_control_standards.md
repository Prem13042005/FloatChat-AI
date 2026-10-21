# ARGO Quality Control and Data Validation Standards

## 1. Real-Time Quality Control (RTQC) Architecture
All profile data gathered by ARGO floats undergo automated real-time quality control checks before dissemination on the Global Telecommunication System (GTS) and Global Data Assembly Centres (GDACs). RTQC tests verify the physical plausibility and integrity of telemetry without human intervention within 24 to 48 hours of acquisition.

Key RTQC tests include:
- **Platform Identification Test**: Ensures the WMO identifier matches approved international registry lists.
- **Impossible Date and Location Test**: Validates timestamps against UTC standards and ensures latitude and longitude fall strictly within valid geographic coordinate boundaries (-90° to +90° latitude, -180° to +180° longitude).
- **Global Range Test**: Confirms that measurements lie within globally observed physical bounds:
  - Temperature: -2.5°C to +40.0°C.
  - Practical Salinity: 0.0 to 45.0 PSU.
  - Hydrostatic Pressure: -5.0 to 2400.0 dbar.
- **Spike Test**: Identifies anomalous single-point deviations relative to neighboring vertical levels using second-difference formulations.
- **Gradient Test**: Detects unrealistically steep temperature or salinity vertical gradients between adjacent pressure levels.
- **Stuck Value Test**: Detects sensor failure where consecutive measurements record identical floating-point values over extended pressure intervals.

## 2. ARGO Data Quality Flagging Conventions
ARGO profiles use a standardized single-digit quality control flag assigned to each individual measurement level and profile record:
- **Flag 1 (Good Data)**: Measurement has passed all real-time QC tests and is considered physically reliable.
- **Flag 2 (Probably Good Data)**: Measurement is within acceptable bounds with minor anomalies.
- **Flag 3 (Bad Data That Are Potentially Correctable)**: Measurement exhibits known sensor bias or drift that may be adjusted during Delayed-Mode Quality Control (DMQC).
- **Flag 4 (Bad Data)**: Measurement failed critical QC tests and must be excluded from scientific analysis.
- **Flag 9 (Missing Value)**: Measurement was not recorded or parameter was omitted.

## 3. Delayed-Mode Quality Control (DMQC)
Delayed-mode quality control is performed by expert oceanographic regional centers 6 to 12 months post-acquisition. DMQC evaluates long-term sensor stability, detects conductivity cell bio-fouling or calibration drift by comparing observed deep-water salinity against historical reference hydrographic climatologies (such as the WOCE and CTD reference databases), and applies objective mapping algorithms to calculate salinity and pressure drift corrections.
