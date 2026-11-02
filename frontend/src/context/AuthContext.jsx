import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";

import {
  getCurrentUser,
} from "../services/api";

import {
  getToken,
  getUser,
  login as loginService,
  register as registerService,
  logout as logoutService,
} from "../services/authService";

import {
  subscribeAuthEvent,
  AUTH_EVENTS,
} from "../services/authEvents";

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(() => getUser());
  const [loading, setLoading] = useState(true);

  // Initial authentication check on application load
  useEffect(() => {
    let active = true;

    async function loadCurrentUser() {
      if (!getToken()) {
        if (active) {
          setUser(null);
          setLoading(false);
        }
        return;
      }

      try {
        const currentUser = await getCurrentUser();

        if (active) {
          localStorage.setItem(
            "floatchat_user",
            JSON.stringify(currentUser)
          );
          setUser(currentUser);
        }
      } catch {
        if (active) {
          logoutService();
          setUser(null);
        }
      } finally {
        if (active) {
          setLoading(false);
        }
      }
    }

    loadCurrentUser();

    return () => {
      active = false;
    };
  }, []);

  // Centralized authentication event listener (e.g. HTTP 401 dispatched by Axios interceptor)
  useEffect(() => {
    const unsubscribe = subscribeAuthEvent((event) => {
      if (event?.type === AUTH_EVENTS.UNAUTHORIZED) {
        logoutService();
        setUser(null);
        setLoading(false);
      }
    });

    return () => {
      unsubscribe();
    };
  }, []);

  const login = useCallback(async (email, password) => {
    const authenticatedUser = await loginService(email, password);
    setUser(authenticatedUser);
    return authenticatedUser;
  }, []);

  const register = useCallback(async (userData) => {
    const response = await registerService(userData);

    if (response?.token && response?.user) {
      setUser(response.user);
    }

    return response;
  }, []);

  const logout = useCallback(() => {
    logoutService();
    setUser(null);
  }, []);

  const value = useMemo(
    () => ({
      user,
      loading,
      isAuthenticated: Boolean(user && getToken()),
      login,
      register,
      logout,
    }),
    [user, loading, login, register, logout]
  );

  return (
    <AuthContext.Provider value={value}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const context = useContext(AuthContext);

  if (!context) {
    throw new Error("useAuth must be used inside AuthProvider");
  }

  return context;
}
