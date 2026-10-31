import { Link } from "react-router-dom";
import { Waves, Mail } from "lucide-react";

export default function Footer() {
  return (
    <footer className="footer">
      <div className="footer-main">
        <div>
          <Link to="/" className="brand footer-brand">
            <Waves size={24} />
            Float<span className="brand-accent">Chat</span>
          </Link>
          <p>
            Making oceanographic data easier to explore,
            understand, and visualize.
          </p>
        </div>

        <div>
          <h4>Explore</h4>
          <Link to="/">Home</Link>
          <Link to="/about">About</Link>
          <Link to="/contact">Contact</Link>
        </div>

        <div>
          <h4>Account</h4>
          <Link to="/login">Sign In</Link>
          <Link to="/register">Create Account</Link>
          <Link to="/forgot-password">Forgot Password</Link>
        </div>

        <div>
          <h4>Contact</h4>
          <p><Mail size={15} /> Contact the FloatChat team</p>
          <Link to="/contact">Send a message</Link>
        </div>
      </div>

      <div className="footer-bottom">
        © {new Date().getFullYear()} FloatChat. Ocean data made accessible.
      </div>
    </footer>
  );
}