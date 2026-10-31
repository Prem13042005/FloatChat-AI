import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Activity, ShieldCheck, Users } from "lucide-react";
import Navbar from "../components/Navbar";
import api from "../services/api";

export default function SystemAdministration() {
  const [health, setHealth] = useState(null);
  const [aiStatus, setAiStatus] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    Promise.all([
      api.get("/health"),
      api.get("/ai/status"),
    ])
      .then(([healthResponse, aiResponse]) => {
        setHealth(healthResponse.data);
        setAiStatus(aiResponse.data);
      })
      .catch(() => {
        setError(
          "One or more system-status endpoints are unavailable."
        );
      });
  }, []);

  return (
    <>
      <Navbar />

      <main className="dashboard-page">
        <span className="eyebrow">SYSTEM CONTROL</span>
        <h1>System Administration</h1>
        <p>Monitor application health and AI integration status.</p>

        {error && <p className="error-message">{error}</p>}

        <div className="stats-grid">
          <article className="stat-card">
            <Activity size={25} />
            <h3>Application health</h3>
            <p>{health?.status || "Checking..."}</p>
          </article>

          <article className="stat-card">
            <ShieldCheck size={25} />
            <h3>AI integration</h3>
            <p>{aiStatus?.status || "Checking..."}</p>
            <p>{aiStatus?.mode || ""}</p>
          </article>

          <article className="stat-card">
            <Users size={25} />
            <h3>User accounts</h3>
            <Link to="/admin/users">Manage users →</Link>
          </article>
        </div>

        <section className="notice-panel">
          <h2>Integration status</h2>
          <p>
            The mock provider can be used during development. The
            real AI provider requires your teammate's documented API
            endpoint, request schema, response schema, and credentials.
          </p>
        </section>
      </main>
    </>
  );
}