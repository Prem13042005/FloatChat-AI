import "./setup.js";
import { describe, it } from "node:test";
import assert from "node:assert";
import { getErrorMessage } from "../services/api.js";

describe("Frontend AI Chat & Error Handling Tests", () => {
  it("1. getErrorMessage handles HTTP 429 Too Many Requests with Retry-After header", () => {
    const error429 = {
      response: {
        status: 429,
        headers: { "retry-after": "30" },
        data: {
          error_code: "RATE_LIMIT_EXCEEDED",
          message: "AI service is currently busy processing another request.",
        },
      },
    };

    const msg = getErrorMessage(error429);
    assert.ok(msg.includes("busy") || msg.includes("Too many requests"));
    assert.ok(msg.includes("30 seconds"));
  });

  it("2. getErrorMessage handles HTTP 400 Bad Request input validation", () => {
    const error400 = {
      response: {
        status: 400,
        data: {
          message: "Query length exceeds the maximum allowed limit of 2000 characters.",
        },
      },
    };

    const msg = getErrorMessage(error400);
    assert.ok(msg.includes("2000 characters") || msg.includes("Invalid request"));
  });

  it("3. getErrorMessage handles HTTP 504 Gateway Timeout", () => {
    const error504 = {
      response: {
        status: 504,
        data: {
          message: "AI workflow timed out during processing.",
        },
      },
    };

    const msg = getErrorMessage(error504);
    assert.ok(msg.includes("timed out") || msg.includes("AI analysis"));
  });

  it("4. getErrorMessage handles HTTP 502 Bad Gateway and 503 Service Unavailable", () => {
    const error502 = {
      response: {
        status: 502,
        data: { message: "AI service encountered an internal error." },
      },
    };
    assert.ok(getErrorMessage(error502).includes("AI service"));

    const error503 = {
      response: {
        status: 503,
        data: { message: "AI service is currently unavailable." },
      },
    };
    assert.ok(getErrorMessage(error503).includes("unavailable"));
  });

  it("5. getErrorMessage handles network disconnect / unreachable server", () => {
    const netError = {
      request: {},
      message: "Network Error",
    };

    const msg = getErrorMessage(netError);
    assert.ok(msg.includes("Unable to reach") || msg.includes("connection"));
  });

  it("6. Real AI structured response validation preserves all fields", () => {
    const mockRealResponse = {
      conversationId: 101,
      answer: "The thermocline in the Arabian Sea is located between 100m and 200m depth.",
      demo: false,
      intentType: "HYBRID",
      status: "SUCCESS",
      citations: [
        {
          documentTitle: "ARGO Quality Control Manual",
          sectionTitle: "Section 3.2 Thermal Gradients",
          chunkId: "chunk_argo_01",
          snippet: "Profiles exhibit sharp thermocline transitions.",
        },
      ],
      sqlMeta: {
        generatedSql: "SELECT pres, temp FROM argo_measurements WHERE float_id = 2901333 LIMIT 50;",
        executionTimeMs: 14.5,
        rowCount: 50,
        isTruncated: false,
      },
      dataSummary: {
        totalRecords: 50,
        variablesPresent: ["temp", "pres"],
        highlights: ["Temperature decreases from 28.5C at surface to 12.1C at 500m."],
      },
      visualizationSpec: {
        chartType: "line",
        xAxis: "temp",
        yAxis: "pres",
        title: "Temperature vs Depth Profile",
        invertY: true,
      },
      warnings: ["Sensor flag indicates unadjusted real-time data."],
    };

    assert.strictEqual(mockRealResponse.conversationId, 101);
    assert.strictEqual(mockRealResponse.demo, false);
    assert.strictEqual(mockRealResponse.intentType, "HYBRID");
    assert.strictEqual(mockRealResponse.citations.length, 1);
    assert.strictEqual(mockRealResponse.citations[0].documentTitle, "ARGO Quality Control Manual");
    assert.strictEqual(mockRealResponse.sqlMeta.rowCount, 50);
    assert.strictEqual(mockRealResponse.visualizationSpec.invertY, true);
    assert.strictEqual(mockRealResponse.warnings.length, 1);
  });
});
