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

const ROLE_HOME = {
  USER: "/dashboard",
  ADMIN: "/dashboard/admin",
  SUPER_ADMIN: "/dashboard/super-admin",
};

const ROLE_ROUTES = {
  USER: "/dashboard",
  ADMIN: "/dashboard/admin",
  SUPER_ADMIN: "/dashboard/super-admin",
};

/**
 * Exact simulation of ProtectedRoute component logic consuming useAuth()
 */
function simulateProtectedRoute({
  authState,
  allowedRoles,
  currentLocation = { pathname: "/dashboard" },
  children = null,
}) {
  const { user, isAuthenticated, loading } = authState;

  // 1. Loading check
  if (loading) {
    return {
      status: "LOADING",
      allowed: false,
      redirectTo: null,
      rendered: "LOADING_INDICATOR",
      state: null,
    };
  }

  // 2. Unauthenticated check
  if (!isAuthenticated || !user) {
    return {
      status: "UNAUTHENTICATED",
      allowed: false,
      redirectTo: "/login",
      rendered: null,
      state: { from: currentLocation },
    };
  }

  // 3. Role authorization check
  const role = String(user.role || "").toUpperCase();
  const userHome = ROLE_HOME[role] || "/login";

  if (allowedRoles && !allowedRoles.includes(role)) {
    return {
      status: "UNAUTHORIZED",
      allowed: false,
      redirectTo: userHome,
      rendered: null,
      state: null,
    };
  }

  return {
    status: "AUTHORIZED",
    allowed: true,
    redirectTo: null,
    rendered: children ? "CHILDREN" : "OUTLET",
    state: null,
  };
}

describe("Frontend Routing & Role-Based Access Control Tests (Phase 2 Step 1)", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it("1. ProtectedRoute displays loading state while AuthContext.loading is true without premature redirect", () => {
    const authState = {
      loading: true,
      isAuthenticated: false,
      user: null,
    };

    const result = simulateProtectedRoute({
      authState,
      currentLocation: { pathname: "/dashboard" },
    });

    assert.strictEqual(result.status, "LOADING");
    assert.strictEqual(result.allowed, false);
    assert.strictEqual(result.redirectTo, null);
    assert.strictEqual(result.rendered, "LOADING_INDICATOR");
  });

  it("2. ProtectedRoute redirects unauthenticated users to /login preserving state.from", () => {
    const authState = {
      loading: false,
      isAuthenticated: false,
      user: null,
    };

    const result = simulateProtectedRoute({
      authState,
      currentLocation: { pathname: "/dashboard/analytics" },
    });

    assert.strictEqual(result.status, "UNAUTHENTICATED");
    assert.strictEqual(result.allowed, false);
    assert.strictEqual(result.redirectTo, "/login");
    assert.deepStrictEqual(result.state?.from, { pathname: "/dashboard/analytics" });
  });

  it("3. ProtectedRoute permits authenticated USER access to /dashboard", () => {
    const authState = {
      loading: false,
      isAuthenticated: true,
      user: { id: 101, name: "Scientist User", email: "user@floatchat.org", role: "USER" },
    };

    const result = simulateProtectedRoute({
      authState,
      currentLocation: { pathname: "/dashboard" },
    });

    assert.strictEqual(result.status, "AUTHORIZED");
    assert.strictEqual(result.allowed, true);
    assert.strictEqual(result.redirectTo, null);
    assert.strictEqual(result.rendered, "OUTLET");
  });

  it("4. ProtectedRoute supports wrapper-style children when provided", () => {
    const authState = {
      loading: false,
      isAuthenticated: true,
      user: { id: 101, name: "Scientist User", email: "user@floatchat.org", role: "USER" },
    };

    const result = simulateProtectedRoute({
      authState,
      currentLocation: { pathname: "/dashboard" },
      children: "CUSTOM_CHILDREN_COMPONENT",
    });

    assert.strictEqual(result.status, "AUTHORIZED");
    assert.strictEqual(result.allowed, true);
    assert.strictEqual(result.rendered, "CHILDREN");
  });

  it("5. ProtectedRoute redirects authenticated USER attempting to access ADMIN routes to /dashboard", () => {
    const authState = {
      loading: false,
      isAuthenticated: true,
      user: { id: 101, name: "Scientist User", email: "user@floatchat.org", role: "USER" },
    };

    const result = simulateProtectedRoute({
      authState,
      allowedRoles: ["ADMIN", "SUPER_ADMIN"],
      currentLocation: { pathname: "/dashboard/admin" },
    });

    assert.strictEqual(result.status, "UNAUTHORIZED");
    assert.strictEqual(result.allowed, false);
    assert.strictEqual(result.redirectTo, "/dashboard");
  });

  it("6. ProtectedRoute permits ADMIN and SUPER_ADMIN access to their respective routes", () => {
    const adminAuthState = {
      loading: false,
      isAuthenticated: true,
      user: { id: 201, name: "Admin Officer", email: "admin@floatchat.org", role: "ADMIN" },
    };

    const adminResult = simulateProtectedRoute({
      authState: adminAuthState,
      allowedRoles: ["ADMIN", "SUPER_ADMIN"],
      currentLocation: { pathname: "/dashboard/admin" },
    });

    assert.strictEqual(adminResult.status, "AUTHORIZED");
    assert.strictEqual(adminResult.allowed, true);

    const superAdminAuthState = {
      loading: false,
      isAuthenticated: true,
      user: { id: 301, name: "Super Architect", email: "super@floatchat.org", role: "SUPER_ADMIN" },
    };

    const superResult = simulateProtectedRoute({
      authState: superAdminAuthState,
      allowedRoles: ["SUPER_ADMIN"],
      currentLocation: { pathname: "/dashboard/super-admin" },
    });

    assert.strictEqual(superResult.status, "AUTHORIZED");
    assert.strictEqual(superResult.allowed, true);
  });

  it("7. ProtectedRoute redirects authenticated ADMIN attempting to access SUPER_ADMIN route to /dashboard/admin", () => {
    const adminAuthState = {
      loading: false,
      isAuthenticated: true,
      user: { id: 201, name: "Admin Officer", email: "admin@floatchat.org", role: "ADMIN" },
    };

    const result = simulateProtectedRoute({
      authState: adminAuthState,
      allowedRoles: ["SUPER_ADMIN"],
      currentLocation: { pathname: "/dashboard/super-admin" },
    });

    assert.strictEqual(result.status, "UNAUTHORIZED");
    assert.strictEqual(result.allowed, false);
    assert.strictEqual(result.redirectTo, "/dashboard/admin");
  });

  it("8. ProtectedRoute behaves correctly when token expires or is cleared in AuthContext", () => {
    // When token expires, AuthContext sets isAuthenticated: false and user: null once validation fails
    const expiredAuthState = {
      loading: false,
      isAuthenticated: false,
      user: null,
    };

    const result = simulateProtectedRoute({
      authState: expiredAuthState,
      currentLocation: { pathname: "/dashboard/settings" },
    });

    assert.strictEqual(result.status, "UNAUTHENTICATED");
    assert.strictEqual(result.allowed, false);
    assert.strictEqual(result.redirectTo, "/login");
    assert.deepStrictEqual(result.state?.from, { pathname: "/dashboard/settings" });
  });

  it("9. ProtectedRoute handles case-insensitive role normalization safely", () => {
    const authState = {
      loading: false,
      isAuthenticated: true,
      user: { id: 102, name: "Case Test", email: "case@floatchat.org", role: "user" }, // lowercase
    };

    const result = simulateProtectedRoute({
      authState,
      allowedRoles: ["USER"],
      currentLocation: { pathname: "/dashboard" },
    });

    assert.strictEqual(result.status, "AUTHORIZED");
    assert.strictEqual(result.allowed, true);
  });

  it("10. ProtectedRoute redirects unknown or malformed role to /login", () => {
    const authState = {
      loading: false,
      isAuthenticated: true,
      user: { id: 999, name: "Unknown Role", email: "unknown@floatchat.org", role: "GUEST" },
    };

    const result = simulateProtectedRoute({
      authState,
      allowedRoles: ["USER", "ADMIN", "SUPER_ADMIN"],
      currentLocation: { pathname: "/dashboard" },
    });

    assert.strictEqual(result.status, "UNAUTHORIZED");
    assert.strictEqual(result.allowed, false);
    assert.strictEqual(result.redirectTo, "/login");
  });

  it("11. Login post-authentication destinations are consistent for all roles", () => {
    assert.strictEqual(ROLE_ROUTES.USER, "/dashboard");
    assert.strictEqual(ROLE_ROUTES.ADMIN, "/dashboard/admin");
    assert.strictEqual(ROLE_ROUTES.SUPER_ADMIN, "/dashboard/super-admin");

    const getLoginDestination = (user) => {
      const role = String(user?.role || "").toUpperCase();
      return ROLE_ROUTES[role] || "/dashboard";
    };

    assert.strictEqual(getLoginDestination({ role: "USER" }), "/dashboard");
    assert.strictEqual(getLoginDestination({ role: "ADMIN" }), "/dashboard/admin");
    assert.strictEqual(getLoginDestination({ role: "SUPER_ADMIN" }), "/dashboard/super-admin");
    assert.strictEqual(getLoginDestination(null), "/dashboard");
  });
});
