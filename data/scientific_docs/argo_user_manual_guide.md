# ARGO User Manual and Mission Operations Guide

## 1. Introduction to the ARGO Float Program
The international ARGO program maintains a global array of robotic profiling floats designed to observe the temperature, salinity, and velocity structure of the upper 2,000 meters of the global ocean. ARGO floats operate autonomously across multi-year missions, typically lasting four to five years, and provide continuous real-time and delayed-mode physical oceanographic data.

## 2. Typical Float Operational Cycle
The standard operational mission cycle of an ARGO profiling float follows a repetitive sequence governed by automated hydraulic buoyancy control:
- **Surface Interval and Satellite Telemetry**: The float transmits collected vertical profile data and GPS surface coordinates via satellite transmission (Argos or Iridium telecommunication networks) to ground receiving stations.
- **Descent to Parking Depth**: Hydraulic oil is transferred from an external bladder to an internal reservoir, increasing the overall float density. The float submerges and descends to its designated drift depth, typically 1,000 decibars (dbar).
- **Subsurface Drift Phase**: The float drifts passively at parking depth for approximately 9 to 10 days, tracking deep ocean currents and intermediate water mass circulation.
- **Descent to Profiling Depth**: At the end of the drift phase, additional oil is transferred internally, causing the float to sink to its maximum profiling depth, typically 2,000 decibars.
- **Ascent and CTD Sampling**: The float pumps oil into the external bladder, decreasing density and initiating buoyant ascent at approximately 10 centimeters per second. During the ascent, the onboard CTD sensor package records continuous temperature, salinity, and hydrostatic pressure measurements from 2,000 dbar to the ocean surface.

## 3. Platform Identification and Metadata Conventions
Every ARGO float platform is assigned a unique World Meteorological Organization (WMO) identifier. The 7-digit WMO platform number uniquely identifies the physical instrument across international oceanographic repositories and data distribution centres (GDACs). Essential platform metadata includes float model, transmission system, sensor serial numbers, initial deployment date, deployment coordinates in WGS84 decimal degrees, and country of origin.
