import { useState } from "react";
import Navbar from "../components/Navbar";
import { getUser } from "../services/authService";
import { changePassword } from "../services/authService";
import { getErrorMessage } from "../services/api";

export default function Profile() {
  const user = getUser();

  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function handleChangePassword(event) {
    event.preventDefault();
    setError("");
    setMessage("");

    if (newPassword.length < 8) {
      setError("New password must contain at least 8 characters.");
      return;
    }

    setLoading(true);

    try {
      const result = await changePassword(currentPassword, newPassword);
      setMessage(result.message || "Password changed successfully.");
      setCurrentPassword("");
      setNewPassword("");
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setLoading(false);
    }
  }

  return (
    <>
      {/* <Navbar /> */}

      <main className="dashboard-page">
        <span className="eyebrow">ACCOUNT SETTINGS</span>
        <h1>My Profile</h1>

        <section className="form-card profile-card">
          <h2>Account information</h2>

          <p><strong>Name:</strong> {user?.name || "Unavailable"}</p>
          <p><strong>Email:</strong> {user?.email || "Unavailable"}</p>
          <p><strong>Role:</strong> {user?.role || "USER"}</p>
        </section>

        <form
          className="form-card profile-card"
          onSubmit={handleChangePassword}
        >
          <h2>Change password</h2>

          <label>
            Current password
            <input
              type="password"
              value={currentPassword}
              onChange={(e) => setCurrentPassword(e.target.value)}
              autoComplete="current-password"
              required
            />
          </label>

          <label>
            New password
            <input
              type="password"
              value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)}
              autoComplete="new-password"
              minLength={8}
              required
            />
          </label>

          {error && <p className="error-message">{error}</p>}
          {message && <p className="success-message">{message}</p>}

          <button className="button button-primary" disabled={loading}>
            {loading ? "Updating..." : "Change Password"}
          </button>
        </form>
      </main>
    </>
  );
}