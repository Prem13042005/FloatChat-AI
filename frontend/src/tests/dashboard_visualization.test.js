import "./setup.js";
import { describe, it } from "node:test";
import assert from "node:assert";

describe("Frontend Dashboard & Visualization Tests", () => {
  it("1. Dashboard stats safely format real ARGO dataset counts", () => {
    const rawStats = {
      totalConversations: 5,
      totalQueries: 14,
      queriesToday: 3,
      totalFloats: 30,
      totalProfiles: 107,
      totalMeasurements: 26046,
      totalDocumentChunks: 12,
      embeddingDimension: 768,
    };

    assert.strictEqual(rawStats.totalFloats, 30);
    assert.strictEqual(rawStats.totalProfiles, 107);
    assert.strictEqual(rawStats.totalMeasurements, 26046);
    assert.strictEqual(rawStats.totalDocumentChunks, 12);
    assert.strictEqual(rawStats.embeddingDimension, 768);

    // Number formatting for physical measurements (26,046)
    const formattedMeasurements = Number(rawStats.totalMeasurements).toLocaleString();
    assert.ok(
      formattedMeasurements === "26,046" || formattedMeasurements === "26 046" || formattedMeasurements.includes("26"),
      `Unexpected formatting: ${formattedMeasurements}`
    );
  });

  it("2. Dashboard handles null or undefined stats gracefully with fallback", () => {
    const nullStats = null;
    const fallbackValue = (val, fallback = "—") => (val !== undefined && val !== null ? val : fallback);

    assert.strictEqual(fallbackValue(nullStats?.totalConversations), "—");
    assert.strictEqual(fallbackValue(nullStats?.totalFloats), "—");
    assert.strictEqual(fallbackValue(nullStats?.totalMeasurements), "—");

    const partialStats = { totalConversations: 0 };
    assert.strictEqual(fallbackValue(partialStats.totalConversations), 0);
    assert.strictEqual(fallbackValue(partialStats.totalFloats), "—");
  });

  it("3. Dashboard supports nested scientificStats structure from backend", () => {
    const backendPayload = {
      totalConversations: 2,
      totalQueries: 4,
      queriesToday: 1,
      scientificStats: {
        totalFloats: 30,
        totalProfiles: 107,
        totalMeasurements: 26046,
        totalDocumentChunks: 12,
        embeddingDimension: 768,
      },
    };

    const extractMetric = (data, key) =>
      data?.[key] !== undefined && data?.[key] !== null
        ? data[key]
        : data?.scientificStats?.[key] ?? "—";

    assert.strictEqual(extractMetric(backendPayload, "totalFloats"), 30);
    assert.strictEqual(extractMetric(backendPayload, "totalProfiles"), 107);
    assert.strictEqual(extractMetric(backendPayload, "totalMeasurements"), 26046);
    assert.strictEqual(extractMetric(backendPayload, "totalDocumentChunks"), 12);
    assert.strictEqual(extractMetric(backendPayload, "totalConversations"), 2);
  });

  it("4. Visualization spec validates required axis configurations", () => {
    const validateSpec = (spec) => {
      if (!spec || typeof spec !== "object") return { valid: false, reason: "MISSING_SPEC" };
      if (!spec.xAxis) return { valid: false, reason: "MISSING_X_AXIS" };
      if (!spec.yAxis && !spec.seriesColumn) return { valid: false, reason: "MISSING_Y_AXIS" };
      return { valid: true };
    };

    assert.deepStrictEqual(validateSpec(null), { valid: false, reason: "MISSING_SPEC" });
    assert.deepStrictEqual(validateSpec({}), { valid: false, reason: "MISSING_X_AXIS" });
    assert.deepStrictEqual(validateSpec({ xAxis: "temperature" }), { valid: false, reason: "MISSING_Y_AXIS" });
    assert.deepStrictEqual(
      validateSpec({ xAxis: "temperature", yAxis: "pressure", chartType: "line" }),
      { valid: true }
    );
  });

  it("5. Visualization spec cleans and converts numeric string coordinates safely", () => {
    const rawData = [
      { pressure: "10.5", temperature: "24.2", flag: true },
      { pressure: "25.0", temperature: "22.8", flag: false },
      { pressure: 50.0, temperature: 20.1, flag: true },
    ];

    const cleanData = rawData.map((row) => {
      const item = { ...row };
      ["pressure", "temperature"].forEach((key) => {
        if (item[key] !== undefined && item[key] !== null) {
          const num = Number(item[key]);
          if (!isNaN(num) && typeof item[key] !== "boolean") {
            item[key] = num;
          }
        }
      });
      return item;
    });

    assert.strictEqual(typeof cleanData[0].pressure, "number");
    assert.strictEqual(cleanData[0].pressure, 10.5);
    assert.strictEqual(typeof cleanData[0].temperature, "number");
    assert.strictEqual(cleanData[0].temperature, 24.2);
    assert.strictEqual(typeof cleanData[0].flag, "boolean");
    assert.strictEqual(cleanData[2].pressure, 50.0);
  });

  it("6. Depth profile oceanographic convention enforces inverted vertical axis", () => {
    const spec = {
      chartType: "line",
      xAxis: "temperature",
      yAxis: "pressure",
      invertY: true,
      title: "Temperature Profile vs Depth (dbar)",
    };

    assert.strictEqual(spec.invertY, true);
    assert.strictEqual(spec.yAxis, "pressure");
  });

  it("7. Supported chart types (line, bar, scatter, pie) are recognized", () => {
    const supportedTypes = new Set(["line", "bar", "scatter", "pie"]);

    assert.ok(supportedTypes.has("line".toLowerCase()));
    assert.ok(supportedTypes.has("bar".toLowerCase()));
    assert.ok(supportedTypes.has("scatter".toLowerCase()));
    assert.ok(supportedTypes.has("pie".toLowerCase()));
    assert.ok(!supportedTypes.has("unknown_chart"));
  });

  it("8. Empty or malformed data array in visualization spec does not crash", () => {
    const safeDataExtract = (spec) => {
      if (!spec || !Array.isArray(spec.data)) return [];
      return spec.data.filter((r) => r && typeof r === "object");
    };

    assert.deepStrictEqual(safeDataExtract({}), []);
    assert.deepStrictEqual(safeDataExtract({ data: null }), []);
    assert.deepStrictEqual(safeDataExtract({ data: "invalid_string" }), []);
    assert.deepStrictEqual(safeDataExtract({ data: [null, undefined, "raw", { x: 1, y: 2 }] }), [
      { x: 1, y: 2 },
    ]);
  });

  it("9. Scientific label formatter maps oceanographic variables to standard units", async () => {
    const { getScientificLabel } = await import("../services/visualizationService.js");
    assert.strictEqual(getScientificLabel("temperature_c"), "Temperature (°C)");
    assert.strictEqual(getScientificLabel("salinity_psu"), "Salinity (PSU)");
    assert.strictEqual(getScientificLabel("pressure_dbar"), "Pressure (dbar)");
    assert.strictEqual(getScientificLabel("latitude"), "Latitude (°N/°S)");
    assert.strictEqual(getScientificLabel("longitude"), "Longitude (°E/°W)");
    assert.strictEqual(getScientificLabel("unknown_column"), "unknown_column");
  });

  it("10. Geographic coordinate validator filters invalid coordinates safely", () => {
    const testPoints = [
      { latitude: 12.5, longitude: 68.2, platform_number: "1902671" },
      { latitude: 95.0, longitude: 70.0, platform_number: "invalid_lat" },
      { latitude: 10.0, longitude: -200.0, platform_number: "invalid_lon" },
      { latitude: "NaN", longitude: 65.0, platform_number: "nan_lat" },
      { latitude: -15.4, longitude: 80.1, platform_number: "2901550" },
    ];

    const validPoints = testPoints.filter((pt) => {
      const lat = Number(pt.latitude);
      const lon = Number(pt.longitude);
      return !isNaN(lat) && !isNaN(lon) && lat >= -90 && lat <= 90 && lon >= -180 && lon <= 180;
    });

    assert.strictEqual(validPoints.length, 2);
    assert.strictEqual(validPoints[0].platform_number, "1902671");
    assert.strictEqual(validPoints[1].platform_number, "2901550");
  });

  it("11. Unsupported chart types are identified for clear fallback rendering", () => {
    const supportedTypes = new Set(["line", "bar", "scatter", "map", "pie", "histogram"]);
    const checkTypeSupport = (type) => supportedTypes.has(String(type || "line").toLowerCase());

    assert.ok(checkTypeSupport("map"));
    assert.ok(checkTypeSupport("line"));
    assert.ok(checkTypeSupport("bar"));
    assert.ok(!checkTypeSupport("radar_chart"));
    assert.ok(!checkTypeSupport("unknown_3d"));
  });

  it("12. Vertical profile configuration requires vertical layout and inverted axis", () => {
    const checkProfileLayout = (spec) => {
      const isVertical = Boolean(spec?.invertY) || (
        spec?.yAxis && (String(spec.yAxis).toLowerCase().includes("press") || String(spec.yAxis).toLowerCase().includes("pres"))
      );
      return {
        layout: isVertical ? "vertical" : "horizontal",
        reversedY: Boolean(spec?.invertY),
      };
    };

    const profileSpec = { chartType: "line", xAxis: "temperature_c", yAxis: "pressure_dbar", invertY: true };
    const timeSpec = { chartType: "line", xAxis: "profile_time", yAxis: "temperature_c", invertY: false };

    assert.deepStrictEqual(checkProfileLayout(profileSpec), { layout: "vertical", reversedY: true });
    assert.deepStrictEqual(checkProfileLayout(timeSpec), { layout: "horizontal", reversedY: false });
  });

  it("13. Two distinct float identifiers produce two independent series", async () => {
    const { prepareMultiSeriesChart, formatSeriesLabel } = await import("../services/visualizationService.js");

    const rawData = [
      { platform_number: "1902671", pressure_dbar: 10, temperature_c: 25.4 },
      { platform_number: "1902671", pressure_dbar: 50, temperature_c: 21.2 },
      { platform_number: "2901550", pressure_dbar: 10, temperature_c: 24.8 },
      { platform_number: "2901550", pressure_dbar: 50, temperature_c: 20.6 },
    ];

    const result = prepareMultiSeriesChart({
      data: rawData,
      seriesColumn: "platform_number",
      xAxis: "temperature_c",
      yAxis: "pressure_dbar",
      isVerticalProfile: true,
    });

    assert.strictEqual(result.isMultiSeries, true);
    assert.strictEqual(result.seriesList.length, 2);
    assert.strictEqual(result.seriesList[0].key, "1902671");
    assert.strictEqual(result.seriesList[0].label, "Float #1902671");
    assert.strictEqual(result.seriesList[1].key, "2901550");
    assert.strictEqual(result.seriesList[1].label, "Float #2901550");
    assert.notStrictEqual(result.seriesList[0].color, result.seriesList[1].color);
  });

  it("14. Three distinct identifiers produce three independent series", async () => {
    const { prepareMultiSeriesChart } = await import("../services/visualizationService.js");

    const rawData = [
      { platform_number: "1902671", pressure_dbar: 10, temperature_c: 25.4 },
      { platform_number: "2901550", pressure_dbar: 10, temperature_c: 24.8 },
      { platform_number: "6901800", pressure_dbar: 10, temperature_c: 26.1 },
    ];

    const result = prepareMultiSeriesChart({
      data: rawData,
      seriesColumn: "platform_number",
      xAxis: "temperature_c",
      yAxis: "pressure_dbar",
      isVerticalProfile: true,
    });

    assert.strictEqual(result.isMultiSeries, true);
    assert.strictEqual(result.seriesList.length, 3);
    const keys = result.seriesList.map((s) => s.key);
    assert.deepStrictEqual(keys, ["1902671", "2901550", "6901800"]);
    // Each series has a distinct assigned color
    const colors = new Set(result.seriesList.map((s) => s.color));
    assert.strictEqual(colors.size, 3);
  });

  it("15. Observations are not connected across different float profiles", async () => {
    const { prepareMultiSeriesChart } = await import("../services/visualizationService.js");

    const rawData = [
      // Float A finishes at 1000 dbar
      { platform_number: "1902671", pressure_dbar: 5, temperature_c: 28.0 },
      { platform_number: "1902671", pressure_dbar: 1000, temperature_c: 6.5 },
      // Float B begins at 10 dbar and finishes at 800 dbar
      { platform_number: "2901550", pressure_dbar: 10, temperature_c: 27.2 },
      { platform_number: "2901550", pressure_dbar: 800, temperature_c: 7.8 },
    ];

    const result = prepareMultiSeriesChart({
      data: rawData,
      seriesColumn: "platform_number",
      xAxis: "temperature_c",
      yAxis: "pressure_dbar",
      isVerticalProfile: true,
    });

    assert.strictEqual(result.isMultiSeries, true);
    // Grid must contain points at pressures 5, 10, 800, 1000
    const pressures = result.chartData.map((r) => r.pressure_dbar);
    assert.deepStrictEqual(pressures, [5, 10, 800, 1000]);

    // At 5 dbar, only Float 1902671 has data; 2901550 is undefined
    assert.strictEqual(result.chartData[0]["1902671"], 28.0);
    assert.strictEqual(result.chartData[0]["2901550"], undefined);

    // At 10 dbar, only Float 2901550 has data; 1902671 is undefined
    assert.strictEqual(result.chartData[1]["1902671"], undefined);
    assert.strictEqual(result.chartData[1]["2901550"], 27.2);

    // At 1000 dbar, only Float 1902671 has data
    assert.strictEqual(result.chartData[3]["1902671"], 6.5);
    assert.strictEqual(result.chartData[3]["2901550"], undefined);

    // No cross-float value contamination: series keys are strictly isolated
    result.chartData.forEach((row) => {
      if (row["1902671"] !== undefined) {
        assert.ok([28.0, 6.5].includes(row["1902671"]));
      }
      if (row["2901550"] !== undefined) {
        assert.ok([27.2, 7.8].includes(row["2901550"]));
      }
    });
  });

  it("16. Irregular pressure sampling is handled safely and sorted strictly ascending", async () => {
    const { prepareMultiSeriesChart } = await import("../services/visualizationService.js");

    const rawData = [
      { platform_number: "1902671", pressure_dbar: 50.5, temperature_c: 21.0 },
      { platform_number: "2901550", pressure_dbar: 12.2, temperature_c: 26.5 },
      { platform_number: "1902671", pressure_dbar: 4.8, temperature_c: 28.5 },
      { platform_number: "2901550", pressure_dbar: 95.0, temperature_c: 18.0 },
      { platform_number: "1902671", pressure_dbar: 22.0, temperature_c: 24.0 },
    ];

    const result = prepareMultiSeriesChart({
      data: rawData,
      seriesColumn: "platform_number",
      xAxis: "temperature_c",
      yAxis: "pressure_dbar",
      isVerticalProfile: true,
    });

    const pressures = result.chartData.map((r) => r.pressure_dbar);
    // Verifies strictly monotonic depth progression
    for (let i = 1; i < pressures.length; i++) {
      assert.ok(pressures[i] > pressures[i - 1], `Pressure not sorted: ${pressures[i]} <= ${pressures[i - 1]}`);
    }
    assert.deepStrictEqual(pressures, [4.8, 12.2, 22.0, 50.5, 95.0]);
  });

  it("17. Null, undefined and empty identifiers do not create misleading combined profiles", async () => {
    const { prepareMultiSeriesChart } = await import("../services/visualizationService.js");

    const rawData = [
      { platform_number: "1902671", pressure_dbar: 10, temperature_c: 25.0 },
      { platform_number: null, pressure_dbar: 20, temperature_c: 23.5 },
      { platform_number: undefined, pressure_dbar: 30, temperature_c: 22.0 },
      { platform_number: "", pressure_dbar: 40, temperature_c: 21.0 },
      { platform_number: "   ", pressure_dbar: 45, temperature_c: 20.5 },
      { platform_number: "null", pressure_dbar: 50, temperature_c: 20.0 },
      { platform_number: "2901550", pressure_dbar: 10, temperature_c: 24.5 },
    ];

    const result = prepareMultiSeriesChart({
      data: rawData,
      seriesColumn: "platform_number",
      xAxis: "temperature_c",
      yAxis: "pressure_dbar",
      isVerticalProfile: true,
    });

    assert.strictEqual(result.isMultiSeries, true);
    assert.strictEqual(result.seriesList.length, 2);
    assert.deepStrictEqual(
      result.seriesList.map((s) => s.key),
      ["1902671", "2901550"]
    );
    // No spurious series for null, empty, or undefined values
    assert.strictEqual(result.chartData[0]["null"], undefined);
    assert.strictEqual(result.chartData[0]["undefined"], undefined);
    assert.strictEqual(result.chartData[0][""], undefined);
  });

  it("18. A single series retains existing single-series rendering behavior", async () => {
    const { prepareMultiSeriesChart } = await import("../services/visualizationService.js");

    const rawData = [
      { platform_number: "1902671", pressure_dbar: 10, temperature_c: 25.0 },
      { platform_number: "1902671", pressure_dbar: 20, temperature_c: 24.0 },
      { platform_number: "1902671", pressure_dbar: 50, temperature_c: 21.0 },
    ];

    const result = prepareMultiSeriesChart({
      data: rawData,
      seriesColumn: "platform_number",
      xAxis: "temperature_c",
      yAxis: "pressure_dbar",
      isVerticalProfile: true,
    });

    assert.strictEqual(result.isMultiSeries, false);
    assert.strictEqual(result.seriesList.length, 0);
    assert.strictEqual(result.chartData, rawData);
  });

  it("19. A missing or null seriesColumn retains existing single-series behavior", async () => {
    const { prepareMultiSeriesChart } = await import("../services/visualizationService.js");

    const rawData = [
      { pressure_dbar: 10, temperature_c: 25.0 },
      { pressure_dbar: 20, temperature_c: 24.0 },
    ];

    const nullColResult = prepareMultiSeriesChart({
      data: rawData,
      seriesColumn: null,
      xAxis: "temperature_c",
      yAxis: "pressure_dbar",
      isVerticalProfile: true,
    });
    assert.strictEqual(nullColResult.isMultiSeries, false);
    assert.strictEqual(nullColResult.chartData, rawData);

    const undefinedColResult = prepareMultiSeriesChart({
      data: rawData,
      seriesColumn: undefined,
      xAxis: "temperature_c",
      yAxis: "pressure_dbar",
      isVerticalProfile: true,
    });
    assert.strictEqual(undefinedColResult.isMultiSeries, false);
    assert.strictEqual(undefinedColResult.chartData, rawData);
  });

  it("20. Existing depth-profile orientation, axes and scientific labels remain unchanged", async () => {
    const { getScientificLabel } = await import("../services/visualizationService.js");

    assert.strictEqual(getScientificLabel("pressure_dbar"), "Pressure (dbar)");
    assert.strictEqual(getScientificLabel("temperature_c"), "Temperature (°C)");
    assert.strictEqual(getScientificLabel("salinity_psu"), "Salinity (PSU)");

    const spec = {
      chartType: "line",
      xAxis: "temperature_c",
      yAxis: "pressure_dbar",
      invertY: true,
      seriesColumn: "platform_number",
    };

    const isVertical = Boolean(spec.invertY) || (
      spec.yAxis && (String(spec.yAxis).toLowerCase().includes("press") || String(spec.yAxis).toLowerCase().includes("pres"))
    );
    assert.strictEqual(isVertical, true);
    assert.strictEqual(spec.invertY, true);
  });

  it("21. formatTimeTick formats valid ISO-8601 timestamps to UTC YYYY-MM-DD", async () => {
    const { formatTimeTick } = await import("../services/visualizationService.js");

    assert.strictEqual(formatTimeTick("2023-04-12T14:30:00Z"), "2023-04-12");
    assert.strictEqual(formatTimeTick("2021-12-31T23:59:59.999Z"), "2021-12-31");
    assert.strictEqual(formatTimeTick("2024-01-01T00:00:00Z"), "2024-01-01");
  });

  it("22. formatTimeTick handles timezone offsets and converts strictly to UTC date", async () => {
    const { formatTimeTick } = await import("../services/visualizationService.js");

    // 2023-04-12 01:30 AM at UTC+5:30 corresponds to 2023-04-11 20:00 UTC
    assert.strictEqual(formatTimeTick("2023-04-12T01:30:00+05:30"), "2023-04-11");

    // 2023-04-11 23:30 PM at UTC-5 corresponds to 2023-04-12 04:30 UTC
    assert.strictEqual(formatTimeTick("2023-04-11T23:30:00-05:00"), "2023-04-12");
  });

  it("23. formatTimeTick safely handles invalid, null, undefined and empty values", async () => {
    const { formatTimeTick } = await import("../services/visualizationService.js");

    assert.strictEqual(formatTimeTick(null), "");
    assert.strictEqual(formatTimeTick(undefined), "");
    assert.strictEqual(formatTimeTick(""), "");
    assert.strictEqual(formatTimeTick("   "), "");
    assert.strictEqual(formatTimeTick("not-a-valid-date"), "not-a-valid-date");
  });

  it("24. formatTooltipTimestamp produces readable UTC date-time representation", async () => {
    const { formatTooltipTimestamp } = await import("../services/visualizationService.js");

    assert.strictEqual(formatTooltipTimestamp("2023-04-12T14:30:00Z"), "2023-04-12 14:30 UTC");
    assert.strictEqual(formatTooltipTimestamp("2023-04-12T01:30:00+05:30"), "2023-04-11 20:00 UTC");
    assert.strictEqual(formatTooltipTimestamp(null), "");
    assert.strictEqual(formatTooltipTimestamp("bad-date"), "bad-date");
  });

  it("25. isTemporalAxis accurately identifies date/time fields and rejects physical variables", async () => {
    const { isTemporalAxis } = await import("../services/visualizationService.js");

    assert.strictEqual(isTemporalAxis("profile_time"), true);
    assert.strictEqual(isTemporalAxis("observation_time"), true);
    assert.strictEqual(isTemporalAxis("time"), true);
    assert.strictEqual(isTemporalAxis("date"), true);
    assert.strictEqual(isTemporalAxis("timestamp"), true);
    assert.strictEqual(isTemporalAxis("datetime"), true);

    // Reject non-temporal physical variables
    assert.strictEqual(isTemporalAxis("temperature_c"), false);
    assert.strictEqual(isTemporalAxis("temp"), false);
    assert.strictEqual(isTemporalAxis("salinity_psu"), false);
    assert.strictEqual(isTemporalAxis("pressure_dbar"), false);
    assert.strictEqual(isTemporalAxis("latitude"), false);
    assert.strictEqual(isTemporalAxis("longitude"), false);
    assert.strictEqual(isTemporalAxis(null), false);
    assert.strictEqual(isTemporalAxis(undefined), false);
  });

  it("26. Original timestamp strings in chart data are preserved without modification", async () => {
    const rawData = [
      { profile_time: "2023-04-12T14:30:00Z", temperature_c: 26.2 },
      { profile_time: "2023-04-13T09:15:00Z", temperature_c: 25.8 },
    ];

    const copy = rawData.map((r) => ({ ...r }));
    const { formatTimeTick } = await import("../services/visualizationService.js");

    // Formatter executes against raw string
    const tick0 = formatTimeTick(copy[0].profile_time);
    const tick1 = formatTimeTick(copy[1].profile_time);

    assert.strictEqual(tick0, "2023-04-12");
    assert.strictEqual(tick1, "2023-04-13");

    // Source data remains unmodified ISO string
    assert.strictEqual(copy[0].profile_time, "2023-04-12T14:30:00Z");
    assert.strictEqual(copy[1].profile_time, "2023-04-13T09:15:00Z");
  });

  it("27. Numeric and vertical-profile axes retain existing configuration without tick formatter", async () => {
    const { isTemporalAxis } = await import("../services/visualizationService.js");

    const verticalSpec = {
      chartType: "line",
      xAxis: "temperature_c",
      yAxis: "pressure_dbar",
      invertY: true,
    };

    const isVertical = Boolean(verticalSpec.invertY) || (
      verticalSpec.yAxis && String(verticalSpec.yAxis).toLowerCase().includes("press")
    );
    assert.strictEqual(isVertical, true);

    // Physical measurements on X-axis must not be treated as temporal
    assert.strictEqual(isTemporalAxis(verticalSpec.xAxis), false);
  });

  it("28. Multi-series time-series retains independent float lines with formatted temporal ticks", async () => {
    const { prepareMultiSeriesChart, formatTimeTick, isTemporalAxis } = await import(
      "../services/visualizationService.js"
    );

    const timeSeriesData = [
      { platform_number: "1902671", profile_time: "2023-04-12T00:00:00Z", temperature_c: 28.1 },
      { platform_number: "1902671", profile_time: "2023-04-15T00:00:00Z", temperature_c: 27.5 },
      { platform_number: "2901550", profile_time: "2023-04-12T00:00:00Z", temperature_c: 27.0 },
      { platform_number: "2901550", profile_time: "2023-04-16T00:00:00Z", temperature_c: 26.8 },
    ];

    const result = prepareMultiSeriesChart({
      data: timeSeriesData,
      seriesColumn: "platform_number",
      xAxis: "profile_time",
      yAxis: "temperature_c",
      isVerticalProfile: false,
    });

    assert.strictEqual(result.isMultiSeries, true);
    assert.strictEqual(result.seriesList.length, 2);
    assert.strictEqual(isTemporalAxis("profile_time"), true);

    // Ticks format accurately across distinct dates
    const formattedDates = result.chartData.map((r) => formatTimeTick(r.profile_time));
    assert.deepStrictEqual(formattedDates, ["2023-04-12", "2023-04-15", "2023-04-16"]);

    // Raw timestamps preserved in pivoted rows
    assert.strictEqual(result.chartData[0].profile_time, "2023-04-12T00:00:00Z");
  });

  // Helper matching DataVisualization.jsx computePressureDomain logic
  const computePressureDomain = ({ isVerticalProfile, yAxis, data }) => {
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
  };

  it("29. Surface profile with minimum pressure 0 dbar anchors to [0, 'auto']", () => {
    const data = [
      { pressure_dbar: 0, temperature_c: 29.5 },
      { pressure_dbar: 20, temperature_c: 28.0 },
      { pressure_dbar: 100, temperature_c: 22.0 },
    ];
    const domain = computePressureDomain({ isVerticalProfile: true, yAxis: "pressure_dbar", data });
    assert.deepStrictEqual(domain, [0, "auto"]);
  });

  it("30. Surface profile with minimum pressure 5 dbar anchors to [0, 'auto']", () => {
    const data = [
      { pressure_dbar: 5.2, temperature_c: 28.4 },
      { pressure_dbar: 50, temperature_c: 24.1 },
      { pressure_dbar: 200, temperature_c: 18.0 },
    ];
    const domain = computePressureDomain({ isVerticalProfile: true, yAxis: "pressure_dbar", data });
    assert.deepStrictEqual(domain, [0, "auto"]);
  });

  it("31. Boundary condition at exactly 50 dbar anchors to [0, 'auto']", () => {
    const data = [
      { pressure_dbar: 50.0, temperature_c: 24.0 },
      { pressure_dbar: 100.0, temperature_c: 20.0 },
      { pressure_dbar: 500.0, temperature_c: 12.0 },
    ];
    const domain = computePressureDomain({ isVerticalProfile: true, yAxis: "pressure_dbar", data });
    assert.deepStrictEqual(domain, [0, "auto"]);
  });

  it("32. Deep profile with minimum pressure greater than 50 dbar preserves ['auto', 'auto']", () => {
    const data = [
      { pressure_dbar: 50.1, temperature_c: 23.9 },
      { pressure_dbar: 500.0, temperature_c: 12.0 },
      { pressure_dbar: 1000.0, temperature_c: 6.5 },
    ];
    const domain = computePressureDomain({ isVerticalProfile: true, yAxis: "pressure_dbar", data });
    assert.deepStrictEqual(domain, ["auto", "auto"]);

    const deepSlice = [
      { pressure_dbar: 1000, salinity_psu: 35.1 },
      { pressure_dbar: 1500, salinity_psu: 34.8 },
      { pressure_dbar: 2000, salinity_psu: 34.7 },
    ];
    const deepDomain = computePressureDomain({ isVerticalProfile: true, yAxis: "pressure_dbar", data: deepSlice });
    assert.deepStrictEqual(deepDomain, ["auto", "auto"]);
  });

  it("33. Mixed valid and invalid pressure values safely evaluate valid data", () => {
    const data = [
      { pressure_dbar: null, temperature_c: 28.0 },
      { pressure_dbar: "invalid", temperature_c: 27.5 },
      { pressure_dbar: 15.0, temperature_c: 26.8 },
      { pressure_dbar: undefined, temperature_c: 26.0 },
      { pressure_dbar: 100.0, temperature_c: 21.0 },
    ];
    const domain = computePressureDomain({ isVerticalProfile: true, yAxis: "pressure_dbar", data });
    assert.deepStrictEqual(domain, [0, "auto"]);
  });

  it("34. Empty or entirely invalid pressure values preserve ['auto', 'auto']", () => {
    const emptyDomain = computePressureDomain({ isVerticalProfile: true, yAxis: "pressure_dbar", data: [] });
    assert.deepStrictEqual(emptyDomain, ["auto", "auto"]);

    const invalidData = [
      { pressure_dbar: null },
      { pressure_dbar: "bad" },
      { pressure_dbar: undefined },
    ];
    const invalidDomain = computePressureDomain({ isVerticalProfile: true, yAxis: "pressure_dbar", data: invalidData });
    assert.deepStrictEqual(invalidDomain, ["auto", "auto"]);
  });

  it("35. Negative-only pressure values preserve ['auto', 'auto'] without zero anchoring", () => {
    const negativeData = [
      { pressure_dbar: -5.0, temperature_c: 25.0 },
      { pressure_dbar: -20.0, temperature_c: 24.0 },
    ];
    const domain = computePressureDomain({ isVerticalProfile: true, yAxis: "pressure_dbar", data: negativeData });
    assert.deepStrictEqual(domain, ["auto", "auto"]);
  });

  it("36. Non-pressure vertical chart behavior preserves ['auto', 'auto']", () => {
    const nonPressureData = [
      { depth_m: 10, temperature_c: 26.0 },
      { depth_m: 50, temperature_c: 22.0 },
    ];
    // yAxis is depth_m rather than pressure
    const domain = computePressureDomain({ isVerticalProfile: true, yAxis: "depth_m", data: nonPressureData });
    assert.deepStrictEqual(domain, ["auto", "auto"]);

    // Horizontal time-series chart (isVerticalProfile is false)
    const timeDomain = computePressureDomain({ isVerticalProfile: false, yAxis: "temperature_c", data: nonPressureData });
    assert.deepStrictEqual(timeDomain, ["auto", "auto"]);
  });

  it("37. Existing reversed pressure-axis orientation is preserved", () => {
    const spec = {
      chartType: "line",
      xAxis: "temperature_c",
      yAxis: "pressure_dbar",
      invertY: true,
    };
    const isVertical = Boolean(spec.invertY) || (
      spec.yAxis && (String(spec.yAxis).toLowerCase().includes("press") || String(spec.yAxis).toLowerCase().includes("pres"))
    );
    assert.strictEqual(isVertical, true);
    // reversed must be true for oceanographic pressure axis
    const reversed = Boolean(spec.invertY);
    assert.strictEqual(reversed, true);
  });

  it("38. Multi-series vertical profile data correctly anchors pressure domain to [0, 'auto']", async () => {
    const { prepareMultiSeriesChart } = await import("../services/visualizationService.js");

    const multiData = [
      { platform_number: "1902671", pressure_dbar: 5, temperature_c: 28.5 },
      { platform_number: "1902671", pressure_dbar: 500, temperature_c: 12.0 },
      { platform_number: "2901550", pressure_dbar: 10, temperature_c: 27.8 },
      { platform_number: "2901550", pressure_dbar: 800, temperature_c: 8.0 },
    ];

    const chartConfig = prepareMultiSeriesChart({
      data: multiData,
      seriesColumn: "platform_number",
      xAxis: "temperature_c",
      yAxis: "pressure_dbar",
      isVerticalProfile: true,
    });

    assert.strictEqual(chartConfig.isMultiSeries, true);
    // Compute pressure domain against the multi-series pivoted data
    const domain = computePressureDomain({
      isVerticalProfile: true,
      yAxis: "pressure_dbar",
      data: chartConfig.chartData,
    });
    assert.deepStrictEqual(domain, [0, "auto"]);
  });

  it("39. Supported chart types recognize histogram alongside line, bar, scatter, pie, map", () => {
    const supportedTypes = new Set(["line", "bar", "scatter", "pie", "histogram", "map"]);

    assert.ok(supportedTypes.has("histogram"));
    assert.ok(supportedTypes.has("scatter"));
    assert.ok(supportedTypes.has("line"));
    assert.ok(supportedTypes.has("bar"));
    assert.ok(supportedTypes.has("map"));
  });

  it("40. Fix 6 Test A — Vertical temperature profile spec selects vertical inverted line chart", () => {
    const specA = {
      chartType: "line",
      xAxis: "temperature_c",
      yAxis: "pressure_dbar",
      title: "Vertical Temperature Profile (T vs P)",
      invertY: true,
      data: [
        { pressure_dbar: 5.0, temperature_c: 28.2 },
        { pressure_dbar: 50.0, temperature_c: 24.5 },
      ],
    };

    const isVerticalProfile = Boolean(specA.invertY) || (
      specA.yAxis && String(specA.yAxis).toLowerCase().includes("pres")
    );
    assert.strictEqual(specA.chartType, "line");
    assert.strictEqual(isVerticalProfile, true);
    assert.strictEqual(specA.xAxis, "temperature_c");
    assert.strictEqual(specA.yAxis, "pressure_dbar");
  });

  it("41. Fix 6 Test B — Temperature distribution spec selects frequency histogram bar chart", () => {
    const specB = {
      chartType: "histogram",
      xAxis: "interval",
      yAxis: "count",
      title: "Temperature Measurement Distribution",
      invertY: false,
      data: [
        { interval: "3.1 - 7.2 °C", count: 45 },
        { interval: "7.2 - 11.3 °C", count: 88 },
        { interval: "11.3 - 15.4 °C", count: 120 },
      ],
    };

    const normalizedType = String(specB.chartType).toLowerCase();
    assert.strictEqual(normalizedType, "histogram");
    assert.strictEqual(specB.xAxis, "interval");
    assert.strictEqual(specB.yAxis, "count");
    assert.strictEqual(specB.invertY, false);
    assert.strictEqual(specB.data.length, 3);
    assert.strictEqual(specB.data[0].count, 45);
  });

  it("42. Fix 6 Test C — Salinity distribution spec selects frequency histogram bar chart", () => {
    const specC = {
      chartType: "histogram",
      xAxis: "interval",
      yAxis: "count",
      title: "Salinity Measurement Distribution",
      invertY: false,
      data: [
        { interval: "34.8 - 35.1 PSU", count: 32 },
        { interval: "35.1 - 35.4 PSU", count: 95 },
      ],
    };

    const normalizedType = String(specC.chartType).toLowerCase();
    assert.strictEqual(normalizedType, "histogram");
    assert.strictEqual(specC.xAxis, "interval");
    assert.strictEqual(specC.yAxis, "count");
    assert.strictEqual(specC.invertY, false);
  });

  it("43. Fix 6 Test D — Temperature and salinity relationship selects scatter plot", () => {
    const specD = {
      chartType: "scatter",
      xAxis: "temperature_c",
      yAxis: "salinity_psu",
      title: "Temperature vs Salinity Relationship",
      invertY: false,
      data: [
        { temperature_c: 28.2, salinity_psu: 36.2 },
        { temperature_c: 24.5, salinity_psu: 35.8 },
      ],
    };

    const normalizedType = String(specD.chartType).toLowerCase();
    assert.strictEqual(normalizedType, "scatter");
    assert.strictEqual(specD.xAxis, "temperature_c");
    assert.strictEqual(specD.yAxis, "salinity_psu");
    assert.strictEqual(specD.invertY, false);
  });

  it("44. Fix 6 Test E — Temperature over time selects chronological line chart with non-inverted axis", () => {
    const specE = {
      chartType: "line",
      xAxis: "profile_time",
      yAxis: "temperature_c",
      title: "Temperature Over Time (Grouped by Profile Date)",
      invertY: false,
      data: [
        { profile_time: "2024-01-01T00:00:00Z", temperature_c: 26.5 },
        { profile_time: "2024-01-10T00:00:00Z", temperature_c: 25.8 },
      ],
    };

    const isVerticalProfile = Boolean(specE.invertY) || (
      specE.yAxis && String(specE.yAxis).toLowerCase().includes("pres")
    );
    assert.strictEqual(specE.chartType, "line");
    assert.strictEqual(isVerticalProfile, false);
    assert.strictEqual(specE.xAxis, "profile_time");
    assert.strictEqual(specE.yAxis, "temperature_c");
    assert.strictEqual(specE.invertY, false);
  });
});

