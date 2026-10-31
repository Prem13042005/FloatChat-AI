import { useState } from "react";
import { Link } from "react-router-dom";
import { Waves } from "lucide-react";
import { requestPasswordReset } from "../services/authService";
import { getErrorMessage } from "../services/api";

export default function ForgotPassword() {
  const [email, setEmail] = useState("");
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function handleSubmit(event) {
    event.preventDefault();
    setError("");
    setMessage("");
    setLoading(true);

    try {
      const result = await requestPasswordReset(email);
      setMessage(
        result.message ||
          "If an account matches that address, password reset instructions will be provided."
      );
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="auth-page">
      <Link to="/" className="brand auth-brand">
        <Waves size={27} />
        Float<span className="brand-accent">Chat</span>
      </Link>

      <section className="auth-card">
        <div className="auth-heading">
          <span className="eyebrow">ACCOUNT RECOVERY</span>
          <h1>Forgot your password?</h1>
          <p>
            Enter your email address to request password reset instructions.
          </p>
        </div>

        <form className="auth-form" onSubmit={handleSubmit}>
          <label>
            Email address
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="you@example.com"
              required
            />
          </label>

          {message && <div className="success-message">{message}</div>}
          {error && <div className="error-message">{error}</div>}

          <button
            className="button button-primary button-full"
            disabled={loading}
          >
            {loading ? "Submitting..." : "Request Reset"}
          </button>
        </form>

        <p className="auth-switch">
          Remember your password? <Link to="/login">Sign in</Link>
        </p>
      </section>
    </main>
  );
}