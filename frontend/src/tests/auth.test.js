import "./setup.js";
import { describe, it, beforeEach } from "node:test";
import assert from "node:assert";
import {
  getToken,
  getUser,
  isAuthenticated,
  saveAuth,
  logout,
} from "../services/authService.js";
import api from "../services/api.js";
import {
  subscribeAuthEvent,
  emitAuthEvent,
  AUTH_EVENTS,
  _resetAuthEvents,
} from "../services/authEvents.js";

describe("Frontend Authentication Tests (Phase 2 Step 2: Axios 401 Synchronization)", () => {
  beforeEach(() => {
    localStorage.clear();
    _resetAuthEvents();
  });

  it("1. saveAuth stores token and user in localStorage", () => {
    const mockAuthResponse = {
      token: "mock-jwt-token-12345",
      user: {
        id: 1,
        name: "Test User",
        email: "test@example.com",
        role: "USER",
      },
    };

    const savedUser = saveAuth(mockAuthResponse);
    assert.strictEqual(savedUser.name, "Test User");
    assert.strictEqual(getToken(), "mock-jwt-token-12345");
    assert.deepStrictEqual(getUser(), mockAuthResponse.user);
    assert.strictEqual(isAuthenticated(), true);
  });

  it("2. saveAuth throws an error on invalid auth response", () => {
    assert.throws(() => {
      saveAuth({});
    }, /Invalid authentication response/);

    assert.strictEqual(getToken(), null);
    assert.strictEqual(isAuthenticated(), false);
  });

  it("3. logout removes token and user from localStorage", () => {
    saveAuth({
      token: "valid-token",
      user: { id: 2, name: "Alice", email: "alice@example.com", role: "USER" },
    });
    assert.strictEqual(isAuthenticated(), true);

    logout();
    assert.strictEqual(getToken(), null);
    assert.strictEqual(getUser(), null);
    assert.strictEqual(isAuthenticated(), false);
  });

  it("4. Request interceptor attaches Bearer token when present", async () => {
    localStorage.setItem("floatchat_token", "sample-bearer-jwt");

    const interceptor = api.interceptors.request.handlers[0];
    const config = await interceptor.fulfilled({ headers: {} });

    assert.strictEqual(config.headers.Authorization, "Bearer sample-bearer-jwt");
  });

  it("5. A private API request returning 401 triggers authentication state clearance and emits UNAUTHORIZED event", async () => {
    saveAuth({
      token: "expired-private-token",
      user: { id: 3, name: "Bob", email: "bob@example.com", role: "USER" },
    });

    let eventReceived = null;
    const unsubscribe = subscribeAuthEvent((evt) => {
      eventReceived = evt;
    });

    const respInterceptor = api.interceptors.response.handlers[0];

    try {
      await respInterceptor.rejected({
        response: { status: 401 },
        config: {
          url: "/api/v1/chat",
          headers: { Authorization: "Bearer expired-private-token" },
        },
      });
    } catch {
      // Expected rejection
    }

    assert.strictEqual(getToken(), null);
    assert.strictEqual(getUser(), null);
    assert.ok(eventReceived, "Auth event should have been emitted");
    assert.strictEqual(eventReceived.type, AUTH_EVENTS.UNAUTHORIZED);
    assert.strictEqual(eventReceived.status, 401);
    assert.strictEqual(eventReceived.url, "/api/v1/chat");

    unsubscribe();
  });

  it("6. Login endpoint returning 401 does not trigger global logout or emit event", async () => {
    saveAuth({
      token: "existing-valid-token",
      user: { id: 4, name: "Charlie", email: "charlie@example.com", role: "USER" },
    });

    let eventFired = false;
    const unsubscribe = subscribeAuthEvent(() => {
      eventFired = true;
    });

    const respInterceptor = api.interceptors.response.handlers[0];

    try {
      await respInterceptor.rejected({
        response: { status: 401, data: { message: "Invalid credentials" } },
        config: { url: "/api/v1/auth/login" },
      });
    } catch {
      // Expected rejection
    }

    assert.strictEqual(getToken(), "existing-valid-token", "Login 401 must not clear token");
    assert.strictEqual(eventFired, false, "Login 401 must not dispatch unauthorized event");

    unsubscribe();
  });

  it("7. HTTP 403 does not trigger global logout", async () => {
    saveAuth({
      token: "valid-user-token",
      user: { id: 5, name: "Diana", email: "diana@example.com", role: "USER" },
    });

    let eventFired = false;
    const unsubscribe = subscribeAuthEvent(() => {
      eventFired = true;
    });

    const respInterceptor = api.interceptors.response.handlers[0];

    try {
      await respInterceptor.rejected({
        response: { status: 403, data: { message: "Forbidden" } },
        config: { url: "/api/v1/admin/dashboard" },
      });
    } catch {
      // Expected rejection
    }

    assert.strictEqual(getToken(), "valid-user-token");
    assert.strictEqual(eventFired, false);

    unsubscribe();
  });

  it("8. HTTP 429 does not trigger global logout", async () => {
    saveAuth({
      token: "rate-limited-token",
      user: { id: 6, name: "Eve", email: "eve@example.com", role: "USER" },
    });

    let eventFired = false;
    const unsubscribe = subscribeAuthEvent(() => {
      eventFired = true;
    });

    const respInterceptor = api.interceptors.response.handlers[0];

    try {
      await respInterceptor.rejected({
        response: {
          status: 429,
          headers: { "retry-after": "5" },
          data: { message: "Too many requests" },
        },
        config: { url: "/api/v1/chat" },
      });
    } catch {
      // Expected rejection
    }

    assert.strictEqual(getToken(), "rate-limited-token");
    assert.strictEqual(eventFired, false);

    unsubscribe();
  });

  it("9. HTTP 500 (and 502, 503, 504) does not trigger global logout", async () => {
    const serverStatuses = [500, 502, 503, 504];

    for (const status of serverStatuses) {
      saveAuth({
        token: `server-token-${status}`,
        user: { id: 7, name: "Frank", email: "frank@example.com", role: "USER" },
      });

      let eventFired = false;
      const unsubscribe = subscribeAuthEvent(() => {
        eventFired = true;
      });

      const respInterceptor = api.interceptors.response.handlers[0];

      try {
        await respInterceptor.rejected({
          response: { status, data: { message: `Error ${status}` } },
          config: { url: "/api/v1/chat" },
        });
      } catch {
        // Expected rejection
      }

      assert.strictEqual(
        getToken(),
        `server-token-${status}`,
        `Token must be preserved for HTTP ${status}`
      );
      assert.strictEqual(eventFired, false);

      unsubscribe();
    }
  });

  it("10. Multiple simultaneous 401 responses do not cause repeated logout events", async () => {
    saveAuth({
      token: "concurrent-token",
      user: { id: 8, name: "Grace", email: "grace@example.com", role: "USER" },
    });

    let eventCount = 0;
    const unsubscribe = subscribeAuthEvent(() => {
      eventCount++;
    });

    const respInterceptor = api.interceptors.response.handlers[0];

    // Simulate 3 concurrent API requests failing with 401 simultaneously
    const calls = [1, 2, 3].map(() =>
      respInterceptor
        .rejected({
          response: { status: 401 },
          config: {
            url: "/api/v1/user/dashboard",
            headers: { Authorization: "Bearer concurrent-token" },
          },
        })
        .catch(() => {})
    );

    await Promise.all(calls);

    assert.strictEqual(eventCount, 1, "Exactly one unauthorized event should be emitted for simultaneous 401s");
    assert.strictEqual(getToken(), null, "Token should be cleared");

    unsubscribe();
  });

  it("11. AuthContext updates its state after receiving the authentication event", () => {
    saveAuth({
      token: "active-session-token",
      user: { id: 9, name: "Hank", email: "hank@example.com", role: "USER" },
    });

    // Simulating AuthContext state and its subscription handler
    const mockContextState = {
      user: getUser(),
      isAuthenticated: isAuthenticated(),
      loading: false,
    };

    assert.strictEqual(mockContextState.isAuthenticated, true);
    assert.strictEqual(mockContextState.user?.name, "Hank");

    const unsubscribe = subscribeAuthEvent((event) => {
      if (event?.type === AUTH_EVENTS.UNAUTHORIZED) {
        logout();
        mockContextState.user = null;
        mockContextState.isAuthenticated = false;
        mockContextState.loading = false;
      }
    });

    emitAuthEvent({
      type: AUTH_EVENTS.UNAUTHORIZED,
      status: 401,
      url: "/api/v1/conversations",
    });

    assert.strictEqual(mockContextState.user, null, "User should be cleared in context state");
    assert.strictEqual(mockContextState.isAuthenticated, false, "isAuthenticated should be false");
    assert.strictEqual(mockContextState.loading, false, "loading should be false");
    assert.strictEqual(getToken(), null, "localStorage token should be cleared");

    unsubscribe();
  });

  it("12. Event listeners are properly cleaned up", () => {
    let callCount = 0;
    const unsubscribe = subscribeAuthEvent(() => {
      callCount++;
    });

    // Unsubscribe immediately
    unsubscribe();

    emitAuthEvent({
      type: AUTH_EVENTS.UNAUTHORIZED,
      status: 401,
      url: "/api/v1/test",
    });

    assert.strictEqual(callCount, 0, "Cleaned-up listener must not receive dispatched events");
  });

  it("13. Normal successful API requests remain unaffected", async () => {
    saveAuth({
      token: "steady-token",
      user: { id: 10, name: "Iris", email: "iris@example.com", role: "USER" },
    });

    let eventFired = false;
    const unsubscribe = subscribeAuthEvent(() => {
      eventFired = true;
    });

    const respInterceptor = api.interceptors.response.handlers[0];
    const mockSuccessResponse = {
      status: 200,
      data: { status: "OK", floats: 42 },
      config: { url: "/api/v1/user/dashboard" },
    };

    const result = respInterceptor.fulfilled(mockSuccessResponse);

    assert.strictEqual(result, mockSuccessResponse);
    assert.strictEqual(getToken(), "steady-token");
    assert.strictEqual(eventFired, false);

    unsubscribe();
  });

  it("14. Stale 401 response from older session does not evict a newly authenticated session", async () => {
    // Current active session in storage
    saveAuth({
      token: "newly-authenticated-token",
      user: { id: 11, name: "Jack", email: "jack@example.com", role: "USER" },
    });

    let eventFired = false;
    const unsubscribe = subscribeAuthEvent(() => {
      eventFired = true;
    });

    const respInterceptor = api.interceptors.response.handlers[0];

    // Older in-flight request arrives with previous expired token
    try {
      await respInterceptor.rejected({
        response: { status: 401 },
        config: {
          url: "/api/v1/history",
          headers: { Authorization: "Bearer stale-expired-token" },
        },
      });
    } catch {
      // Expected rejection
    }

    assert.strictEqual(
      getToken(),
      "newly-authenticated-token",
      "Current token must not be cleared by stale 401"
    );
    assert.strictEqual(
      eventFired,
      false,
      "Unauthorized event must not be emitted for stale request"
    );

    unsubscribe();
  });
});
