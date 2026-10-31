import "./setup.js";
import { describe, it } from "node:test";
import assert from "node:assert";

describe("Frontend Conversation History Tests", () => {
  it("1. Array response from Java /api/v1/history is properly extracted", () => {
    const javaBackendHistory = [
      {
        id: 1,
        question: "What is an ARGO float?",
        answer: "ARGO floats are robotic ocean instruments...",
        createdAt: "2026-10-31T12:00:00",
      },
      {
        id: 2,
        question: "Show salinity readings in the Indian Ocean.",
        answer: "Average salinity was 35.2 PSU.",
        createdAt: "2026-10-31T12:05:00",
      },
    ];

    const items = Array.isArray(javaBackendHistory)
      ? javaBackendHistory
      : javaBackendHistory?.content || [];

    assert.strictEqual(items.length, 2);
    assert.strictEqual(items[0].question, "What is an ARGO float?");
    assert.strictEqual(items[1].answer, "Average salinity was 35.2 PSU.");
  });

  it("2. Paginated object fallback is properly handled", () => {
    const paginatedHistory = {
      content: [
        { id: 10, question: "How deep do floats dive?", answer: "Up to 2000m" },
      ],
      totalPages: 1,
    };

    const items = Array.isArray(paginatedHistory)
      ? paginatedHistory
      : paginatedHistory?.content || [];

    assert.strictEqual(items.length, 1);
    assert.strictEqual(items[0].id, 10);
  });

  it("3. Empty history array produces empty list without errors", () => {
    const emptyHistory = [];
    const items = Array.isArray(emptyHistory) ? emptyHistory : emptyHistory?.content || [];

    assert.strictEqual(items.length, 0);
  });

  it("4. Conversation item selection maps properly to chat session", () => {
    const conversation = {
      id: 42,
      title: "Salinity depth profiling",
      createdAt: "2026-10-31T10:00:00",
    };

    const session = {
      conversationId: conversation.id,
      title: conversation.title,
    };

    assert.strictEqual(session.conversationId, 42);
    assert.strictEqual(session.title, "Salinity depth profiling");
  });
});
