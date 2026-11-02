import { Database, MessageCircle, Waves } from "lucide-react";
import Navbar from "../components/Navbar";
import Footer from "../components/Footer";

export default function About() {
  return (
    <>
      {/* <Navbar /> */}

      <main className="public-page">
        <section className="page-hero">
          <span className="eyebrow">ABOUT FLOATCHAT</span>
          <h1>Making ocean data easier to understand</h1>
          <p>
            FloatChat is designed to connect oceanographic data exploration
            with conversational interaction and scientific visualization.
          </p>
        </section>

        <section className="about-grid">
          <article className="about-card">
            <MessageCircle size={30} />
            <h2>Our purpose</h2>
            <p>
              Provide a user-friendly way to ask questions about
              oceanographic information without requiring every user
              to work directly with complex data formats.
            </p>
          </article>

          <article className="about-card">
            <Database size={30} />
            <h2>Our approach</h2>
            <p>
              Combine a React interface, a secure Java application backend,
              persistent PostgreSQL/PostGIS records, and a replaceable AI integration.
            </p>
          </article>

          <article className="about-card">
            <Waves size={30} />
            <h2>Our direction</h2>
            <p>
              Support scientific exploration, profile comparisons,
              interactive charts, and geographic visualization when
              suitable data sources are available.
            </p>
          </article>
        </section>

        <section className="notice-panel">
          <h2>Built for extensibility</h2>
          <p>
            The application can run without the external AI service using
            clearly labeled demonstration responses. Scientific findings,
            real ARGO measurements, and real-world locations are not
            fabricated when data is unavailable.
          </p>
        </section>
      </main>

      <Footer />
    </>
  );
}