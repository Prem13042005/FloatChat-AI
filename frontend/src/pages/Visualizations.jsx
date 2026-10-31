import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import Navbar from "../components/Navbar";
import { getVisualizations } from "../services/visualizationService";

export default function Visualizations() {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    getVisualizations()
      .then((result) => setItems(result.content || result))
      .catch(() => setItems([]))
      .finally(() => setLoading(false));
  }, []);

  return (
    <>
      {/* <Navbar /> */}

      <main className="dashboard-page">
        <span className="eyebrow">SCIENTIFIC ANALYTICS</span>
        <h1>Visualizations</h1>
        <p>Charts will be shown when supported data is available.</p>

        {loading ? (
          <p>Loading visualizations...</p>
        ) : items.length === 0 ? (
          <section className="notice-panel">
            <h2>No scientific visualizations available</h2>
            <p>
              Scientific data will appear when the AI service and
              data source are connected. No measurements are fabricated.
            </p>
            <Link to="/chat">Ask a question →</Link>
          </section>
        ) : (
          <div className="visualization-grid">
            {items.map((item) => (
              <article className="visualization-card" key={item.id}>
                <h2>{item.title}</h2>
                {item.type === "LINE" && Array.isArray(item.data) ? (
                  <ResponsiveContainer width="100%" height={300}>
                    <LineChart data={item.data}>
                      <CartesianGrid strokeDasharray="3 3" />
                      <XAxis dataKey="x" />
                      <YAxis />
                      <Tooltip />
                      <Line
                        type="monotone"
                        dataKey="y"
                        stroke="#12b8d5"
                      />
                    </LineChart>
                  </ResponsiveContainer>
                ) : (
                  <p>This visualization type needs a supported renderer.</p>
                )}
              </article>
            ))}
          </div>
        )}
      </main>
    </>
  );
}