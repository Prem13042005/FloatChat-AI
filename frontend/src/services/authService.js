
import api, {
  loginUser,
  signupUser,
} from "./api.js";

const TOKEN_KEY = "floatchat_token";
const USER_KEY = "floatchat_user";

export function getToken() {
  return localStorage.getItem(TOKEN_KEY);
}

export function getUser() {
  const storedUser = localStorage.getItem(USER_KEY);

  if (!storedUser) return null;

  try {
    return JSON.parse(storedUser);
  } catch {
    localStorage.removeItem(USER_KEY);
    return null;
  }
}

export function isAuthenticated() {
  return Boolean(getToken());
}

export function saveAuth(response) {
  if (!response?.token || !response?.user) {
    throw new Error("Invalid authentication response from server.");
  }

  localStorage.setItem(TOKEN_KEY, response.token);
  localStorage.setItem(USER_KEY, JSON.stringify(response.user));

  return response.user;
}

export async function login(email, password) {
  const response = await loginUser({
    email: email.trim(),
    password,
  });

  return saveAuth(response);
}

export async function register(userData) {
  const response = await signupUser({
    name: userData.name,
    email: userData.email,
    password: userData.password,
  });

  if (response?.token && response?.user) {
    saveAuth(response);
  }

  return response;
}

export function logout() {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(USER_KEY);
}

export const clearAuth = logout;
export const logoutUser = logout;
export const registerUser = register;

// Request a password reset.
// Backend endpoint must be implemented.
export async function requestPasswordReset(email) {
  const response = await api.post("/api/v1/auth/forgot-password", {
    email: email.trim(),
  });

  return response.data;
}

// Reset password using a reset token.
// Backend endpoint must be implemented.
export async function resetPassword(token, newPassword) {
  const response = await api.post("/api/v1/auth/reset-password", {
    token,
    newPassword,
  });

  return response.data;
}

// Change password for the currently authenticated user.
// Backend endpoint must be implemented.
export async function changePassword(
  currentPassword,
  newPassword
) {
  const response = await api.post("/api/v1/auth/change-password", {
    currentPassword,
    newPassword,
  });

  return response.data;
}
