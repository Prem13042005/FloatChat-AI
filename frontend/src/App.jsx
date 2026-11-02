import { Routes, Route, Navigate } from "react-router-dom";
import { useAuth } from "./context/AuthContext";

import Home from "./pages/Home";
import About from "./pages/About";
import Contact from "./pages/Contact";
import Login from "./pages/Login";
import Register from "./pages/Register";
import ForgotPassword from "./pages/ForgotPassword";
import ResetPassword from "./pages/ResetPassword";
import Dashboard from "./pages/Dashboard";
import Chat from "./pages/Chat";
import Profile from "./pages/Profile";
import QueryHistory from "./pages/QueryHistory";
import Visualizations from "./pages/Visualizations";
import SystemAdministration from "./pages/SystemAdministration";
import UserManagement from "./pages/UserManagement";
import NotFound from "./pages/NotFound";

import Navbar from "./components/Navbar";
import ProtectedRoute from "./components/ProtectedRoute";
import RoleDashboard from "./pages/RoleDashboard";

function AppLayout({ children }) {
  return (
    <>
      <Navbar />
      {children}
    </>
  );
}

const ROLE_HOME = {
  USER: "/dashboard",
  ADMIN: "/dashboard/admin",
  SUPER_ADMIN: "/dashboard/super-admin",
};

export function HomeRedirect() {
  const { user, isAuthenticated, loading } = useAuth();

  if (loading) {
    return (
      <div
        className="auth-page"
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          minHeight: "50vh",
          color: "#64748b",
          fontSize: "1rem",
        }}
      >
        <div style={{ textAlign: "center" }}>
          <p>Verifying session...</p>
        </div>
      </div>
    );
  }

  if (!isAuthenticated || !user) {
    return (
      <AppLayout>
        <Home />
      </AppLayout>
    );
  }

  const role = String(user.role || "").toUpperCase();
  const destination = ROLE_HOME[role] || "/dashboard";

  return <Navigate to={destination} replace />;
}

export default function App() {
  return (
    <Routes>
      {/* Public pages */}
      <Route path="/" element={<HomeRedirect />} />

      <Route
        path="/about"
        element={<AppLayout><About /></AppLayout>}
      />

      <Route
        path="/contact"
        element={<AppLayout><Contact /></AppLayout>}
      />

      <Route path="/login" element={<Login />} />
      <Route path="/register" element={<Register />} />
      <Route path="/signup" element={<Register />} />

      <Route
        path="/forgot-password"
        element={<ForgotPassword />}
      />

      <Route
        path="/reset-password"
        element={<ResetPassword />}
      />

      {/* Common authenticated routes */}
      <Route element={<ProtectedRoute />}>
        <Route
          path="/dashboard"
          element={<AppLayout><Dashboard /></AppLayout>}
        />

        <Route
          path="/dashboard/user"
          element={<AppLayout><Dashboard /></AppLayout>}
        />

        <Route
          path="/chat"
          element={<AppLayout><Chat /></AppLayout>}
        />

        <Route
          path="/profile"
          element={<AppLayout><Profile /></AppLayout>}
        />

        <Route
          path="/query-history"
          element={<AppLayout><QueryHistory /></AppLayout>}
        />

        <Route
          path="/history"
          element={<Navigate to="/query-history" replace />}
        />

        <Route
          path="/visualizations"
          element={<AppLayout><Visualizations /></AppLayout>}
        />
      </Route>

      {/* Admin dashboard and administration pages */}
      <Route element={<ProtectedRoute allowedRoles={["ADMIN", "SUPER_ADMIN"]} />}>
        <Route
          path="/dashboard/admin"
          element={<AppLayout><RoleDashboard expectedRole="ADMIN" /></AppLayout>}
        />

        <Route
          path="/system-administration"
          element={<AppLayout><SystemAdministration /></AppLayout>}
        />

        <Route
          path="/user-management"
          element={<AppLayout><UserManagement /></AppLayout>}
        />

        <Route
          path="/admin/users"
          element={<Navigate to="/user-management" replace />}
        />
      </Route>

      {/* Super Admin dashboard */}
      <Route element={<ProtectedRoute allowedRoles={["SUPER_ADMIN"]} />}>
        <Route
          path="/dashboard/super-admin"
          element={<AppLayout><RoleDashboard expectedRole="SUPER_ADMIN" /></AppLayout>}
        />
      </Route>

      {/* Unknown URLs fallback */}
      <Route path="*" element={<AppLayout><NotFound /></AppLayout>} />
    </Routes>
  );
}
