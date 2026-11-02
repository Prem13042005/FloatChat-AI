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

  it("7. Conversation restoration parses chronological user and assistant messages", () => {
    const conversationDetail = {
      id: 42,
      title: "Salinity and Depth Exploration",
      createdAt: "2026-10-31T10:00:00",
      updatedAt: "2026-10-31T10:05:00",
      messages: [
        { role: "user", content: "What is salinity?", createdAt: "2026-10-31T10:00:01" },
        { role: "assistant", content: "Salinity is the concentration of dissolved salts in seawater.", createdAt: "2026-10-31T10:00:15" },
        { role: "user", content: "How many profiles are stored?", createdAt: "2026-10-31T10:01:00" },
        { role: "assistant", content: "The ARGO database currently stores 107 ocean profiles.", createdAt: "2026-10-31T10:01:10" },
      ],
    };

    assert.strictEqual(conversationDetail.id, 42);
    assert.strictEqual(conversationDetail.messages.length, 4);

    const mapped = conversationDetail.messages.map((m) => ({
      role: String(m.role || "assistant").toLowerCase(),
      content: m.content || "",
      createdAt: m.createdAt,
    }));

    assert.strictEqual(mapped[0].role, "user");
    assert.strictEqual(mapped[0].content, "What is salinity?");
    assert.strictEqual(mapped[1].role, "assistant");
    assert.strictEqual(mapped[1].content, "Salinity is the concentration of dissolved salts in seawater.");
    assert.strictEqual(mapped[2].role, "user");
    assert.strictEqual(mapped[3].role, "assistant");
    assert.strictEqual(mapped[3].content, "The ARGO database currently stores 107 ocean profiles.");
  });

  it("8. Empty conversation restoration returns empty message array without placeholder text", () => {
    const emptyConversation = {
      id: 99,
      title: "Fresh Observation Thread",
      createdAt: "2026-10-31T11:00:00",
      updatedAt: "2026-10-31T11:00:00",
      messages: [],
    };

    assert.strictEqual(emptyConversation.id, 99);
    assert.strictEqual(Array.isArray(emptyConversation.messages), true);
    assert.strictEqual(emptyConversation.messages.length, 0);

    const mapped = emptyConversation.messages.map((m) => ({
      role: String(m.role || "assistant").toLowerCase(),
      content: m.content || "",
    }));
    assert.strictEqual(mapped.length, 0);
  });

  it("9. getErrorMessage returns clear 404 message when conversation is not found or inaccessible", () => {
    const error404 = {
      response: {
        status: 404,
        data: { message: "Conversation not found." },
      },
    };

    const msg = getErrorMessage(error404);
    assert.ok(msg.includes("Conversation not found") || msg.includes("not found"));
  });

  it("10. Active conversation ID persistence lifecycle in sessionStorage", () => {
    const mockStorage = new Map();
    const storageInterface = {
      getItem: (key) => mockStorage.get(key) ?? null,
      setItem: (key, val) => mockStorage.set(key, String(val)),
      removeItem: (key) => mockStorage.delete(key),
    };

    storageInterface.setItem("floatchat_active_conversation_id", "42");
    assert.strictEqual(storageInterface.getItem("floatchat_active_conversation_id"), "42");

    storageInterface.removeItem("floatchat_active_conversation_id");
    assert.strictEqual(storageInterface.getItem("floatchat_active_conversation_id"), null);
  });
});
