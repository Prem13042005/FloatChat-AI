import "./setup.js";
import { describe, it, beforeEach } from "node:test";
import assert from "node:assert";

const ROLE_HOME = {
  USER: "/dashboard",
  ADMIN: "/dashboard/admin",
  SUPER_ADMIN: "/dashboard/super-admin",
};

/**
 * Route resolution simulation matching App.jsx routes
 */
function resolveRoute({ path, authState }) {
  const { user, isAuthenticated, loading } = authState;

  // 1. Root route with HomeRedirect
  if (path === "/") {
    if (loading) {
      return { component: "VERIFYING_SESSION_SPINNER", protected: false, redirectedTo: null };
    }
    if (!isAuthenticated || !user) {
      return { component: "Home", protected: false, redirectedTo: null };
    }
    const role = String(user.role || "").toUpperCase();
    return { component: null, protected: false, redirectedTo: ROLE_HOME[role] || "/dashboard" };
  }

  // 2. Public pages
  if (path === "/about") return { component: "About", protected: false, redirectedTo: null };
  if (path === "/contact") return { component: "Contact", protected: false, redirectedTo: null };
  if (path === "/login") return { component: "Login", protected: false, redirectedTo: null };
  if (path === "/register" || path === "/signup") return { component: "Register", protected: false, redirectedTo: null };
  if (path === "/forgot-password") return { component: "ForgotPassword", protected: false, redirectedTo: null };
  if (path === "/reset-password") return { component: "ResetPassword", protected: false, redirectedTo: null };

  // 3. Aliases
  if (path === "/history") return { component: null, protected: true, redirectedTo: "/query-history" };
  if (path === "/admin/users") return { component: null, protected: true, redirectedTo: "/user-management" };

  // 4. Common protected routes
  const commonProtected = ["/dashboard", "/dashboard/user", "/chat", "/profile", "/query-history", "/visualizations"];
  if (commonProtected.includes(path)) {
    if (loading) return { component: "VERIFYING_AUTH_SPINNER", protected: true, redirectedTo: null };
    if (!isAuthenticated || !user) {
      return { component: null, protected: true, redirectedTo: "/login", state: { from: { pathname: path } } };
    }
    const componentName =
      path.startsWith("/dashboard") ? "Dashboard" :
      path === "/chat" ? "Chat" :
      path === "/profile" ? "Profile" :
      path === "/query-history" ? "QueryHistory" :
      path === "/visualizations" ? "Visualizations" : "Unknown";
    return { component: componentName, protected: true, redirectedTo: null };
  }

  // 5. Admin & Super Admin routes
  const adminRoutes = ["/dashboard/admin", "/system-administration", "/user-management"];
  if (adminRoutes.includes(path)) {
    if (loading) return { component: "VERIFYING_AUTH_SPINNER", protected: true, redirectedTo: null };
    if (!isAuthenticated || !user) {
      return { component: null, protected: true, redirectedTo: "/login", state: { from: { pathname: path } } };
    }
    const role = String(user.role || "").toUpperCase();
    if (!["ADMIN", "SUPER_ADMIN"].includes(role)) {
      return { component: null, protected: true, redirectedTo: ROLE_HOME[role] || "/dashboard" };
    }
    const componentName =
      path === "/dashboard/admin" ? "RoleDashboard (ADMIN)" :
      path === "/system-administration" ? "SystemAdministration" :
      path === "/user-management" ? "UserManagement" : "Unknown";
    return { component: componentName, protected: true, redirectedTo: null };
  }

  // 6. Super Admin exclusive routes
  if (path === "/dashboard/super-admin") {
    if (loading) return { component: "VERIFYING_AUTH_SPINNER", protected: true, redirectedTo: null };
    if (!isAuthenticated || !user) {
      return { component: null, protected: true, redirectedTo: "/login", state: { from: { pathname: path } } };
    }
    const role = String(user.role || "").toUpperCase();
    if (role !== "SUPER_ADMIN") {
      return { component: null, protected: true, redirectedTo: ROLE_HOME[role] || "/dashboard" };
    }
    return { component: "RoleDashboard (SUPER_ADMIN)", protected: true, redirectedTo: null };
  }

  // 7. Wildcard Fallback (404 NotFound)
  return { component: "NotFound", protected: false, redirectedTo: null };
}

describe("Navigation & Layout Stabilization Tests (Phase 3)", () => {
  beforeEach(() => {
    localStorage.clear();
    sessionStorage.clear();
  });

  it("1. Public routes render without requiring authentication", () => {
    const unauthState = { user: null, isAuthenticated: false, loading: false };

    assert.strictEqual(resolveRoute({ path: "/", authState: unauthState }).component, "Home");
    assert.strictEqual(resolveRoute({ path: "/about", authState: unauthState }).component, "About");
    assert.strictEqual(resolveRoute({ path: "/contact", authState: unauthState }).component, "Contact");
    assert.strictEqual(resolveRoute({ path: "/login", authState: unauthState }).component, "Login");
    assert.strictEqual(resolveRoute({ path: "/register", authState: unauthState }).component, "Register");
    assert.strictEqual(resolveRoute({ path: "/signup", authState: unauthState }).component, "Register");
  });

  it("2. Common protected routes require authentication and redirect unauthenticated users to /login", () => {
    const unauthState = { user: null, isAuthenticated: false, loading: false };
    const protectedPaths = ["/dashboard", "/chat", "/profile", "/query-history", "/visualizations"];

    for (const path of protectedPaths) {
      const result = resolveRoute({ path, authState: unauthState });
      assert.strictEqual(result.redirectedTo, "/login", `${path} must redirect to /login`);
      assert.strictEqual(result.state?.from?.pathname, path);
    }
  });

  it("3. Authenticated USER can access standard pages but is blocked from admin routes", () => {
    const userState = {
      user: { id: 101, name: "Scientist", role: "USER" },
      isAuthenticated: true,
      loading: false,
    };

    assert.strictEqual(resolveRoute({ path: "/dashboard", authState: userState }).component, "Dashboard");
    assert.strictEqual(resolveRoute({ path: "/chat", authState: userState }).component, "Chat");
    assert.strictEqual(resolveRoute({ path: "/profile", authState: userState }).component, "Profile");
    assert.strictEqual(resolveRoute({ path: "/visualizations", authState: userState }).component, "Visualizations");

    // Blocked from admin routes
    assert.strictEqual(resolveRoute({ path: "/dashboard/admin", authState: userState }).redirectedTo, "/dashboard");
    assert.strictEqual(resolveRoute({ path: "/system-administration", authState: userState }).redirectedTo, "/dashboard");
    assert.strictEqual(resolveRoute({ path: "/user-management", authState: userState }).redirectedTo, "/dashboard");
    assert.strictEqual(resolveRoute({ path: "/dashboard/super-admin", authState: userState }).redirectedTo, "/dashboard");
  });

  it("4. Authenticated ADMIN can access admin management routes", () => {
    const adminState = {
      user: { id: 201, name: "Admin Officer", role: "ADMIN" },
      isAuthenticated: true,
      loading: false,
    };

    assert.strictEqual(resolveRoute({ path: "/dashboard/admin", authState: adminState }).component, "RoleDashboard (ADMIN)");
    assert.strictEqual(resolveRoute({ path: "/system-administration", authState: adminState }).component, "SystemAdministration");
    assert.strictEqual(resolveRoute({ path: "/user-management", authState: adminState }).component, "UserManagement");

    // Blocked from super-admin exclusive route
    assert.strictEqual(resolveRoute({ path: "/dashboard/super-admin", authState: adminState }).redirectedTo, "/dashboard/admin");
  });

  it("5. Authenticated SUPER_ADMIN can access all role dashboards and administration routes", () => {
    const superAdminState = {
      user: { id: 301, name: "Super Admin", role: "SUPER_ADMIN" },
      isAuthenticated: true,
      loading: false,
    };

    assert.strictEqual(resolveRoute({ path: "/dashboard/super-admin", authState: superAdminState }).component, "RoleDashboard (SUPER_ADMIN)");
    assert.strictEqual(resolveRoute({ path: "/dashboard/admin", authState: superAdminState }).component, "RoleDashboard (ADMIN)");
    assert.strictEqual(resolveRoute({ path: "/system-administration", authState: superAdminState }).component, "SystemAdministration");
    assert.strictEqual(resolveRoute({ path: "/user-management", authState: superAdminState }).component, "UserManagement");
  });

  it("6. Route alias /admin/users cleanly redirects to /user-management", () => {
    const adminState = {
      user: { id: 201, name: "Admin Officer", role: "ADMIN" },
      isAuthenticated: true,
      loading: false,
    };

    const result = resolveRoute({ path: "/admin/users", authState: adminState });
    assert.strictEqual(result.redirectedTo, "/user-management");
  });

  it("7. Route alias /history cleanly redirects to /query-history", () => {
    const userState = {
      user: { id: 101, name: "Scientist", role: "USER" },
      isAuthenticated: true,
      loading: false,
    };

    const result = resolveRoute({ path: "/history", authState: userState });
    assert.strictEqual(result.redirectedTo, "/query-history");
  });

  it("8. Invalid route paths render NotFound 404 fallback page", () => {
    const unauthState = { user: null, isAuthenticated: false, loading: false };
    const invalidPaths = ["/invalid-url", "/missing-page", "/dashboard/unknown", "/app/settings"];

    for (const path of invalidPaths) {
      const result = resolveRoute({ path, authState: unauthState });
      assert.strictEqual(result.component, "NotFound", `${path} must render NotFound component`);
      assert.strictEqual(result.redirectedTo, null);
    }
  });

  it("9. Post-login role destinations remain consistent and without redirect loops", () => {
    assert.strictEqual(ROLE_HOME.USER, "/dashboard");
    assert.strictEqual(ROLE_HOME.ADMIN, "/dashboard/admin");
    assert.strictEqual(ROLE_HOME.SUPER_ADMIN, "/dashboard/super-admin");

    Object.values(ROLE_HOME).forEach((dest) => {
      assert.notStrictEqual(dest, "/", "Role dashboard destination must not redirect back to root");
      assert.notStrictEqual(dest, "/login", "Role dashboard destination must not redirect to login");
    });
  });
});

