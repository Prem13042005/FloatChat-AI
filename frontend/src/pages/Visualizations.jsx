import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import DataVisualization from "../components/DataVisualization";
import { getVisualizations } from "../services/visualizationService";

export default function Visualizations() {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    getVisualizations()
      .then((result) => {
        setItems(result?.content || (Array.isArray(result) ? result : []));
        setError("");
      })
      .catch((err) => {
        setItems([]);
        setError(err?.response?.data?.message || err?.message || "Unable to load scientific visualizations.");
      })
      .finally(() => setLoading(false));
  }, []);

  return (
    <>
      {/* <Navbar /> */}

      <main className="dashboard-page">
        <span className="eyebrow">SCIENTIFIC ANALYTICS</span>
        <h1>Visualizations</h1>
        <p>Interactive oceanographic charts generated from real ARGO profile queries and measurements.</p>

        {loading ? (
          <p>Loading visualizations...</p>
        ) : error ? (
          <section className="notice-panel" style={{ borderColor: "#fca5a5", background: "#fef2f2" }}>
            <h2 style={{ color: "#991b1b" }}>Error loading visualizations</h2>
            <p style={{ color: "#7f1d1d" }}>{error}</p>
          </section>
        ) : items.length === 0 ? (
          <section className="notice-panel">
            <h2>No scientific visualizations available</h2>
            <p>
              Interactive oceanographic visualizations are dynamically generated when you query ARGO float data in the chat interface.
            </p>
            <Link to="/chat" className="btn btn-primary" style={{ display: "inline-block", marginTop: "1rem" }}>
              Ask a question in Chat →
            </Link>
          </section>
        ) : (
          <div className="visualization-grid" style={{ display: "flex", flexDirection: "column", gap: "2rem" }}>
            {items.map((item, index) => {
              const spec = item.spec || item.visualizationSpec || item;
              return (
                <article className="visualization-card" key={item.id || index}>
                  {item.question && (
                    <div style={{ marginBottom: "8px", fontSize: "0.9rem", color: "#64748b" }}>
                      Query: <strong>"{item.question}"</strong>
                    </div>
                  )}
                  <DataVisualization spec={spec} />
                </article>
              );
            })}
          </div>
        )}
      </main>
    </>
  );
}
