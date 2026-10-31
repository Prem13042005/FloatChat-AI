import api from "./api";

export async function getUsers(page = 0, size = 10) {
  const response = await api.get("/api/v1/admin/users", {
    params: { page, size },
  });

  return response.data;
}

export async function updateUserRole(id, role) {
  const response = await api.patch(`/api/v1/admin/users/${id}/role`, { role });
  return response.data;
}

export async function updateUserStatus(id, enabled) {
  const response = await api.patch(`/api/v1/admin/users/${id}/status`, {
    enabled,
  });

  return response.data;
}

export async function getAuditLogs(page = 0, size = 20) {
  const response = await api.get("/api/v1/admin/audit-logs", {
    params: { page, size },
  });

  return response.data;
}