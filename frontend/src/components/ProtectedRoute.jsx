import { Navigate, Outlet, useLocation } from "react-router-dom";
import {
  getUser,
  isAuthenticated,
} from "../services/authService";

const ROLE_HOME = {
  USER: "/dashboard/user",
  ADMIN: "/dashboard/admin",
  SUPER_ADMIN: "/dashboard/super-admin",
};

export default function ProtectedRoute({ allowedRoles }) {
  const location = useLocation();

  if (!isAuthenticated()) {
    return (
      <Navigate
        to="/login"
        state={{ from: location }}
        replace
      />
    );
  }

  const user = getUser();

  if (!user || !ROLE_HOME[user.role]) {
    return <Navigate to="/login" replace />;
  }

  if (allowedRoles && !allowedRoles.includes(user.role)) {
    return <Navigate to={ROLE_HOME[user.role]} replace />;
  }

  return <Outlet />;
}