import { Routes, Route, Navigate } from "react-router-dom";

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

import Navbar from "./components/Navbar";
import ProtectedRoute from "./components/ProtectedRoute";
import RoleDashboard from "./pages/RoleDashboard";

function AppLayout({ children }) {
  return (
    <>
      <Navbar />
      <main>{children}</main>
    </>
  );
}

const ROLE_HOME = {
  USER: "/dashboard/user",
  ADMIN: "/dashboard/admin",
  SUPER_ADMIN: "/dashboard/super-admin",
};

function HomeRedirect() {
  const token = localStorage.getItem("floatchat_token");
  const savedUser = localStorage.getItem("floatchat_user");

  if (!token || !savedUser) {
    return <AppLayout><Home /></AppLayout>;
  }

  try {
    const user = JSON.parse(savedUser);
    return (
      <Navigate
        to={ROLE_HOME[user.role] || "/login"}
        replace
      />
    );
  } catch {
    localStorage.removeItem("floatchat_user");
    return <Navigate to="/login" replace />;
  }
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

      {/* All authenticated users */}
      <Route element={<ProtectedRoute />}>
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
          path="/visualizations"
          element={<AppLayout><Visualizations /></AppLayout>}
        />
      </Route>

      {/* User dashboard */}
      <Route element={<ProtectedRoute allowedRoles={["USER"]} />}>
        <Route
          path="/dashboard/user"
          element={<RoleDashboard expectedRole="USER" />}
        />
      </Route>

      {/* Admin dashboard and administration pages */}
      <Route element={<ProtectedRoute allowedRoles={["ADMIN", "SUPER_ADMIN"]} />}>
        <Route
          path="/dashboard/admin"
          element={<RoleDashboard expectedRole="ADMIN" />}
        />

        <Route
          path="/system-administration"
          element={<AppLayout><SystemAdministration /></AppLayout>}
        />

        <Route
          path="/user-management"
          element={<AppLayout><UserManagement /></AppLayout>}
        />
      </Route>

      {/* Super Admin dashboard */}
      <Route element={<ProtectedRoute allowedRoles={["SUPER_ADMIN"]} />}>
        <Route
          path="/dashboard/super-admin"
          element={<RoleDashboard expectedRole="SUPER_ADMIN" />}
        />
      </Route>

      {/* Keep old dashboard URL working */}
      <Route
        path="/dashboard"
        element={
          <ProtectedRoute>
            <Navigate to="/" replace />
          </ProtectedRoute>
        }
      />

      {/* Unknown URLs */}
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}