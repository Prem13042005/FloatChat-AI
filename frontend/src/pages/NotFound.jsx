import { Link } from "react-router-dom";
import { Waves, ArrowLeft } from "lucide-react";

export default function NotFound() {
  return (
    <main className="dashboard-page" style={{ textAlign: "center", padding: "80px 20px" }}>
      <div
        style={{
          display: "inline-flex",
          padding: "16px",
          background: "#f0f9ff",
          borderRadius: "50%",
          color: "#0284c7",
          marginBottom: "16px",
        }}
      >
        <Waves size={40} />
      </div>

      <span className="eyebrow" style={{ display: "block" }}>PAGE NOT FOUND</span>
      <h1 style={{ fontSize: "2.2rem", margin: "10px 0 16px" }}>404 — Page Unavailable</h1>
      <p
        style={{
          color: "#64748b",
          maxWidth: "480px",
          margin: "0 auto 28px",
          fontSize: "1rem",
          lineHeight: "1.6",
        }}
      >
        The page you are looking for does not exist, has been moved, or is temporarily unavailable.
      </p>

      <Link
        to="/"
        className="button button-primary"
        style={{ display: "inline-flex", alignItems: "center", gap: "8px" }}
      >
        <ArrowLeft size={16} /> Return to Home
      </Link>
    </main>
  );
}

