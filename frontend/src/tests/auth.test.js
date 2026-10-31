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

describe("Frontend Authentication Tests", () => {
  beforeEach(() => {
    localStorage.clear();
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

    // Invoke request interceptor directly
    const interceptor = api.interceptors.request.handlers[0];
    const config = await interceptor.fulfilled({ headers: {} });

    assert.strictEqual(config.headers.Authorization, "Bearer sample-bearer-jwt");
  });

  it("5. Response interceptor clears auth on 401 Unauthorized", async () => {
    saveAuth({
      token: "expired-token",
      user: { id: 3, name: "Bob", email: "bob@example.com", role: "USER" },
    });

    const respInterceptor = api.interceptors.response.handlers[0];

    try {
      await respInterceptor.rejected({
        response: { status: 401 },
        config: { url: "/api/v1/chat" },
      });
    } catch {
      // Expected rejection
    }

    assert.strictEqual(getToken(), null);
    assert.strictEqual(getUser(), null);
  });

  it("6. Response interceptor preserves auth on 429, 502, 503, 504 errors", async () => {
    const statuses = [429, 500, 502, 503, 504];

    for (const status of statuses) {
      saveAuth({
        token: "valid-token",
        user: { id: 4, name: "User", email: "user@example.com", role: "USER" },
      });

      const respInterceptor = api.interceptors.response.handlers[0];

      try {
        await respInterceptor.rejected({
          response: { status },
          config: { url: "/api/v1/chat" },
        });
      } catch {
        // Expected rejection
      }

      assert.strictEqual(
        getToken(),
        "valid-token",
        `Token should NOT be cleared for HTTP ${status}`
      );
    }
  });
});
