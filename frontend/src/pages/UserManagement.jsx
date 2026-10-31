import { useEffect, useState } from "react";
import Navbar from "../components/Navbar";
import {
  getUsers,
  updateUserRole,
  updateUserStatus,
} from "../services/adminService";

export default function UserManagement() {
  const [users, setUsers] = useState([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  async function loadUsers() {
    setLoading(true);
    setError("");

    try {
      const result = await getUsers(0, 50);
      setUsers(result.content || []);
    } catch (err) {
      setError(
        err.response?.data?.message ||
          "Unable to load users. Check your administrator permissions."
      );
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadUsers();
  }, []);

  async function changeRole(user, role) {
    try {
      await updateUserRole(user.id, role);
      await loadUsers();
    } catch (err) {
      setError(err.response?.data?.message || "Unable to update user role.");
    }
  }

  async function toggleStatus(user) {
    try {
      await updateUserStatus(user.id, !user.enabled);
      await loadUsers();
    } catch (err) {
      setError(err.response?.data?.message || "Unable to update user status.");
    }
  }

  return (
    <>
      <Navbar />

      <main className="dashboard-page">
        <span className="eyebrow">ADMINISTRATION</span>
        <h1>User Management</h1>
        <p>Manage accounts permitted by your administrator role.</p>

        {loading && <p>Loading users...</p>}
        {error && <p className="error-message">{error}</p>}

        {!loading && users.length > 0 && (
          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Email</th>
                  <th>Role</th>
                  <th>Status</th>
                  <th>Actions</th>
                </tr>
              </thead>

              <tbody>
                {users.map((user) => (
                  <tr key={user.id}>
                    <td>{user.name}</td>
                    <td>{user.email}</td>
                    <td>
                      <select
                        value={user.role}
                        onChange={(e) => changeRole(user, e.target.value)}
                      >
                        <option value="USER">USER</option>
                        <option value="ADMIN">ADMIN</option>
                        <option value="SUPER_ADMIN">SUPER_ADMIN</option>
                      </select>
                    </td>
                    <td>{user.enabled ? "Active" : "Disabled"}</td>
                    <td>
                      <button
                        className="button button-outline"
                        onClick={() => toggleStatus(user)}
                      >
                        {user.enabled ? "Disable" : "Enable"}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </main>
    </>
  );
}