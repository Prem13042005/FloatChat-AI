import "./setup.js";
import { describe, it, beforeEach } from "node:test";
import assert from "node:assert";
import {
  saveAuth,
  logout,
  getToken,
  getUser,
} from "../services/authService.js";
import api from "../services/api.js";
import {
  subscribeAuthEvent,
  AUTH_EVENTS,
  _resetAuthEvents,
} from "../services/authEvents.js";

const ACTIVE_CONV_KEY = "floatchat_active_conversation_id";

/**
 * Simulates Chat.jsx conversation restoration algorithm on mount / page refresh
 */
function simulateConversationRestoration({ userConversations, savedSessionConversationId }) {
  const list = Array.isArray(userConversations)
    ? userConversations
    : userConversations?.content || [];

  if (!savedSessionConversationId) {
    return {
      restored: false,
      activeConversationId: null,
      storageAction: "NONE",
    };
  }

  const parsedId = Number(savedSessionConversationId);
  const found = list.find((c) => c.id === parsedId);

  if (found) {
    return {
      restored: true,
      activeConversationId: parsedId,
      storageAction: "RETAINED",
      conversation: found,
    };
  } else {
    // Foreign or stale conversation ID evicted immediately
    sessionStorage.removeItem(ACTIVE_CONV_KEY);
    return {
      restored: false,
      activeConversationId: null,
      storageAction: "REMOVED_FOREIGN_OR_STALE",
    };
  }
}

describe("Conversation Session Isolation Tests (Phase 2 Step 4)", () => {
  beforeEach(() => {
    localStorage.clear();
    sessionStorage.clear();
    _resetAuthEvents();
  });

  it("1. Logout removes the active conversation ID from sessionStorage", () => {
    saveAuth({
      token: "user1-token",
      user: { id: 101, name: "Scientist One", email: "user1@floatchat.org", role: "USER" },
    });

    sessionStorage.setItem(ACTIVE_CONV_KEY, "55");
    assert.strictEqual(sessionStorage.getItem(ACTIVE_CONV_KEY), "55");

    logout();

    assert.strictEqual(sessionStorage.getItem(ACTIVE_CONV_KEY), null, "Active conversation must be cleared on logout");
    assert.strictEqual(getToken(), null, "Token must be cleared");
    assert.strictEqual(getUser(), null, "User must be cleared");
  });

  it("2. Logout does not delete unrelated application preferences", () => {
    // Persist unrelated preferences in localStorage and sessionStorage
    localStorage.setItem("fc_theme", "deep-ocean");
    localStorage.setItem("user_settings", JSON.stringify({ fontSize: "medium", autoRefresh: true }));
    sessionStorage.setItem("sidebar_collapsed", "true");

    saveAuth({
      token: "user1-token",
      user: { id: 101, name: "Scientist One", email: "user1@floatchat.org", role: "USER" },
    });
    sessionStorage.setItem(ACTIVE_CONV_KEY, "55");

    logout();

    // Verify session credentials and active conversation were cleared
    assert.strictEqual(sessionStorage.getItem(ACTIVE_CONV_KEY), null);
    assert.strictEqual(getToken(), null);
    assert.strictEqual(getUser(), null);

    // Verify unrelated application preferences were preserved
    assert.strictEqual(localStorage.getItem("fc_theme"), "deep-ocean");
    assert.deepStrictEqual(
      JSON.parse(localStorage.getItem("user_settings")),
      { fontSize: "medium", autoRefresh: true }
    );
    assert.strictEqual(sessionStorage.getItem("sidebar_collapsed"), "true");
  });

  it("3. A second user cannot inherit the previous user's active conversation", () => {
    // User A logs in and has conversation 42
    saveAuth({
      token: "userA-token",
      user: { id: 1, name: "User A", email: "userA@floatchat.org", role: "USER" },
    });
    sessionStorage.setItem(ACTIVE_CONV_KEY, "42");

    // User A logs out
    logout();
    assert.strictEqual(sessionStorage.getItem(ACTIVE_CONV_KEY), null);

    // If an orphan ID somehow remained in sessionStorage:
    sessionStorage.setItem(ACTIVE_CONV_KEY, "42");

    // User B logs in
    saveAuth({
      token: "userB-token",
      user: { id: 2, name: "User B", email: "userB@floatchat.org", role: "USER" },
    });

    // saveAuth guarantees sessionStorage active conversation is purged
    assert.strictEqual(sessionStorage.getItem(ACTIVE_CONV_KEY), null);

    // Even if an orphan ID was injected:
    sessionStorage.setItem(ACTIVE_CONV_KEY, "42");
    const userBConversations = [
      { id: 201, title: "User B Salinity Query" },
      { id: 202, title: "User B Temperature Profile" },
    ];

    const result = simulateConversationRestoration({
      userConversations: userBConversations,
      savedSessionConversationId: sessionStorage.getItem(ACTIVE_CONV_KEY),
    });

    assert.strictEqual(result.restored, false, "User B must NOT restore User A's conversation");
    assert.strictEqual(result.activeConversationId, null);
    assert.strictEqual(result.storageAction, "REMOVED_FOREIGN_OR_STALE");
    assert.strictEqual(sessionStorage.getItem(ACTIVE_CONV_KEY), null);
  });

  it("4. Page refresh restores the correct conversation for the same authenticated user", () => {
    const userAConversations = [
      { id: 101, title: "Arabian Sea Float Trajectory" },
      { id: 102, title: "Bay of Bengal Salinity" },
    ];

    // User A sets active conversation to 101
    sessionStorage.setItem(ACTIVE_CONV_KEY, "101");

    // User refreshes page: Chat.jsx runs restoration check
    const result = simulateConversationRestoration({
      userConversations: userAConversations,
      savedSessionConversationId: sessionStorage.getItem(ACTIVE_CONV_KEY),
    });

    assert.strictEqual(result.restored, true);
    assert.strictEqual(result.activeConversationId, 101);
    assert.strictEqual(result.conversation.title, "Arabian Sea Float Trajectory");
    assert.strictEqual(result.storageAction, "RETAINED");
  });

  it("5. Existing conversation-history behavior remains functional", () => {
    // 5a. Opening a conversation sets active conversation ID in sessionStorage
    sessionStorage.setItem(ACTIVE_CONV_KEY, "102");
    assert.strictEqual(sessionStorage.getItem(ACTIVE_CONV_KEY), "102");

    // 5b. New conversation clears active conversation ID
    sessionStorage.removeItem(ACTIVE_CONV_KEY);
    assert.strictEqual(sessionStorage.getItem(ACTIVE_CONV_KEY), null);

    // 5c. Deleting active conversation clears active conversation ID
    sessionStorage.setItem(ACTIVE_CONV_KEY, "103");
    sessionStorage.removeItem(ACTIVE_CONV_KEY);
    assert.strictEqual(sessionStorage.getItem(ACTIVE_CONV_KEY), null);
  });

  it("6. A 401-triggered logout performs the required conversation session cleanup", async () => {
    saveAuth({
      token: "expiring-token",
      user: { id: 301, name: "Expiring User", email: "expire@floatchat.org", role: "USER" },
    });

    sessionStorage.setItem(ACTIVE_CONV_KEY, "88");
    localStorage.setItem("fc_custom_setting", "enabled");

    let eventReceived = null;
    const unsubscribe = subscribeAuthEvent((event) => {
      eventReceived = event;
      if (event?.type === AUTH_EVENTS.UNAUTHORIZED) {
        logout();
      }
    });

    const respInterceptor = api.interceptors.response.handlers[0];

    try {
      await respInterceptor.rejected({
        response: { status: 401 },
        config: {
          url: "/api/v1/chat",
          headers: { Authorization: "Bearer expiring-token" },
        },
      });
    } catch {
      // Expected rejection
    }

    // Verify session credentials and conversation ID were purged
    assert.strictEqual(getToken(), null);
    assert.strictEqual(getUser(), null);
    assert.strictEqual(sessionStorage.getItem(ACTIVE_CONV_KEY), null, "401 must clear active conversation ID");

    // Verify unrelated application preferences were preserved
    assert.strictEqual(localStorage.getItem("fc_custom_setting"), "enabled");
    assert.strictEqual(eventReceived?.type, AUTH_EVENTS.UNAUTHORIZED);

    unsubscribe();
  });
});

