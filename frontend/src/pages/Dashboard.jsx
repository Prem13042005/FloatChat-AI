import { useEffect, useState } from "react";
import {
  Activity,
  Database,
  FileText,
  MessageSquare,
  RefreshCw,
  Waves,
  Compass,
} from "lucide-react";
import { Link } from "react-router-dom";
import { getDashboardStats } from "../services/dashboardService";
import { getErrorMessage } from "../services/api";

export default function Dashboard() {
  const [stats, setStats] = useState(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  function loadStats() {
    setLoading(true);
    setError("");
    getDashboardStats()
      .then((data) => {
        setStats(data);
      })
      .catch((err) => {
        setError(getErrorMessage(err, "Dashboard statistics are currently unavailable."));
      })
      .finally(() => setLoading(false));
  }

  useEffect(() => {
    loadStats();
  }, []);

  const userCards = [
    {
      title: "My Conversations",
      value: stats?.totalConversations !== undefined && stats?.totalConversations !== null ? stats.totalConversations : "—",
      icon: MessageSquare,
      subtitle: "Active scientific sessions",
    },
    {
      title: "My Queries",
      value: stats?.totalQueries !== undefined && stats?.totalQueries !== null ? stats.totalQueries : "—",
      icon: Activity,
      subtitle: "Total questions submitted",
    },
    {
      title: "Queries Today",
      value: stats?.queriesToday !== undefined && stats?.queriesToday !== null ? stats.queriesToday : "—",
      icon: Database,
      subtitle: "Today's interaction count",
    },
  ];

  const scientificCards = [
    {
      title: "Active ARGO Floats",
      value: stats?.totalFloats !== undefined && stats?.totalFloats !== null ? stats.totalFloats : (stats?.scientificStats?.totalFloats ?? "—"),
      icon: Compass,
      subtitle: "Autonomous profiling floats",
    },
    {
      title: "Ocean Profiles",
      value: stats?.totalProfiles !== undefined && stats?.totalProfiles !== null ? stats.totalProfiles : (stats?.scientificStats?.totalProfiles ?? "—"),
      icon: Waves,
      subtitle: "Ascent & descent observation cycles",
    },
    {
      title: "Physical Measurements",
      value: stats?.totalMeasurements !== undefined && stats?.totalMeasurements !== null
        ? Number(stats.totalMeasurements).toLocaleString()
        : stats?.scientificStats?.totalMeasurements !== undefined && stats?.scientificStats?.totalMeasurements !== null
        ? Number(stats.scientificStats.totalMeasurements).toLocaleString()
        : "—",
      icon: Database,
      subtitle: "Temperature, salinity & pressure records",
    },
    {
      title: "Scientific Knowledge Chunks",
      value: stats?.totalDocumentChunks !== undefined && stats?.totalDocumentChunks !== null ? stats.totalDocumentChunks : (stats?.scientificStats?.totalDocumentChunks ?? "—"),
      icon: FileText,
      subtitle: stats?.embeddingDimension ? `pgvector (${stats.embeddingDimension} dims)` : "Authoritative doc passages",
    },
  ];

  return (
    <main className="dashboard-page">
      <div className="dashboard-heading">
        <div>
          <span className="eyebrow">RESEARCH WORKSPACE</span>
          <h1>Ocean Intelligence Dashboard</h1>
          <p>Real-time application activity and verified ARGO oceanographic dataset metrics.</p>
        </div>

        <div style={{ display: "flex", gap: "10px" }}>
          <button
            type="button"
            onClick={loadStats}
            disabled={loading}
            className="button button-secondary"
            style={{ display: "flex", alignItems: "center", gap: "6px" }}
            aria-label="Refresh statistics"
          >
            <RefreshCw size={16} className={loading ? "fc-spin" : ""} />
            <span>Refresh</span>
          </button>
          <Link to="/chat" className="button button-primary">
            <MessageSquare size={18} /> Open AI Chat
          </Link>
        </div>
      </div>

      {loading && (
        <div style={{ padding: "30px", textAlign: "center", color: "#64748b" }}>
          <p>Loading dashboard metrics from backend...</p>
        </div>
      )}

      {error && (
        <div className="error-message" style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "20px" }}>
          <span>{error}</span>
          <button
            type="button"
            onClick={loadStats}
            style={{ background: "transparent", border: "1px solid currentColor", borderRadius: "4px", padding: "4px 8px", cursor: "pointer", color: "inherit", fontSize: "0.85rem" }}
          >
            Retry
          </button>
        </div>
      )}

      <section style={{ marginBottom: "28px" }}>
        <h2 style={{ fontSize: "1.1rem", fontWeight: 600, color: "#334155", marginBottom: "12px" }}>
          Personal Activity
        </h2>
        <div className="stats-grid">
          {userCards.map(({ title, value, icon: Icon, subtitle }) => (
            <article className="stat-card" key={title}>
              <div className="feature-icon"><Icon size={23} /></div>
              <p>{title}</p>
              <h2>{loading ? "..." : value}</h2>
              <span style={{ fontSize: "0.78rem", color: "#64748b", marginTop: "4px" }}>{subtitle}</span>
            </article>
          ))}
        </div>
      </section>

      <section style={{ marginBottom: "28px" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "12px" }}>
          <h2 style={{ fontSize: "1.1rem", fontWeight: 600, color: "#334155", margin: 0 }}>
            ARGO Scientific Dataset
          </h2>
          <span style={{ fontSize: "0.8rem", color: "#0284c7", background: "#f0f9ff", padding: "3px 10px", borderRadius: "9999px", fontWeight: 500 }}>
            PostgreSQL / PostGIS / pgvector
          </span>
        </div>
        <div className="stats-grid">
          {scientificCards.map(({ title, value, icon: Icon, subtitle }) => (
            <article className="stat-card" key={title}>
              <div className="feature-icon"><Icon size={23} /></div>
              <p>{title}</p>
              <h2>{loading ? "..." : value}</h2>
              <span style={{ fontSize: "0.78rem", color: "#64748b", marginTop: "4px" }}>{subtitle}</span>
            </article>
          ))}
        </div>
      </section>

      <section className="quick-links">
        <Link to="/chat" className="quick-link">
          <MessageSquare size={22} />
          <div>
            <strong>Ask a scientific question</strong>
            <p>Query oceanographic data and retrieve grounded citations.</p>
          </div>
        </Link>

        <Link to="/query-history" className="quick-link">
          <Activity size={22} />
          <div>
            <strong>Query history</strong>
            <p>Review past queries and synthesized scientific findings.</p>
          </div>
        </Link>

        <Link to="/visualizations" className="quick-link">
          <Waves size={22} />
          <div>
            <strong>Data visualizations</strong>
            <p>Explore vertical depth profiles and interactive charts.</p>
          </div>
        </Link>
      </section>
    </main>
  );
}
