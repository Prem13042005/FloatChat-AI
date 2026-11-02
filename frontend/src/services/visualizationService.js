import { getVisualizations } from "./api.js";

export { getVisualizations };

export async function getVisualization(id) {
  return null;
}

/**
 * Returns formatted scientific labels and standard units for oceanographic variables.
 */
export function getScientificLabel(key) {
  if (!key) return "";
  const lower = String(key).toLowerCase();
  if (lower.includes("temperature") || lower === "temp" || lower === "temperature_c") return "Temperature (°C)";
  if (lower.includes("salinity") || lower === "psal" || lower === "salinity_psu") return "Salinity (PSU)";
  if (lower.includes("pressure") || lower === "pres" || lower === "pressure_dbar") return "Pressure (dbar)";
  if (lower === "latitude" || lower === "lat") return "Latitude (°N/°S)";
  if (lower === "longitude" || lower === "lon" || lower === "long") return "Longitude (°E/°W)";
  if (lower.includes("time") || lower.includes("date")) return "Observation Time";
  if (lower.includes("count") || lower.includes("total")) return "Observation Count";
  if (lower.includes("interval") || lower.includes("bin")) return "Measurement Interval";
  if (lower.includes("depth_range")) return "Depth Range";
  if (lower.includes("platform") || lower.includes("wmo")) return "Platform Number";
  return key;
}

/**
 * Validates geographic coordinate values within standard WGS-84 ranges.
 */
export function isValidCoordinate(lat, lon) {
  const numLat = Number(lat);
  const numLon = Number(lon);
  return (
    !isNaN(numLat) &&
    !isNaN(numLon) &&
    numLat >= -90 &&
    numLat <= 90 &&
    numLon >= -180 &&
    numLon <= 180
  );
}

export const SERIES_COLORS = [
  "#0284c7", // Ocean blue
  "#10b981", // Emerald green
  "#f59e0b", // Amber
  "#8b5cf6", // Purple
  "#ec4899", // Rose
  "#06b6d4", // Cyan
  "#f97316", // Orange
  "#6366f1", // Indigo
];

/**
 * Detects whether an axis identifier represents a temporal/date-time dimension.
 */
export function isTemporalAxis(key) {
  if (!key) return false;
  const lower = String(key).toLowerCase();
  return (
    lower.includes("time") ||
    lower.includes("date") ||
    lower === "timestamp" ||
    lower === "datetime" ||
    lower === "observation_time" ||
    lower === "profile_time"
  );
}

/**
 * Formats ISO-8601 timestamps consistently into readable UTC 'YYYY-MM-DD' tick labels.
 * Returns safe fallback strings for non-date, null, undefined or empty values.
 */
export function formatTimeTick(val) {
  if (val === null || val === undefined) return "";
  const strVal = String(val).trim();
  if (!strVal) return "";

  const d = new Date(strVal);
  if (isNaN(d.getTime())) return strVal;

  try {
    const yyyy = d.getUTCFullYear();
    const mm = String(d.getUTCMonth() + 1).padStart(2, "0");
    const dd = String(d.getUTCDate()).padStart(2, "0");
    return `${yyyy}-${mm}-${dd}`;
  } catch {
    return strVal;
  }
}

/**
 * Formats ISO-8601 timestamps into detailed UTC date-time string for tooltips.
 */
export function formatTooltipTimestamp(val) {
  if (val === null || val === undefined) return "";
  const strVal = String(val).trim();
  if (!strVal) return "";

  const d = new Date(strVal);
  if (isNaN(d.getTime())) return strVal;

  try {
    const yyyy = d.getUTCFullYear();
    const mm = String(d.getUTCMonth() + 1).padStart(2, "0");
    const dd = String(d.getUTCDate()).padStart(2, "0");
    const hh = String(d.getUTCHours()).padStart(2, "0");
    const min = String(d.getUTCMinutes()).padStart(2, "0");
    return `${yyyy}-${mm}-${dd} ${hh}:${min} UTC`;
  } catch {
    return strVal;
  }
}

/**
 * Returns formatted human-readable labels for series identifiers.
 */
export function formatSeriesLabel(seriesId, seriesColumn) {
  if (seriesId === null || seriesId === undefined) return "Series";
  const strId = String(seriesId).trim();
  const col = String(seriesColumn || "").toLowerCase();
  if (col.includes("platform") || col.includes("wmo") || col.includes("float")) {
    return strId.toLowerCase().startsWith("float") ? strId : `Float #${strId}`;
  }
  if (col.includes("cycle")) {
    return strId.toLowerCase().startsWith("cycle") ? strId : `Cycle #${strId}`;
  }
  return strId;
}

/**
 * Transforms flat tabular observations into multi-series chart structures
 * when multiple distinct series identifiers exist in `seriesColumn`.
 */
export function prepareMultiSeriesChart({
  data = [],
  seriesColumn,
  xAxis,
  yAxis,
  isVerticalProfile = false,
}) {
  if (!Array.isArray(data) || data.length === 0) {
    return {
      isMultiSeries: false,
      seriesList: [],
      chartData: [],
    };
  }

  // If seriesColumn is missing, preserve single-series behavior
  if (!seriesColumn) {
    return {
      isMultiSeries: false,
      seriesList: [],
      chartData: data,
    };
  }

  // Filter out invalid/empty/null/undefined series keys
  const validSeriesKeys = [
    ...new Set(
      data
        .map((r) => r && r[seriesColumn])
        .filter(
          (v) =>
            v !== null &&
            v !== undefined &&
            String(v).trim() !== "" &&
            String(v) !== "null" &&
            String(v) !== "undefined"
        )
    ),
  ];

  // If there are not at least 2 distinct valid series, retain single-series behavior
  if (validSeriesKeys.length < 2) {
    return {
      isMultiSeries: false,
      seriesList: [],
      chartData: data,
    };
  }

  // Define series metadata (color, label, key)
  const seriesList = validSeriesKeys.map((key, index) => ({
    key: String(key),
    rawKey: key,
    label: formatSeriesLabel(key, seriesColumn),
    color: SERIES_COLORS[index % SERIES_COLORS.length],
  }));

  const validKeySet = new Set(validSeriesKeys.map((k) => String(k)));

  if (isVerticalProfile) {
    // 1. Group observations strictly by series
    const seriesObservations = new Map();
    validSeriesKeys.forEach((k) => seriesObservations.set(String(k), []));

    data.forEach((row) => {
      if (!row || typeof row !== "object") return;
      const sVal = row[seriesColumn];
      if (sVal === null || sVal === undefined) return;
      const sKey = String(sVal);
      if (!validKeySet.has(sKey)) return;

      const pVal = Number(row[yAxis]);
      const xVal = Number(row[xAxis]);
      if (isNaN(pVal) || isNaN(xVal)) return;

      seriesObservations.get(sKey).push({
        pressure: pVal,
        val: xVal,
      });
    });

    // 2. Sort observations within each series by pressure ascending
    seriesObservations.forEach((obsList) => {
      obsList.sort((a, b) => a.pressure - b.pressure);
    });

    // 3. Pivot observations onto a unified, strictly sorted pressure grid
    const pressureMap = new Map();

    seriesObservations.forEach((obsList, sKey) => {
      obsList.forEach(({ pressure, val }) => {
        if (!pressureMap.has(pressure)) {
          pressureMap.set(pressure, { [yAxis]: pressure });
        }
        const entry = pressureMap.get(pressure);
        // Map value to this float's dedicated series key
        entry[sKey] = val;
      });
    });

    // Sort grid strictly by pressure ascending (shallow to deep)
    const chartData = Array.from(pressureMap.keys())
      .sort((a, b) => a - b)
      .map((p) => pressureMap.get(p));

    return {
      isMultiSeries: true,
      seriesList,
      chartData,
    };
  }

  // Horizontal time-series or trend line chart
  const seriesObservations = new Map();
  validSeriesKeys.forEach((k) => seriesObservations.set(String(k), []));

  data.forEach((row) => {
    if (!row || typeof row !== "object") return;
    const sVal = row[seriesColumn];
    if (sVal === null || sVal === undefined) return;
    const sKey = String(sVal);
    if (!validKeySet.has(sKey)) return;

    const xVal = row[xAxis];
    const yVal = Number(row[yAxis]);
    if (xVal === undefined || xVal === null || isNaN(yVal)) return;

    seriesObservations.get(sKey).push({
      x: xVal,
      val: yVal,
    });
  });

  const xMap = new Map();
  seriesObservations.forEach((obsList, sKey) => {
    obsList.forEach(({ x, val }) => {
      if (!xMap.has(x)) {
        xMap.set(x, { [xAxis]: x });
      }
      const entry = xMap.get(x);
      entry[sKey] = val;
    });
  });

  const chartData = Array.from(xMap.values());

  return {
    isMultiSeries: true,
    seriesList,
    chartData,
  };
}
