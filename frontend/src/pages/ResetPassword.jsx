import { useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { Waves } from "lucide-react";
import { resetPassword } from "../services/authService";
import { getErrorMessage } from "../services/api";

export default function ResetPassword() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const token = params.get("token") || "";

  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function handleSubmit(event) {
    event.preventDefault();
    setError("");

    if (!token) {
      setError("The reset link is missing its token.");
      return;
    }

    if (password.length < 8) {
      setError("Password must contain at least 8 characters.");
      return;
    }

    if (password !== confirmPassword) {
      setError("Passwords do not match.");
      return;
    }

    setLoading(true);

    try {
      await resetPassword(token, password);
      navigate("/login", {
        replace: true,
        state: { message: "Password reset successful. Please sign in." },
      });
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
          <span className="eyebrow">SECURE YOUR ACCOUNT</span>
          <h1>Reset password</h1>
          <p>Choose a new password for your FloatChat account.</p>
        </div>

        <form className="auth-form" onSubmit={handleSubmit}>
          <label>
            New password
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              minLength={8}
              autoComplete="new-password"
              required
            />
          </label>

          <label>
            Confirm new password
            <input
              type="password"
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
              autoComplete="new-password"
              required
            />
          </label>

          {error && <div className="error-message">{error}</div>}

          <button
            className="button button-primary button-full"
            disabled={loading}
          >
            {loading ? "Resetting..." : "Reset Password"}
          </button>
        </form>
      </section>
    </main>
  );
}