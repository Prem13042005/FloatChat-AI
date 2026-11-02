import { useState } from "react";
import { Link, NavLink, useNavigate } from "react-router-dom";
import {
  Waves,
  UserRound,
  ChevronDown,
  LogOut,
  LayoutDashboard,
  Settings,
  Menu,
  X,
} from "lucide-react";
import { useAuth } from "../context/AuthContext";
import "../styles/Navbar.css";

const ROLE_HOME = {
  USER: "/dashboard",
  ADMIN: "/dashboard/admin",
  SUPER_ADMIN: "/dashboard/super-admin",
};

export default function Navbar() {
  const { user, isAuthenticated, logout } = useAuth();
  const navigate = useNavigate();

  const [profileOpen, setProfileOpen] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);

  const isLoggedIn = Boolean(isAuthenticated && user);

  const displayName = user?.name || "FloatChat User";
  const email = user?.email || "Email not available";
  const rawRole = user?.role || "USER";
  const normalizedRole = String(rawRole).toUpperCase();
  const dashboardPath = ROLE_HOME[normalizedRole] || "/dashboard";

  const initials = displayName
    .trim()
    .split(/\s+/)
    .slice(0, 2)
    .map((part) => part[0])
    .join("")
    .toUpperCase();

  function handleLogout() {
    logout();
    setProfileOpen(false);
    setMobileOpen(false);
    navigate("/login", { replace: true });
  }

  function closeMenus() {
    setProfileOpen(false);
    setMobileOpen(false);
  }

  return (
    <header className="fc-navbar">
      <div className="fc-navbar-inner">
        {/* Brand */}
        <Link
          to="/"
          className="fc-navbar-brand"
          onClick={closeMenus}
        >
          <span className="fc-navbar-logo">
            <Waves size={25} />
          </span>

          <span className="fc-navbar-brand-text">
            <strong>FloatChat</strong>
            <small>Ocean Intelligence</small>
          </span>
        </Link>

        {/* Mobile menu button */}
        <button
          type="button"
          className="fc-mobile-menu-button"
          onClick={() => setMobileOpen((open) => !open)}
          aria-label={mobileOpen ? "Close menu" : "Open menu"}
          aria-expanded={mobileOpen}
        >
          {mobileOpen ? <X size={23} /> : <Menu size={23} />}
        </button>

        {/* Navigation */}
        <nav
          className={`fc-navbar-links ${
            mobileOpen ? "fc-navbar-links-open" : ""
          }`}
        >
          <NavLink
            to="/"
            end
            onClick={closeMenus}
            className={({ isActive }) =>
              `fc-nav-link ${isActive ? "active" : ""}`
            }
          >
            Home
          </NavLink>

          <NavLink
            to="/about"
            onClick={closeMenus}
            className={({ isActive }) =>
              `fc-nav-link ${isActive ? "active" : ""}`
            }
          >
            About
          </NavLink>

          <NavLink
            to="/contact"
            onClick={closeMenus}
            className={({ isActive }) =>
              `fc-nav-link ${isActive ? "active" : ""}`
            }
          >
            Contact
          </NavLink>

          {isLoggedIn && (
            <>
              <NavLink
                to={dashboardPath}
                onClick={closeMenus}
                className={({ isActive }) =>
                  `fc-nav-link ${isActive ? "active" : ""}`
                }
              >
                Dashboard
              </NavLink>

              <NavLink
                to="/chat"
                onClick={closeMenus}
                className={({ isActive }) =>
                  `fc-nav-link ${isActive ? "active" : ""}`
                }
              >
                AI Chat
              </NavLink>
            </>
          )}

          {/* Logged-out actions */}
          {!isLoggedIn ? (
            <div className="fc-navbar-auth">
              <Link
                to="/login"
                className="fc-login-link"
                onClick={closeMenus}
              >
                Sign In
              </Link>

              <Link
                to="/register"
                className="fc-register-link"
                onClick={closeMenus}
              >
                Create Account
              </Link>
            </div>
          ) : (
            /* Logged-in user profile */
            <div className="fc-profile-wrapper">
              <button
                type="button"
                className={`fc-profile-trigger ${
                  profileOpen ? "fc-profile-trigger-open" : ""
                }`}
                onClick={() => setProfileOpen((open) => !open)}
                aria-expanded={profileOpen}
                aria-label="Open user profile menu"
              >
                <span className="fc-profile-avatar">
                  {initials || <UserRound size={19} />}
                </span>

                <span className="fc-profile-trigger-info">
                  <strong>{displayName}</strong>
                  <small>{rawRole.replaceAll("_", " ")}</small>
                </span>

                <ChevronDown
                  size={16}
                  className={`fc-profile-chevron ${
                    profileOpen ? "rotated" : ""
                  }`}
                />
              </button>

              {profileOpen && (
                <>
                  <button
                    type="button"
                    className="fc-profile-backdrop"
                    aria-label="Close profile menu"
                    onClick={() => setProfileOpen(false)}
                  />

                  <div className="fc-profile-dropdown">
                    <div className="fc-profile-card">
                      <span className="fc-profile-avatar fc-profile-avatar-large">
                        {initials || <UserRound size={23} />}
                      </span>

                      <div className="fc-profile-user-details">
                        <strong>{displayName}</strong>
                        <span>{email}</span>
                        <span className="fc-profile-role">
                          {rawRole.replaceAll("_", " ")}
                        </span>
                      </div>
                    </div>

                    <div className="fc-profile-divider" />

                    <Link
                      to="/profile"
                      className="fc-profile-menu-item"
                      onClick={closeMenus}
                    >
                      <UserRound size={17} />
                      <span>My Profile</span>
                    </Link>

                    <Link
                      to={dashboardPath}
                      className="fc-profile-menu-item"
                      onClick={closeMenus}
                    >
                      <LayoutDashboard size={17} />
                      <span>Dashboard</span>
                    </Link>

                    {(normalizedRole === "ADMIN" || normalizedRole === "SUPER_ADMIN") && (
                      <Link
                        to="/user-management"
                        className="fc-profile-menu-item"
                        onClick={closeMenus}
                      >
                        <Settings size={17} />
                        <span>Administration</span>
                      </Link>
                    )}

                    <button
                      type="button"
                      className="fc-profile-menu-item fc-logout-button"
                      onClick={handleLogout}
                    >
                      <LogOut size={17} />
                      <span>Log Out</span>
                    </button>
                  </div>
                </>
              )}
            </div>
          )}
        </nav>
      </div>
    </header>
  );
}
