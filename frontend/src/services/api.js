import axios from "axios";
import { emitAuthEvent, AUTH_EVENTS } from "./authEvents.js";

const api = axios.create({
  baseURL: import.meta?.env?.VITE_API_BASE_URL || "",
  headers: {
    "Content-Type": "application/json",
  },
  timeout: 30000,
});

// Attach JWT token to authenticated requests.
api.interceptors.request.use(
  (config) => {
    const token = localStorage.getItem("floatchat_token");

    if (token) {
      config.headers = config.headers || {};
      config.headers.Authorization = `Bearer ${token}`;
    }

    return config;
  },
  (error) => Promise.reject(error)
);

// Response interceptor: only clear auth on genuine 401 Unauthorized from protected endpoints
api.interceptors.response.use(
  (response) => response,
  (error) => {
    const status = error?.response?.status;
    const url = error?.config?.url || "";
    const isLoginRequest = url.includes("/auth/login");

    // Only handle genuine 401 Unauthorized from protected endpoints (exclude login failures)
    if (status === 401 && !isLoginRequest) {
      let requestAuthHeader = null;
      if (error?.config?.headers) {
        if (typeof error.config.headers.get === "function") {
          requestAuthHeader = error.config.headers.get("Authorization");
        }
        if (!requestAuthHeader) {
          requestAuthHeader =
            error.config.headers.Authorization ||
            error.config.headers.authorization;
        }
      }

      let requestToken = null;
      if (typeof requestAuthHeader === "string") {
        requestToken = requestAuthHeader.replace(/^Bearer\s+/i, "").trim();
      }

      const currentToken = localStorage.getItem("floatchat_token");

      // If request carried an older token that is no longer the active token,
      // this 401 is from a stale session and must NOT evict the new session.
      const isStaleRequest = Boolean(
        requestToken && currentToken && requestToken !== currentToken
      );

      if (!isStaleRequest && currentToken) {
        localStorage.removeItem("floatchat_token");
        localStorage.removeItem("floatchat_user");
        if (typeof sessionStorage !== "undefined") {
          sessionStorage.removeItem("floatchat_active_conversation_id");
        }

        emitAuthEvent({
          type: AUTH_EVENTS.UNAUTHORIZED,
          status: 401,
          url,
        });
      }
    }

    return Promise.reject(error);
  }
);

// Extract a useful, sanitized error message from backend responses.
export const getErrorMessage = (
  error,
  fallback = "Something went wrong. Please try again."
) => {
  if (!error) return fallback;

  const status = error?.response?.status;
  const retryAfter = error?.response?.headers?.["retry-after"];
  const serverMsg = error?.response?.data?.message || error?.response?.data?.detail;

  if (status === 429) {
    const retryNote = retryAfter ? ` Please wait ${retryAfter} seconds before retrying.` : "";
    const base = serverMsg || "Too many requests or AI service is currently busy.";
    return `${base}${retryNote}`;
  }
  if (status === 400) {
    return serverMsg || "Invalid request. Please check your query or input.";
  }
  if (status === 401) {
    return serverMsg || "Authentication required or session expired. Please sign in again.";
  }
  if (status === 403) {
    return serverMsg || "You are not authorized to perform this operation.";
  }
  if (status === 404) {
    return serverMsg || "The requested resource or conversation was not found.";
  }
  if (status === 422) {
    return serverMsg || "Validation failed: input data is invalid or empty.";
  }
  if (status === 502) {
    return serverMsg || "The AI service encountered an error or returned an invalid response.";
  }
  if (status === 503) {
    return serverMsg || "AI service is currently unavailable. Please try again shortly.";
  }
  if (status === 504) {
    return serverMsg || "AI analysis timed out. Deep scientific reasoning took longer than expected.";
  }
  if (status >= 500) {
    return serverMsg || "An internal application error occurred. Please try again later.";
  }

  if (error.code === "ECONNABORTED" || error.message?.toLowerCase().includes("timeout")) {
    return "Request timed out while waiting for AI scientific analysis. Please try again.";
  }

  if (!error.response && error.request) {
    return "Unable to reach the FloatChat server. Please check your connection.";
  }

  return serverMsg || error?.message || fallback;
};

// ----------------------------------------------------------------------
// Authentication APIs
// ----------------------------------------------------------------------
export const loginUser = async (credentials) => {
  const response = await api.post("/api/v1/auth/login", {
    email: credentials.email,
    password: credentials.password,
  });
  return response.data;
};

export const signupUser = async (userData) => {
  const response = await api.post("/api/v1/auth/signup", {
    name: userData.name,
    email: userData.email,
    password: userData.password,
  });
  return response.data;
};

export const registerUser = signupUser;

export const getCurrentUser = async () => {
  const response = await api.get("/api/v1/auth/me");
  return response.data;
};

// ----------------------------------------------------------------------
// AI Chat & Conversation APIs (Java backend endpoints)
// ----------------------------------------------------------------------
export const sendChatMessage = async (question, conversationId = null) => {
  // Allow up to 120s for local CPU inference
  const response = await api.post(
    "/api/v1/chat",
    {
      question,
      conversationId: conversationId || null,
    },
    { timeout: 120000 }
  );
  return response.data;
};

export const askAI = sendChatMessage;

export const getConversations = async () => {
  const response = await api.get("/api/v1/conversations");
  return response.data;
};

export const getConversation = async (id) => {
  const response = await api.get(`/api/v1/conversations/${id}`);
  return response.data;
};

export const deleteConversation = async (id) => {
  const response = await api.delete(`/api/v1/conversations/${id}`);
  return response.data;
};

// ----------------------------------------------------------------------
// Query History API
// ----------------------------------------------------------------------
export const getQueryHistory = async (page = 0, size = 10) => {
  const response = await api.get("/api/v1/history", {
    params: { page, size },
  });
  return response.data;
};

export const getHistory = getQueryHistory;

// ----------------------------------------------------------------------
// Visualizations API
// ----------------------------------------------------------------------
export const getVisualizations = async () => {
  const response = await api.get("/api/v1/visualizations");
  return response.data;
};

// ----------------------------------------------------------------------
// Role Dashboards APIs
// ----------------------------------------------------------------------
export const getUserDashboard = async () => {
  const response = await api.get("/api/v1/user/dashboard");
  return response.data;
};

export const getAdminDashboard = async () => {
  const response = await api.get("/api/v1/admin/dashboard");
  return response.data;
};

export const getSuperAdminDashboard = async () => {
  const response = await api.get("/api/v1/super-admin/dashboard");
  return response.data;
};

export const getDashboardStats = async () => {
  const response = await api.get("/api/v1/user/dashboard");
  return response.data;
};

// ----------------------------------------------------------------------
// Health & System APIs
// ----------------------------------------------------------------------
export const getHealth = async () => {
  const response = await api.get("/api/v1/health");
  return response.data;
};

export const getAiStatus = async () => {
  const response = await api.get("/api/v1/ai/status");
  return response.data;
};

// ----------------------------------------------------------------------
// Super Admin / Admin APIs
// ----------------------------------------------------------------------
export const createAdmin = async (adminData) => {
  const response = await api.post("/api/v1/auth/admins", {
    name: adminData.name,
    email: adminData.email,
    password: adminData.password,
  });
  return response.data;
};

export const getAdminUsers = async (page = 0, size = 10) => {
  const response = await api.get("/api/v1/admin/users", {
    params: { page, size },
  });
  return response.data;
};

export default api;
