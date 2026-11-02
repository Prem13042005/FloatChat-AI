import { useMemo } from "react";
import {
  ResponsiveContainer,
  LineChart,
  Line,
  BarChart,
  Bar,
  ScatterChart,
  Scatter,
  PieChart,
  Pie,
  Cell,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
} from "recharts";
import { MapContainer, TileLayer, CircleMarker, Popup } from "react-leaflet";
import { BarChart2, Info, AlertTriangle, MapPin } from "lucide-react";
import {
  getScientificLabel,
  isValidCoordinate,
  SERIES_COLORS,
  formatSeriesLabel,
  prepareMultiSeriesChart,
  isTemporalAxis,
  formatTimeTick,
  formatTooltipTimestamp,
} from "../services/visualizationService";

const PIE_COLORS = ["#0284c7", "#0ea5e9", "#06b6d4", "#10b981", "#f59e0b", "#8b5cf6", "#ec4899"];

export { getScientificLabel };

/**
 * Computes pressure axis domain for vertical oceanographic profiles.
 * Anchors to [0, "auto"] when surface observations exist (min pressure between 0 and 50 dbar).
 * Preserves ["auto", "auto"] for deep-ocean profiles, negative-only, non-pressure, or invalid data.
 */
export function computePressureDomain({ isVerticalProfile, yAxis, data }) {
  if (!isVerticalProfile || !yAxis || !Array.isArray(data) || data.length === 0) {
    return ["auto", "auto"];
  }

  const yLower = String(yAxis).toLowerCase();
  const isPressureAxis = yLower.includes("press") || yLower.includes("pres");
  if (!isPressureAxis) {
    return ["auto", "auto"];
  }

  let minPressure = Infinity;
  let hasValidPositivePressure = false;

  for (const row of data) {
    if (!row || typeof row !== "object") continue;
    const val = row[yAxis];
    if (val !== null && val !== undefined && val !== "") {
      const num = Number(val);
      if (!isNaN(num) && isFinite(num)) {
        if (num >= 0) {
          hasValidPositivePressure = true;
        }
        if (num < minPressure) {
          minPressure = num;
        }
      }
    }
  }

  if (hasValidPositivePressure && minPressure >= 0 && minPressure <= 50) {
    return [0, "auto"];
  }

  return ["auto", "auto"];
}

export default function DataVisualization({ spec }) {
  if (!spec || typeof spec !== "object") {
    return null;
  }

  const {
    chartType = "line",
    xAxis,
    yAxis,
    title = "Data Visualization",
    invertY = false,
    seriesColumn,
    description,
    data = [],
  } = spec;

  const normalizedType = String(chartType || "line").toLowerCase();

  // Clean and validate data points
  const cleanData = useMemo(() => {
    if (!Array.isArray(data) || data.length === 0) return [];

    return data
      .filter((row) => row && typeof row === "object")
      .map((row) => {
        const item = { ...row };
        // Parse numeric coordinates/measurements safely
        if (xAxis && item[xAxis] !== undefined && item[xAxis] !== null) {
          const numX = Number(item[xAxis]);
          if (!isNaN(numX) && typeof item[xAxis] !== "boolean") {
            item[xAxis] = numX;
          }
        }
        if (yAxis && item[yAxis] !== undefined && item[yAxis] !== null) {
          const numY = Number(item[yAxis]);
          if (!isNaN(numY) && typeof item[yAxis] !== "boolean") {
            item[yAxis] = numY;
          }
        }
        return item;
      });
  }, [data, xAxis, yAxis]);

  // Extract and validate geographic coordinates for map visualization
  const validMapPoints = useMemo(() => {
    if (normalizedType !== "map") return [];
    if (!Array.isArray(cleanData)) return [];

    return cleanData
      .map((row) => {
        const latVal = row.latitude ?? row.lat ?? (yAxis && row[yAxis] !== undefined ? row[yAxis] : undefined);
        const lonVal = row.longitude ?? row.lon ?? row.long ?? (xAxis && row[xAxis] !== undefined ? row[xAxis] : undefined);
        const lat = Number(latVal);
        const lon = Number(lonVal);
        if (!isValidCoordinate(lat, lon)) {
          return null;
        }
        return {
          ...row,
          _lat: lat,
          _lon: lon,
          _platform: row.platform_number ?? row.platform_id ?? row.wmo_id ?? "ARGO Float",
        };
      })
      .filter(Boolean);
  }, [cleanData, normalizedType, xAxis, yAxis]);

  if (!xAxis) {
    return (
      <div className="fc-viz-container fc-viz-empty" style={{ padding: "16px", background: "#f8fafc", borderRadius: "8px", border: "1px dashed #cbd5e1" }}>
        <p style={{ margin: 0, color: "#64748b", fontSize: "0.88rem", display: "flex", alignItems: "center", gap: "6px" }}>
          <AlertTriangle size={15} />
          Visualization specification is missing required axis mappings.
        </p>
      </div>
    );
  }

  if (cleanData.length === 0) {
    return (
      <div className="fc-viz-container fc-viz-empty" style={{ padding: "16px", background: "#f8fafc", borderRadius: "8px", border: "1px dashed #cbd5e1" }}>
        <div style={{ display: "flex", alignItems: "center", gap: "8px", color: "#64748b", marginBottom: "4px" }}>
          <BarChart2 size={16} />
          <strong>{title}</strong>
        </div>
        <p style={{ margin: 0, color: "#94a3b8", fontSize: "0.85rem" }}>
          No data points available for this visualization.
        </p>
      </div>
    );
  }

  // Check if this is a vertical oceanographic profile (pressure on Y with inverted axis)
  const isVerticalProfile = Boolean(invertY) || (
    yAxis && (String(yAxis).toLowerCase().includes("press") || String(yAxis).toLowerCase().includes("pres"))
  );

  // Group observations into independent multi-series if seriesColumn contains multiple series
  const multiSeriesConfig = useMemo(() => {
    return prepareMultiSeriesChart({
      data: cleanData,
      seriesColumn,
      xAxis,
      yAxis,
      isVerticalProfile,
    });
  }, [cleanData, seriesColumn, xAxis, yAxis, isVerticalProfile]);

  const { isMultiSeries, seriesList, chartData: multiSeriesData } = multiSeriesConfig;
  const effectiveData = isMultiSeries ? multiSeriesData : cleanData;

  // Compute anchored pressure domain for vertical oceanographic profiles
  const pressureDomain = useMemo(() => {
    return computePressureDomain({
      isVerticalProfile,
      yAxis,
      data: cleanData,
    });
  }, [isVerticalProfile, yAxis, cleanData]);

  return (
    <div
      className="fc-viz-card"
      style={{
        marginTop: "16px",
        padding: "16px",
        background: "#ffffff",
        border: "1px solid #e2e8f0",
        borderRadius: "10px",
        boxShadow: "0 1px 3px rgba(0,0,0,0.05)",
      }}
    >
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: "12px", borderBottom: "1px solid #f1f5f9", paddingBottom: "8px" }}>
        <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
          {normalizedType === "map" ? <MapPin size={16} color="#0284c7" /> : <BarChart2 size={16} color="#0284c7" />}
          <h4 style={{ margin: 0, fontSize: "0.95rem", fontWeight: 600, color: "#0f172a" }}>
            {title}
          </h4>
        </div>
        <span style={{ fontSize: "0.75rem", background: "#f0f9ff", color: "#0284c7", padding: "2px 8px", borderRadius: "9999px", fontWeight: 500, textTransform: "uppercase" }}>
          {normalizedType} chart · {cleanData.length} records
        </span>
      </div>

      <div style={{ width: "100%", height: 320, minHeight: 280 }}>
        {(() => {
          switch (normalizedType) {
            case "map": {
              if (validMapPoints.length === 0) {
                return (
                  <div className="fc-viz-container fc-viz-empty" style={{ padding: "32px 16px", textAlign: "center", background: "#f8fafc", borderRadius: "8px", border: "1px dashed #cbd5e1" }}>
                    <p style={{ margin: 0, color: "#64748b", fontSize: "0.88rem", display: "flex", alignItems: "center", justifyContent: "center", gap: "6px" }}>
                      <AlertTriangle size={15} />
                      No valid geographic coordinates available for map rendering.
                    </p>
                  </div>
                );
              }

              const centerLat = validMapPoints.reduce((sum, p) => sum + p._lat, 0) / validMapPoints.length;
              const centerLon = validMapPoints.reduce((sum, p) => sum + p._lon, 0) / validMapPoints.length;

              return (
                <div style={{ width: "100%", height: "100%", borderRadius: "8px", overflow: "hidden" }}>
                  <MapContainer
                    center={[centerLat, centerLon]}
                    zoom={4}
                    scrollWheelZoom={false}
                    style={{ height: "100%", width: "100%" }}
                  >
                    <TileLayer
                      attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
                      url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
                    />
                    {validMapPoints.map((pt, idx) => (
                      <CircleMarker
                        key={idx}
                        center={[pt._lat, pt._lon]}
                        radius={7}
                        pathOptions={{ color: "#0284c7", fillColor: "#38bdf8", fillOpacity: 0.85, weight: 2 }}
                      >
                        <Popup>
                          <div style={{ fontSize: "0.85rem", lineHeight: "1.4" }}>
                            <strong>Float #{pt._platform}</strong><br />
                            <span>Lat: {pt._lat.toFixed(4)}°, Lon: {pt._lon.toFixed(4)}°</span>
                            {pt.profile_time && <div><small>{new Date(pt.profile_time).toUTCString()}</small></div>}
                            {pt.temperature_c !== undefined && <div>Temp: {pt.temperature_c}°C</div>}
                            {pt.salinity_psu !== undefined && <div>Salinity: {pt.salinity_psu} PSU</div>}
                            {pt.pressure_dbar !== undefined && <div>Pressure: {pt.pressure_dbar} dbar</div>}
                          </div>
                        </Popup>
                      </CircleMarker>
                    ))}
                  </MapContainer>
                </div>
              );
            }

            case "bar":
              return (
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={cleanData} margin={{ top: 10, right: 20, left: 10, bottom: 25 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                    <XAxis
                      dataKey={xAxis}
                      tick={{ fill: "#64748b", fontSize: 11 }}
                      stroke="#94a3b8"
                      label={{ value: getScientificLabel(xAxis), position: "insideBottom", offset: -10, fill: "#64748b", fontSize: 11 }}
                    />
                    <YAxis
                      dataKey={yAxis}
                      type="number"
                      reversed={Boolean(invertY)}
                      tick={{ fill: "#64748b", fontSize: 11 }}
                      stroke="#94a3b8"
                      label={{ value: getScientificLabel(yAxis), angle: -90, position: "insideLeft", fill: "#64748b", fontSize: 11 }}
                    />
                    <Tooltip
                      formatter={(val, name) => [val, getScientificLabel(name || yAxis)]}
                      labelFormatter={(label) => `${getScientificLabel(xAxis)}: ${label}`}
                      contentStyle={{ background: "#ffffff", borderRadius: "6px", border: "1px solid #cbd5e1", fontSize: "0.85rem" }}
                    />
                    <Legend verticalAlign="top" height={36} />
                    <Bar dataKey={yAxis || "value"} name={getScientificLabel(yAxis || "Measurement")} fill="#0284c7" radius={[4, 4, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              );

            case "scatter": {
              const scatterPoints = cleanData.filter(
                (r) =>
                  typeof r[xAxis] === "number" &&
                  !isNaN(r[xAxis]) &&
                  typeof r[yAxis] === "number" &&
                  !isNaN(r[yAxis])
              );
              return (
                <ResponsiveContainer width="100%" height="100%">
                  <ScatterChart margin={{ top: 10, right: 20, left: 10, bottom: 25 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                    <XAxis
                      dataKey={xAxis}
                      type="number"
                      domain={["auto", "auto"]}
                      tick={{ fill: "#64748b", fontSize: 11 }}
                      stroke="#94a3b8"
                      name={getScientificLabel(xAxis)}
                      label={{ value: getScientificLabel(xAxis), position: "insideBottom", offset: -10, fill: "#64748b", fontSize: 11 }}
                    />
                    <YAxis
                      dataKey={yAxis}
                      type="number"
                      domain={["auto", "auto"]}
                      reversed={Boolean(invertY)}
                      tick={{ fill: "#64748b", fontSize: 11 }}
                      stroke="#94a3b8"
                      name={getScientificLabel(yAxis)}
                      label={{ value: getScientificLabel(yAxis), angle: -90, position: "insideLeft", fill: "#64748b", fontSize: 11 }}
                    />
                    <Tooltip
                      cursor={{ strokeDasharray: "3 3" }}
                      formatter={(val, name) => [val, getScientificLabel(name || yAxis)]}
                      contentStyle={{ background: "#ffffff", borderRadius: "6px", border: "1px solid #cbd5e1", fontSize: "0.85rem" }}
                    />
                    <Legend verticalAlign="top" height={36} />
                    <Scatter name={title || "Observations"} data={scatterPoints} fill="#0ea5e9" />
                  </ScatterChart>
                </ResponsiveContainer>
              );
            }

            case "pie":
              return (
                <ResponsiveContainer width="100%" height="100%">
                  <PieChart margin={{ top: 10, right: 20, left: 20, bottom: 10 }}>
                    <Tooltip contentStyle={{ background: "#ffffff", borderRadius: "6px", border: "1px solid #cbd5e1", fontSize: "0.85rem" }} />
                    <Legend verticalAlign="bottom" height={36} />
                    <Pie
                      data={cleanData}
                      dataKey={yAxis || "value"}
                      nameKey={xAxis}
                      cx="50%"
                      cy="50%"
                      outerRadius={80}
                      label={(entry) => `${entry[xAxis]}: ${entry[yAxis || "value"]}`}
                    >
                      {cleanData.map((_, index) => (
                        <Cell key={`cell-${index}`} fill={PIE_COLORS[index % PIE_COLORS.length]} />
                      ))}
                    </Pie>
                  </PieChart>
                </ResponsiveContainer>
              );

            case "histogram":
              return (
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={cleanData} margin={{ top: 10, right: 20, left: 10, bottom: 25 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                    <XAxis
                      dataKey={xAxis || "interval"}
                      tick={{ fill: "#64748b", fontSize: 11 }}
                      stroke="#94a3b8"
                      label={{ value: getScientificLabel(xAxis || "interval"), position: "insideBottom", offset: -10, fill: "#64748b", fontSize: 11 }}
                    />
                    <YAxis
                      dataKey={yAxis || "count"}
                      type="number"
                      domain={["auto", "auto"]}
                      tick={{ fill: "#64748b", fontSize: 11 }}
                      stroke="#94a3b8"
                      label={{ value: getScientificLabel(yAxis || "count"), angle: -90, position: "insideLeft", fill: "#64748b", fontSize: 11 }}
                    />
                    <Tooltip
                      formatter={(val, name) => [val, getScientificLabel(name || yAxis || "count")]}
                      labelFormatter={(label) => `${getScientificLabel(xAxis || "interval")}: ${label}`}
                      contentStyle={{ background: "#ffffff", borderRadius: "6px", border: "1px solid #cbd5e1", fontSize: "0.85rem" }}
                    />
                    <Legend verticalAlign="top" height={36} />
                    <Bar dataKey={yAxis || "count"} name={getScientificLabel(yAxis || "count")} fill="#0284c7" radius={[4, 4, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              );

            case "line": {
              if (isVerticalProfile) {
                // Vertical oceanographic profile: Recharts layout="vertical"
                // XAxis: horizontal continuous physical measurement (Temperature or Salinity)
                // YAxis: vertical inverted pressure axis (0 dbar at surface, increasing downward)
                // Line: binds dataKey to plot horizontally across depth
                return (
                  <ResponsiveContainer width="100%" height="100%">
                    <LineChart
                      layout="vertical"
                      data={effectiveData}
                      margin={{ top: 10, right: 25, left: 15, bottom: 25 }}
                    >
                      <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                      <XAxis
                        type="number"
                        dataKey={isMultiSeries ? undefined : xAxis}
                        domain={["auto", "auto"]}
                        tick={{ fill: "#64748b", fontSize: 11 }}
                        stroke="#94a3b8"
                        label={{
                          value: getScientificLabel(xAxis),
                          position: "insideBottom",
                          offset: -10,
                          fill: "#64748b",
                          fontSize: 11,
                        }}
                      />
                      <YAxis
                        type="number"
                        dataKey={yAxis}
                        reversed={true}
                        domain={pressureDomain}
                        tick={{ fill: "#64748b", fontSize: 11 }}
                        stroke="#94a3b8"
                        label={{
                          value: getScientificLabel(yAxis),
                          angle: -90,
                          position: "insideLeft",
                          fill: "#64748b",
                          fontSize: 11,
                        }}
                      />
                      <Tooltip
                        formatter={(val, name) => [val, name || getScientificLabel(xAxis)]}
                        labelFormatter={(label) => `${getScientificLabel(yAxis)}: ${label}`}
                        contentStyle={{ background: "#ffffff", borderRadius: "6px", border: "1px solid #cbd5e1", fontSize: "0.85rem" }}
                      />
                      <Legend verticalAlign="top" height={36} />
                      {isMultiSeries ? (
                        seriesList.map((s) => (
                          <Line
                            key={s.key}
                            type="monotone"
                            dataKey={s.key}
                            name={s.label}
                            stroke={s.color}
                            strokeWidth={2}
                            dot={{ r: 3, fill: s.color }}
                            activeDot={{ r: 5 }}
                            connectNulls={true}
                          />
                        ))
                      ) : (
                        <Line
                          type="monotone"
                          dataKey={xAxis}
                          name={getScientificLabel(xAxis)}
                          stroke="#0284c7"
                          strokeWidth={2}
                          dot={{ r: 3, fill: "#0284c7" }}
                          activeDot={{ r: 5 }}
                        />
                      )}
                    </LineChart>
                  </ResponsiveContainer>
                );
              }

              // Standard horizontal time-series or trend line chart
              const isTimeAxis = isTemporalAxis(xAxis);
              return (
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={effectiveData} margin={{ top: 10, right: 20, left: 15, bottom: 25 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                    <XAxis
                      dataKey={xAxis}
                      tick={{ fill: "#64748b", fontSize: 11 }}
                      stroke="#94a3b8"
                      tickFormatter={isTimeAxis ? formatTimeTick : undefined}
                      label={{ value: getScientificLabel(xAxis), position: "insideBottom", offset: -10, fill: "#64748b", fontSize: 11 }}
                    />
                    <YAxis
                      dataKey={isMultiSeries ? undefined : yAxis}
                      type="number"
                      reversed={Boolean(invertY)}
                      domain={["auto", "auto"]}
                      tick={{ fill: "#64748b", fontSize: 11 }}
                      stroke="#94a3b8"
                      label={{ value: getScientificLabel(yAxis), angle: -90, position: "insideLeft", fill: "#64748b", fontSize: 11 }}
                    />
                    <Tooltip
                      formatter={(val, name) => [val, name || getScientificLabel(yAxis)]}
                      labelFormatter={(label) =>
                        isTimeAxis
                          ? `${getScientificLabel(xAxis)}: ${formatTooltipTimestamp(label)}`
                          : `${getScientificLabel(xAxis)}: ${label}`
                      }
                      contentStyle={{ background: "#ffffff", borderRadius: "6px", border: "1px solid #cbd5e1", fontSize: "0.85rem" }}
                    />
                    <Legend verticalAlign="top" height={36} />
                    {isMultiSeries ? (
                      seriesList.map((s) => (
                        <Line
                          key={s.key}
                          type="monotone"
                          dataKey={s.key}
                          name={s.label}
                          stroke={s.color}
                          strokeWidth={2}
                          dot={{ r: 3, fill: s.color }}
                          activeDot={{ r: 5 }}
                          connectNulls={true}
                        />
                      ))
                    ) : (
                      <Line
                        type="monotone"
                        dataKey={yAxis || "value"}
                        name={getScientificLabel(yAxis || "Measurement")}
                        stroke="#0284c7"
                        strokeWidth={2}
                        dot={{ r: 3, fill: "#0284c7" }}
                        activeDot={{ r: 5 }}
                      />
                    )}
                  </LineChart>
                </ResponsiveContainer>
              );
            }

            default:
              return (
                <div className="fc-viz-container fc-viz-unsupported" style={{ padding: "32px 16px", textAlign: "center", background: "#f8fafc", borderRadius: "8px", border: "1px dashed #cbd5e1" }}>
                  <p style={{ margin: 0, color: "#64748b", fontSize: "0.88rem", display: "flex", alignItems: "center", justifyContent: "center", gap: "6px" }}>
                    <AlertTriangle size={15} />
                    Visualization type '{normalizedType}' is not currently supported.
                  </p>
                </div>
              );
          }
        })()}
      </div>

      {description && (
        <p style={{ marginTop: "10px", marginBottom: 0, fontSize: "0.8rem", color: "#64748b", fontStyle: "italic", borderTop: "1px solid #f8fafc", paddingTop: "6px" }}>
          {description}
        </p>
      )}
    </div>
  );
}
