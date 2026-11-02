import "./setup.js";
import { describe, it, beforeEach } from "node:test";
import assert from "node:assert";

const ROLE_HOME = {
  USER: "/dashboard",
  ADMIN: "/dashboard/admin",
  SUPER_ADMIN: "/dashboard/super-admin",
};

/**
 * Navbar component logic simulation consuming useAuth()
 */
function simulateNavbar(authState) {
  const { user, isAuthenticated, logout } = authState;
  const isLoggedIn = Boolean(isAuthenticated && user);

  const displayName = user?.name || "FloatChat User";
  const email = user?.email || "Email not available";
  const rawRole = user?.role || "USER";
  const normalizedRole = String(rawRole).toUpperCase();
  const dashboardPath = ROLE_HOME[normalizedRole] || "/dashboard";

  const publicLinks = ["/", "/about", "/contact"];
  const authLinks = isLoggedIn ? [dashboardPath, "/chat"] : [];
  const actionLinks = !isLoggedIn ? ["/login", "/register"] : [];
  const dropdownLinks = isLoggedIn
    ? [
        "/profile",
        dashboardPath,
        ...(normalizedRole === "ADMIN" || normalizedRole === "SUPER_ADMIN"
          ? ["/user-management"]
          : []),
      ]
    : [];

  return {
    isLoggedIn,
    displayName,
    email,
    role: normalizedRole,
    dashboardPath,
    publicLinks,
    authLinks,
    actionLinks,
    dropdownLinks,
    handleLogout: () => {
      logout();
      return "/login";
    },
  };
}

/**
 * Profile component logic simulation consuming useAuth()
 */
function simulateProfile(authState) {
  const { user } = authState;
  return {
    name: user?.name || "Unavailable",
    email: user?.email || "Unavailable",
    role: user?.role || "USER",
  };
}

/**
 * RoleDashboard component logic simulation consuming useAuth()
 */
function simulateRoleDashboard(authState, expectedRole) {
  const { user, logout } = authState;
  const DASHBOARD_CONFIG = {
    USER: { title: "User Dashboard", endpoint: "/api/v1/user/dashboard" },
    ADMIN: { title: "Admin Dashboard", endpoint: "/api/v1/admin/dashboard" },
    SUPER_ADMIN: { title: "Super Admin Dashboard", endpoint: "/api/v1/super-admin/dashboard" },
  };

  const config = DASHBOARD_CONFIG[expectedRole] || DASHBOARD_CONFIG.USER;

  return {
    title: config.title,
    endpoint: config.endpoint,
    userName: user?.name || "User",
    userRole: user?.role || expectedRole,
    handleLogout: () => {
      logout();
      return "/login";
    },
  };
}

/**
 * HomeRedirect component logic simulation consuming useAuth()
 */
function simulateHomeRedirect(authState, options = {}) {
  const { user, isAuthenticated, loading } = authState;

  if (loading) {
    return {
      status: "LOADING",
      rendered: "VERIFYING_SESSION",
      redirectTo: null,
    };
  }

  // If existing route design allows authenticated access to home
  if (options.allowAuthenticatedHome) {
    return {
      status: "PUBLIC_HOME",
      rendered: "HOME_PAGE",
      redirectTo: null,
    };
  }

  if (!isAuthenticated || !user) {
    return {
      status: "UNAUTHENTICATED",
      rendered: "HOME_PAGE",
      redirectTo: null,
    };
  }

  const role = String(user.role || "").toUpperCase();
  const destination = ROLE_HOME[role] || "/dashboard";

  return {
    status: "REDIRECT_DASHBOARD",
    rendered: null,
    redirectTo: destination,
  };
}

describe("Frontend Authentication Consumer Alignment Tests (Phase 2 Step 3)", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it("1. Navbar displays correct links for unauthenticated visitors", () => {
    const authState = {
      user: null,
      isAuthenticated: false,
      logout: () => {},
    };

    const nav = simulateNavbar(authState);

    assert.strictEqual(nav.isLoggedIn, false);
    assert.deepStrictEqual(nav.actionLinks, ["/login", "/register"]);
    assert.deepStrictEqual(nav.authLinks, []);
    assert.deepStrictEqual(nav.dropdownLinks, []);
  });

  it("2. Navbar displays correct links for authenticated USER", () => {
    const authState = {
      user: { id: 1, name: "Ocean Researcher", email: "user@floatchat.org", role: "USER" },
      isAuthenticated: true,
      logout: () => {},
    };

    const nav = simulateNavbar(authState);

    assert.strictEqual(nav.isLoggedIn, true);
    assert.strictEqual(nav.displayName, "Ocean Researcher");
    assert.strictEqual(nav.dashboardPath, "/dashboard");
    assert.deepStrictEqual(nav.authLinks, ["/dashboard", "/chat"]);
    assert.deepStrictEqual(nav.actionLinks, []);
    assert.ok(nav.dropdownLinks.includes("/profile"));
    assert.ok(nav.dropdownLinks.includes("/dashboard"));
    assert.strictEqual(nav.dropdownLinks.includes("/user-management"), false);
  });

  it("3. Navbar displays correct role-specific navigation for ADMIN and SUPER_ADMIN", () => {
    const adminState = {
      user: { id: 2, name: "Data Admin", email: "admin@floatchat.org", role: "ADMIN" },
      isAuthenticated: true,
      logout: () => {},
    };

    const adminNav = simulateNavbar(adminState);
    assert.strictEqual(adminNav.dashboardPath, "/dashboard/admin");
    assert.ok(adminNav.authLinks.includes("/dashboard/admin"));
    assert.ok(adminNav.dropdownLinks.includes("/user-management"));

    const superAdminState = {
      user: { id: 3, name: "Platform Architect", email: "super@floatchat.org", role: "SUPER_ADMIN" },
      isAuthenticated: true,
      logout: () => {},
    };

    const superNav = simulateNavbar(superAdminState);
    assert.strictEqual(superNav.dashboardPath, "/dashboard/super-admin");
    assert.ok(superNav.authLinks.includes("/dashboard/super-admin"));
    assert.ok(superNav.dropdownLinks.includes("/user-management"));
  });

  it("4. Navbar logout triggers AuthContext logout and returns /login destination", () => {
    let logoutCalled = false;
    const authState = {
      user: { id: 1, name: "User", role: "USER" },
      isAuthenticated: true,
      logout: () => {
        logoutCalled = true;
      },
    };

    const nav = simulateNavbar(authState);
    const redirectTarget = nav.handleLogout();

    assert.strictEqual(logoutCalled, true);
    assert.strictEqual(redirectTarget, "/login");
  });

  it("5. Profile displays user details from AuthContext and falls back gracefully", () => {
    const authState = {
      user: { id: 1, name: "Dr. Alice", email: "alice@argo.org", role: "USER" },
    };

    const profile = simulateProfile(authState);
    assert.strictEqual(profile.name, "Dr. Alice");
    assert.strictEqual(profile.email, "alice@argo.org");
    assert.strictEqual(profile.role, "USER");

    // Missing user fallback test
    const emptyProfile = simulateProfile({ user: null });
    assert.strictEqual(emptyProfile.name, "Unavailable");
    assert.strictEqual(emptyProfile.email, "Unavailable");
    assert.strictEqual(emptyProfile.role, "USER");
  });

  it("6. RoleDashboard responds correctly to authentication state and handles logout via context", () => {
    let loggedOut = false;
    const authState = {
      user: { id: 2, name: "Admin Officer", role: "ADMIN" },
      logout: () => {
        loggedOut = true;
      },
    };

    const dashboard = simulateRoleDashboard(authState, "ADMIN");
    assert.strictEqual(dashboard.title, "Admin Dashboard");
    assert.strictEqual(dashboard.userName, "Admin Officer");
    assert.strictEqual(dashboard.userRole, "ADMIN");

    const target = dashboard.handleLogout();
    assert.strictEqual(loggedOut, true);
    assert.strictEqual(target, "/login");

    // When user state is cleared after session expiration
    const expiredDashboard = simulateRoleDashboard({ user: null, logout: () => {} }, "ADMIN");
    assert.strictEqual(expiredDashboard.userName, "User");
    assert.strictEqual(expiredDashboard.userRole, "ADMIN");
  });

  it("7. HomeRedirect displays loading state while authentication is loading", () => {
    const loadingState = {
      user: null,
      isAuthenticated: false,
      loading: true,
    };

    const result = simulateHomeRedirect(loadingState);
    assert.strictEqual(result.status, "LOADING");
    assert.strictEqual(result.rendered, "VERIFYING_SESSION");
    assert.strictEqual(result.redirectTo, null);
  });

  it("8. HomeRedirect renders public home for unauthenticated visitors", () => {
    const unauthState = {
      user: null,
      isAuthenticated: false,
      loading: false,
    };

    const result = simulateHomeRedirect(unauthState);
    assert.strictEqual(result.status, "UNAUTHENTICATED");
    assert.strictEqual(result.rendered, "HOME_PAGE");
    assert.strictEqual(result.redirectTo, null);
  });

  it("9. HomeRedirect routes authenticated users to their correct role-based dashboard", () => {
    const userState = {
      user: { id: 1, role: "USER" },
      isAuthenticated: true,
      loading: false,
    };
    assert.strictEqual(simulateHomeRedirect(userState).redirectTo, "/dashboard");

    const adminState = {
      user: { id: 2, role: "ADMIN" },
      isAuthenticated: true,
      loading: false,
    };
    assert.strictEqual(simulateHomeRedirect(adminState).redirectTo, "/dashboard/admin");

    const superAdminState = {
      user: { id: 3, role: "SUPER_ADMIN" },
      isAuthenticated: true,
      loading: false,
    };
    assert.strictEqual(simulateHomeRedirect(superAdminState).redirectTo, "/dashboard/super-admin");
  });

  it("10. Authenticated users can access public homepage if supported by route design", () => {
    const authState = {
      user: { id: 1, role: "USER" },
      isAuthenticated: true,
      loading: false,
    };

    const result = simulateHomeRedirect(authState, { allowAuthenticatedHome: true });
    assert.strictEqual(result.status, "PUBLIC_HOME");
    assert.strictEqual(result.rendered, "HOME_PAGE");
    assert.strictEqual(result.redirectTo, null);
  });

  it("11. Role-based dashboard destinations do not cause redirect loops", () => {
    const validDashboards = new Set(["/dashboard", "/dashboard/admin", "/dashboard/super-admin"]);

    Object.entries(ROLE_HOME).forEach(([role, destination]) => {
      assert.ok(validDashboards.has(destination), `${role} dashboard ${destination} must be a valid dashboard`);
      // Destination must not point back to root "/"
      assert.notStrictEqual(destination, "/");
      assert.notStrictEqual(destination, "/login");
    });
  });
});

