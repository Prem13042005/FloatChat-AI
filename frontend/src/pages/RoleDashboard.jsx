import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import api from "../services/api";
import { getUser, logoutUser } from "../services/authService";
import "./RoleDashboard.css";

const DASHBOARD_CONFIG = {
  USER: {
    title: "User Dashboard",
    description: "Explore FloatChat and your personal workspace.",
    endpoint: "/api/v1/user/dashboard",
    features: [
      { title: "AI Chat", description: "Ask questions about your data.", link: "/chat" },
      { title: "Query History", description: "Review your previous queries.", link: "/query-history" },
      { title: "Visualizations", description: "Explore your data visually.", link: "/visualizations" },
    ],
  },
  ADMIN: {
    title: "Admin Dashboard",
    description: "Manage platform activity and datasets.",
    endpoint: "/api/v1/admin/dashboard",
    features: [
      { title: "User Management", description: "Review and manage user accounts.", link: "/user-management" },
      { title: "System Administration", description: "Review system status and operations.", link: "/system-administration" },
      { title: "Visualizations", description: "Explore scientific data.", link: "/visualizations" },
    ],
  },
  SUPER_ADMIN: {
    title: "Super Admin Dashboard",
    description: "Oversee administrators and platform permissions.",
    endpoint: "/api/v1/super-admin/dashboard",
    features: [
      { title: "System Administration", description: "Platform oversight and system administration.", link: "/system-administration" },
      { title: "User Management", description: "Manage administrators and roles.", link: "/user-management" },
      { title: "AI Chat", description: "Scientific intelligence interface.", link: "/chat" },
    ],
  },
};

export default function RoleDashboard({ expectedRole }) {
  const user = getUser();
  const config = DASHBOARD_CONFIG[expectedRole];

  const [serverData, setServerData] = useState(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let active = true;

    api.get(config.endpoint)
      .then((response) => {
        if (active) setServerData(response.data);
      })
      .catch((err) => {
        if (active) {
          setError(
            err?.response?.status === 403
              ? "Your account is not authorized to access this dashboard."
              : "Unable to load dashboard data. Check your backend connection."
          );
        }
      })
      .finally(() => {
        if (active) setLoading(false);
      });

    return () => {
      active = false;
    };
  }, [config.endpoint]);

  function handleLogout() {
    logoutUser();
    window.location.assign("/login");
  }

  return (
    <main className="role-dashboard">
      <header className="role-dashboard-header">
        <div>
          <h1>{config.title}</h1>
          <p>{config.description}</p>
        </div>

        <button onClick={handleLogout}>Logout</button>
      </header>

      <section className="role-dashboard-welcome">
        <h2>Welcome, {user?.name || "User"}</h2>
        <p>
          Account role: <strong>{user?.role}</strong>
        </p>
      </section>

      {loading && <p>Loading dashboard...</p>}
      {error && <p className="error-message">{error}</p>}

      {!loading && !error && (
        <>
          <section className="role-dashboard-grid">
            {config.features.map((feature) => (
              <article className="role-dashboard-card" key={feature.title}>
                <h3>{feature.title}</h3>
                <p>{feature.description}</p>
                <Link to={feature.link}>Open section →</Link>
              </article>
            ))}
          </section>

          <section className="role-dashboard-status">
            <h3>Backend connection</h3>
            <p>{serverData?.title || "Dashboard API connected"}</p>
            <p>
              {serverData?.features?.join(" • ") ||
                "Dashboard data loaded successfully."}
            </p>
          </section>
        </>
      )}
    </main>
  );
}