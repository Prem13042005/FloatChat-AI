import { Link } from "react-router-dom";
import {
  ArrowRight,
  Bot,
  ChartNoAxesCombined,
  Database,
  Globe2,
  Waves,
} from "lucide-react";
import Navbar from "../components/Navbar";
import Footer from "../components/Footer";

const features = [
  {
    icon: Bot,
    title: "Natural Language Queries",
    text: "Explore oceanographic data using questions written in everyday language.",
  },
  {
    icon: ChartNoAxesCombined,
    title: "Scientific Visualizations",
    text: "Present supported scientific results using charts and graphs.",
  },
  {
    icon: Database,
    title: "Ocean Data Exploration",
    text: "Build a convenient interface for exploring available ocean datasets.",
  },
  {
    icon: Globe2,
    title: "ARGO Float Exploration",
    text: "Prepare to explore float locations and profiles when real data is connected.",
  },
];

const examples = [
  "How does ocean temperature change with depth?",
  "Compare temperature and salinity profiles.",
  "Show available oceanographic observations.",
];

export default function Home() {
  return (
    <>
      {/* <Navbar /> */}

      <main>
        <section className="hero">
          <div className="hero-content">
            <span className="eyebrow">
              <Waves size={16} /> OCEANOGRAPHIC DATA, SIMPLIFIED
            </span>

            <h1>
              Explore the ocean.
              <br />
              <span>Understand the data.</span>
            </h1>

            <p className="hero-description">
              FloatChat is a platform designed to make oceanographic
              information easier to explore through natural-language
              interaction, scientific visualizations, and data analytics.
            </p>

            <div className="hero-actions">
              <Link to="/register" className="button button-primary">
                Get Started <ArrowRight size={18} />
              </Link>
              <Link to="/about" className="button button-outline">
                Discover FloatChat
              </Link>
            </div>

            <p className="hero-note">
              Your workspace for ocean data exploration.
            </p>
          </div>

          <div className="hero-visual">
            <div className="ocean-orb">
              <div className="orb-ring ring-one" />
              <div className="orb-ring ring-two" />
              <Waves size={100} strokeWidth={1.1} />
            </div>

            <div className="floating-card card-top">
              <span className="status-dot" />
              Data exploration workspace
            </div>

            <div className="floating-card card-bottom">
              <ChartNoAxesCombined size={21} />
              <div>
                <strong>Visual analytics</strong>
                <small>Charts and scientific profiles</small>
              </div>
            </div>
          </div>
        </section>

        <section className="trust-strip">
          <span>DISCOVER</span>
          <span>ANALYZE</span>
          <span>VISUALIZE</span>
          <span>UNDERSTAND</span>
        </section>

        <section className="section" id="features">
          <div className="section-heading">
            <span className="eyebrow">PLATFORM FEATURES</span>
            <h2>Everything begins with a question</h2>
            <p>
              A unified interface for interacting with oceanographic
              information and presenting available results.
            </p>
          </div>

          <div className="feature-grid">
            {features.map(({ icon: Icon, title, text }) => (
              <article className="feature-card" key={title}>
                <div className="feature-icon"><Icon size={25} /></div>
                <h3>{title}</h3>
                <p>{text}</p>
              </article>
            ))}
          </div>
        </section>

        <section className="example-section">
          <div>
            <span className="eyebrow">START WITH A QUESTION</span>
            <h2>What would you like to discover?</h2>
            <p>
              These are example questions for the future AI-enabled
              workspace. Actual scientific answers require a connected
              data source.
            </p>
            <Link to="/register" className="button button-primary">
              Explore FloatChat <ArrowRight size={18} />
            </Link>
          </div>

          <div className="example-list">
            {examples.map((example) => (
              <div className="example-item" key={example}>
                <Waves size={19} />
                <span>{example}</span>
                <ArrowRight size={17} />
              </div>
            ))}
          </div>
        </section>

        <section className="cta-section">
          <span className="eyebrow">YOUR OCEAN DATA WORKSPACE</span>
          <h2>Ready to explore FloatChat?</h2>
          <p>Create an account to access your personal workspace.</p>
          <Link to="/register" className="button button-light">
            Create Your Account <ArrowRight size={18} />
          </Link>
        </section>
      </main>

      <Footer />
    </>
  );
}