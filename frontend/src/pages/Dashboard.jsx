import { useEffect, useState } from "react";
import {
  Activity,
  Database,
  MessageSquare,
  Waves,
} from "lucide-react";
import { Link } from "react-router-dom";
import Navbar from "../components/Navbar";
import { getDashboardStats } from "../services/dashboardService";

export default function Dashboard() {
  const [stats, setStats] = useState(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    getDashboardStats()
      .then(setStats)
      .catch(() => {
        setError("Dashboard statistics are currently unavailable.");
      })
      .finally(() => setLoading(false));
  }, []);

  const cards = [
    {
      title: "My Conversations",
      value: stats?.totalConversations ?? "—",
      icon: MessageSquare,
    },
    {
      title: "My Queries",
      value: stats?.totalQueries ?? "—",
      icon: Activity,
    },
    {
      title: "Queries Today",
      value: stats?.queriesToday ?? "—",
      icon: Database,
    },
  ];

  return (
    <>
      {/* <Navbar /> */}

      <main className="dashboard-page">
        <div className="dashboard-heading">
          <div>
            <span className="eyebrow">PERSONAL WORKSPACE</span>
            <h1>Your Dashboard</h1>
            <p>Explore your conversations and application activity.</p>
          </div>

          <Link to="/chat" className="button button-primary">
            <MessageSquare size={18} /> Open AI Chat
          </Link>
        </div>

        {loading && <p>Loading dashboard...</p>}
        {error && <p className="error-message">{error}</p>}

        <div className="stats-grid">
          {cards.map(({ title, value, icon: Icon }) => (
            <article className="stat-card" key={title}>
              <div className="feature-icon"><Icon size={23} /></div>
              <p>{title}</p>
              <h2>{loading ? "..." : value}</h2>
            </article>
          ))}
        </div>

        <section className="notice-panel">
          <Waves size={27} />
          <h2>Scientific Data Explorer</h2>
          <p>
            Scientific data will appear when the AI service and its
            data source are connected. Application statistics above
            are separate from scientific dataset statistics.
          </p>
          <Link to="/visualizations">Open visualizations →</Link>
        </section>

        <section className="quick-links">
          <Link to="/chat" className="quick-link">
            <MessageSquare size={22} />
            <div>
              <strong>Ask a question</strong>
              <p>Open the chat workspace.</p>
            </div>
          </Link>

          <Link to="/history" className="quick-link">
            <Activity size={22} />
            <div>
              <strong>Query history</strong>
              <p>Review your previous queries.</p>
            </div>
          </Link>
        </section>
      </main>
    </>
  );
}