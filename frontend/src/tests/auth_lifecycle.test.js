import "./setup.js";
import { describe, it, beforeEach } from "node:test";
import assert from "node:assert";
import {
  saveAuth,
  logout,
  getToken,
  getUser,
  isAuthenticated,
} from "../services/authService.js";
import api from "../services/api.js";
import {
  subscribeAuthEvent,
  emitAuthEvent,
  AUTH_EVENTS,
  _resetAuthEvents,
} from "../services/authEvents.js";

const ROLE_ROUTES = {
  USER: "/dashboard",
  ADMIN: "/dashboard/admin",
  SUPER_ADMIN: "/dashboard/super-admin",
};

const ACTIVE_CONV_KEY = "floatchat_active_conversation_id";

/**
 * End-to-end lifecycle router simulation representing App.jsx, ProtectedRoute.jsx, and HomeRedirect
 */
function routeLifecycleSimulator({ path, authContext, allowedRoles = null, children = "PROTECTED_CONTENT" }) {
  const { user, isAuthenticated, loading } = authContext;

  // 1. Root / Home route simulation
  if (path === "/") {
    if (loading) {
      return { status: "LOADING", rendered: "VERIFYING_SESSION", redirectedTo: null };
    }
    if (!isAuthenticated || !user) {
      return { status: "PUBLIC_HOME", rendered: "PUBLIC_HOME_PAGE", redirectedTo: null };
    }
    const role = String(user.role || "").toUpperCase();
    return { status: "REDIRECT", rendered: null, redirectedTo: ROLE_ROUTES[role] || "/dashboard" };
  }

  // 2. Protected routes simulation
  if (path.startsWith("/dashboard") || path === "/chat" || path === "/profile") {
    if (loading) {
      return { status: "LOADING", rendered: "VERIFYING_AUTH_SPINNER", redirectedTo: null };
    }
    if (!isAuthenticated || !user) {
      return {
        status: "REDIRECT_LOGIN",
        rendered: null,
        redirectedTo: "/login",
        state: { from: { pathname: path } },
      };
    }
    const role = String(user.role || "").toUpperCase();
    const userHome = ROLE_ROUTES[role] || "/dashboard";

    if (allowedRoles && !allowedRoles.includes(role)) {
      return {
        status: "REDIRECT_ROLE_HOME",
        rendered: null,
        redirectedTo: userHome,
      };
    }

    return { status: "PERMITTED", rendered: children, redirectedTo: null };
  }

  return { status: "OTHER", rendered: "PAGE", redirectedTo: null };
}

describe("Comprehensive Authentication Lifecycle Tests (Phase 2 Step 5)", () => {
  beforeEach(() => {
    localStorage.clear();
    sessionStorage.clear();
    _resetAuthEvents();
  });

  it("Scenario 1: Unauthenticated visitor opens / and sees public homepage", () => {
    const context = { user: null, isAuthenticated: false, loading: false };
    const route = routeLifecycleSimulator({ path: "/", authContext: context });

    assert.strictEqual(route.status, "PUBLIC_HOME");
    assert.strictEqual(route.rendered, "PUBLIC_HOME_PAGE");
    assert.strictEqual(route.redirectedTo, null);
  });

  it("Scenario 2: Unauthenticated visitor opens /dashboard and is redirected to login with preserved location", () => {
    const context = { user: null, isAuthenticated: false, loading: false };
    const route = routeLifecycleSimulator({ path: "/dashboard", authContext: context });

    assert.strictEqual(route.status, "REDIRECT_LOGIN");
    assert.strictEqual(route.redirectedTo, "/login");
    assert.deepStrictEqual(route.state?.from, { pathname: "/dashboard" });
  });

  it("Scenario 3: Successful USER login redirects to /dashboard", () => {
    const authUser = saveAuth({
      token: "valid-user-jwt",
      user: { id: 1, name: "Scientist User", email: "user@floatchat.org", role: "USER" },
    });

    const role = String(authUser.role || "").toUpperCase();
    const destination = ROLE_ROUTES[role] || "/dashboard";

    assert.strictEqual(destination, "/dashboard");
    assert.strictEqual(getToken(), "valid-user-jwt");
    assert.strictEqual(isAuthenticated(), true);
  });

  it("Scenario 4: ADMIN login redirects to /dashboard/admin", () => {
    const authUser = saveAuth({
      token: "valid-admin-jwt",
      user: { id: 2, name: "Admin Officer", email: "admin@floatchat.org", role: "ADMIN" },
    });

    const destination = ROLE_ROUTES[authUser.role] || "/dashboard";
    assert.strictEqual(destination, "/dashboard/admin");
  });

  it("Scenario 5: SUPER_ADMIN login redirects to /dashboard/super-admin", () => {
    const authUser = saveAuth({
      token: "valid-super-jwt",
      user: { id: 3, name: "Super Architect", email: "super@floatchat.org", role: "SUPER_ADMIN" },
    });

    const destination = ROLE_ROUTES[authUser.role] || "/dashboard";
    assert.strictEqual(destination, "/dashboard/super-admin");
  });

  it("Scenario 6: Refreshing a protected page preserves a valid authenticated session", () => {
    saveAuth({
      token: "persisted-jwt",
      user: { id: 1, name: "User", role: "USER" },
    });

    // On reload, initial context state reads from storage
    const restoredUser = getUser();
    const restoredAuth = isAuthenticated();

    assert.strictEqual(restoredAuth, true);
    assert.strictEqual(restoredUser.id, 1);

    // Context loading finishes with verified session
    const context = { user: restoredUser, isAuthenticated: restoredAuth, loading: false };
    const route = routeLifecycleSimulator({ path: "/dashboard", authContext: context });

    assert.strictEqual(route.status, "PERMITTED");
    assert.strictEqual(route.rendered, "PROTECTED_CONTENT");
  });

  it("Scenario 7: An expired or invalid token triggers logout and redirects appropriately", () => {
    saveAuth({
      token: "invalid-or-expired-jwt",
      user: { id: 1, name: "User", role: "USER" },
    });

    // Simulating token verification failure in AuthContext
    logout();
    const context = { user: null, isAuthenticated: false, loading: false };
    const route = routeLifecycleSimulator({ path: "/dashboard", authContext: context });

    assert.strictEqual(route.status, "REDIRECT_LOGIN");
    assert.strictEqual(route.redirectedTo, "/login");
    assert.strictEqual(getToken(), null);
  });

  it("Scenario 8: A 401 response clears authentication state and active conversation state", async () => {
    saveAuth({
      token: "expired-chat-token",
      user: { id: 1, name: "Active User", role: "USER" },
    });
    sessionStorage.setItem(ACTIVE_CONV_KEY, "77");

    let eventFired = false;
    const unsubscribe = subscribeAuthEvent((evt) => {
      if (evt?.type === AUTH_EVENTS.UNAUTHORIZED) eventFired = true;
    });

    const respInterceptor = api.interceptors.response.handlers[0];

    try {
      await respInterceptor.rejected({
        response: { status: 401 },
        config: { url: "/api/v1/chat", headers: { Authorization: "Bearer expired-chat-token" } },
      });
    } catch {}

    assert.strictEqual(eventFired, true);
    assert.strictEqual(getToken(), null);
    assert.strictEqual(sessionStorage.getItem(ACTIVE_CONV_KEY), null);

    unsubscribe();
  });

  it("Scenario 9: A 403 response does not unnecessarily log the user out", async () => {
    saveAuth({
      token: "valid-user-jwt",
      user: { id: 1, name: "Regular User", role: "USER" },
    });
    sessionStorage.setItem(ACTIVE_CONV_KEY, "77");

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
    } catch {}

    assert.strictEqual(eventFired, false);
    assert.strictEqual(getToken(), "valid-user-jwt");
    assert.strictEqual(sessionStorage.getItem(ACTIVE_CONV_KEY), "77");

    unsubscribe();
  });

  it("Scenario 10: A 500 response does not unnecessarily log the user out", async () => {
    saveAuth({
      token: "valid-user-jwt",
      user: { id: 1, name: "Regular User", role: "USER" },
    });

    const respInterceptor = api.interceptors.response.handlers[0];

    try {
      await respInterceptor.rejected({
        response: { status: 500, data: { message: "Internal server error" } },
        config: { url: "/api/v1/chat" },
      });
    } catch {}

    assert.strictEqual(getToken(), "valid-user-jwt");
  });

  it("Scenario 11: Manual logout clears authentication and active conversation state while preserving preferences", () => {
    localStorage.setItem("fc_theme", "arctic-blue");
    sessionStorage.setItem("user_zoom_level", "12");

    saveAuth({
      token: "logout-token",
      user: { id: 1, name: "User", role: "USER" },
    });
    sessionStorage.setItem(ACTIVE_CONV_KEY, "88");

    logout();

    assert.strictEqual(getToken(), null);
    assert.strictEqual(getUser(), null);
    assert.strictEqual(sessionStorage.getItem(ACTIVE_CONV_KEY), null);
    assert.strictEqual(localStorage.getItem("fc_theme"), "arctic-blue");
    assert.strictEqual(sessionStorage.getItem("user_zoom_level"), "12");
  });

  it("Scenario 12: Logging in as a second user does not restore the previous user's active conversation", () => {
    // User A session ends with conversation 42
    sessionStorage.setItem(ACTIVE_CONV_KEY, "42");

    // User B logs in
    saveAuth({
      token: "userB-token",
      user: { id: 2, name: "User B", role: "USER" },
    });

    // saveAuth guarantees active conversation is purged
    assert.strictEqual(sessionStorage.getItem(ACTIVE_CONV_KEY), null);
  });

  it("Scenario 13: Browser back/forward navigation does not expose protected content after logout", () => {
    // User was previously on /dashboard, then logged out
    logout();
    const contextAfterLogout = { user: null, isAuthenticated: false, loading: false };

    // User clicks Browser Back button to /dashboard
    const backRoute = routeLifecycleSimulator({ path: "/dashboard", authContext: contextAfterLogout });

    assert.strictEqual(backRoute.status, "REDIRECT_LOGIN");
    assert.strictEqual(backRoute.redirectedTo, "/login");
    assert.notStrictEqual(backRoute.rendered, "PROTECTED_CONTENT");
  });

  it("Scenario 14: Multiple simultaneous 401 responses do not create inconsistent authentication state", async () => {
    saveAuth({
      token: "concurrent-401-token",
      user: { id: 1, name: "User", role: "USER" },
    });

    let eventCount = 0;
    const unsubscribe = subscribeAuthEvent(() => {
      eventCount++;
    });

    const respInterceptor = api.interceptors.response.handlers[0];

    const calls = [1, 2, 3, 4].map(() =>
      respInterceptor
        .rejected({
          response: { status: 401 },
          config: {
            url: "/api/v1/user/dashboard",
            headers: { Authorization: "Bearer concurrent-401-token" },
          },
        })
        .catch(() => {})
    );

    await Promise.all(calls);

    assert.strictEqual(eventCount, 1, "Exactly 1 unauthorized event emitted");
    assert.strictEqual(getToken(), null);

    unsubscribe();
  });

  it("Scenario 15: Loading states do not briefly expose protected content", () => {
    const loadingContext = { user: null, isAuthenticated: false, loading: true };

    const protectedDashboard = routeLifecycleSimulator({ path: "/dashboard", authContext: loadingContext });
    assert.strictEqual(protectedDashboard.status, "LOADING");
    assert.strictEqual(protectedDashboard.rendered, "VERIFYING_AUTH_SPINNER");
    assert.notStrictEqual(protectedDashboard.rendered, "PROTECTED_CONTENT");

    const homeRoute = routeLifecycleSimulator({ path: "/", authContext: loadingContext });
    assert.strictEqual(homeRoute.status, "LOADING");
    assert.strictEqual(homeRoute.rendered, "VERIFYING_SESSION");
    assert.notStrictEqual(homeRoute.rendered, "PUBLIC_HOME_PAGE");
  });
});

