// services/adminServices.js
import { useApi } from "../composables/useApi.js";

/* ── AUTH ─────────────────────────────────────────────────────────────────── */
export const login = async (username, password) => {
  // Public – no token
  const { api } = useApi();
  const { data } = await api.post("/login", { username, password });
  console.log(data);
  return data.token;
};

export const logout = (token) => {
  const { api } = useApi(token);
  return api.post("/logout");
};

/* ── COMPANIES ────────────────────────────────────────────────────────────── */
export const fetchCompanies = (filters = {}, token) => useApi(token).api.get("/companies", { params: filters });
export const fetchCompanyById = (id, token) => useApi(token).api.get(`/companies/${id}`);
export const createCompany = (data, token) => useApi(token).api.post("/companies", data);
export const updateCompany = (id, data, token) => useApi(token).api.put(`/companies/${id}`, data);
export const deleteCompany = (id, token) => useApi(token).api.delete(`/companies/${id}`);
export const cleanupCompany = (id, token) => useApi(token).api.post(`/companies/${id}/cleanup`);
export const fetchCompanyApiKey = (id, token) => useApi(token).api.get(`/companies/${id}/api-key`);
export const generateCompanyApiKey = (id, token) => useApi(token).api.post(`/companies/${id}/api-key`);
export const revokeCompanyApiKey = (id, token) => useApi(token).api.delete(`/companies/${id}/api-key`);

/* ── METADATA ─────────────────────────────────────────────────────────────── */
export const fetchMetadata = (filters = {}, token) => useApi(token).api.get("/metadata", { params: filters });
export const fetchMetadataById = (id, token) => useApi(token).api.get(`/metadata/${id}`);
export const fetchMetadataByCompanyId = (companyId, token) => useApi(token).api.get(`/metadata/company/${companyId}`);
export const createMetadata = (data, token) => useApi(token).api.post("/metadata", data);
export const updateMetadata = (id, data, token) => useApi(token).api.put(`/metadata/${id}`, data);
export const deleteMetadata = (id, token) => useApi(token).api.delete(`/metadata/${id}`);

/* ── MEMORIES ─────────────────────────────────────────────────────────────── */
export const fetchMemoriesByCompanyId = (companyId, token) => useApi(token).api.get(`/memories/company/${companyId}`);
export const deleteMemory = (memoryId, token) => useApi(token).api.delete(`/memories/${memoryId}`);
export const fetchMemoryStats = (companyId, token) => useApi(token).api.get(`/memories/stats/${companyId}`);

/* ── USERS ─────────────────────────────────────────────────────────────────── */
export const fetchUsers = (filters = {}, token) => useApi(token).api.get("/users", { params: filters });
export const fetchUserById = (id, token) => useApi(token).api.get(`/users/${id}`);
export const fetchUsersByCompanyId = (companyId, token) => useApi(token).api.get(`/users/company/${companyId}`);
export const createUser = (data, token) => useApi(token).api.post("/users", data);
export const updateUser = (id, data, token) => useApi(token).api.put(`/users/${id}`, data);
export const deleteUser = (id, token) => useApi(token).api.delete(`/users/${id}`);

/* ── SETTINGS ───────────────────────────────────────────────────────────────── */
export const fetchSettings = (token) => useApi(token).api.get("/settings");
export const saveSettings = (data, token) => useApi(token).api.put("/settings", data);

/* ── GOOGLE DRIVE ───────────────────────────────────────────────────────────── */
export const initiateGoogleDriveAuth = (companyId, token) => useApi(token).api.post(`/companies/${companyId}/google-drive/auth`);
export const syncGoogleDrive = (companyId, token) => useApi(token).api.post(`/companies/${companyId}/google-drive/sync`);
export const disconnectGoogleDrive = (companyId, removeSyncedFiles, token) =>
  useApi(token).api.post(`/companies/${companyId}/google-drive/disconnect`, { remove_synced_files: removeSyncedFiles });
export const fetchGoogleDriveFolders = (companyId, token) => useApi(token).api.get(`/companies/${companyId}/google-drive/folders`);
export const fetchGoogleDriveFolderChildren = (companyId, parentId, token, driveId = null) => {
  const params = parentId ? { parent_id: parentId } : {};
  if (driveId) {
    params.drive_id = driveId;
  }
  return useApi(token).api.get(`/companies/${companyId}/google-drive/folders/children`, { params });
};
export const updateMonitoredFolders = (companyId, folderIds, token) => useApi(token).api.put(`/companies/${companyId}/google-drive/folders`, { folder_ids: folderIds });

/* ── ONEDRIVE ──────────────────────────────────────────────────────────────── */
export const initiateOneDriveAuth = (companyId, token) => useApi(token).api.post(`/companies/${companyId}/onedrive/auth`);
export const syncOneDrive = (companyId, token) => useApi(token).api.post(`/companies/${companyId}/onedrive/sync`);
export const disconnectOneDrive = (companyId, removeSyncedFiles, token) =>
  useApi(token).api.post(`/companies/${companyId}/onedrive/disconnect`, { remove_synced_files: removeSyncedFiles });
export const fetchOneDriveFolders = (companyId, token) => useApi(token).api.get(`/companies/${companyId}/onedrive/folders`);
export const fetchOneDriveFolderChildren = (companyId, parentId, token) => {
  const params = parentId ? { parent_id: parentId } : {};
  return useApi(token).api.get(`/companies/${companyId}/onedrive/folders/children`, { params });
};
export const updateMonitoredOneDriveFolders = (companyId, folderIds, token) => useApi(token).api.put(`/companies/${companyId}/onedrive/folders`, { folder_ids: folderIds });

/* ── EMAIL INTEGRATION ────────────────────────────────────────────────────── */
export const initiateEmailAuth = (companyId, provider, token) => useApi(token).api.post(`/companies/${companyId}/email/auth/${provider}`);
export const connectGenericEmail = (companyId, credentials, token) => useApi(token).api.post(`/companies/${companyId}/email/connect/generic`, credentials);
export const syncEmails = (companyId, token) => useApi(token).api.post(`/companies/${companyId}/email/sync`);
export const disconnectEmail = (companyId, removeSyncedEmails, token) =>
  useApi(token).api.post(`/companies/${companyId}/email/disconnect`, { remove_synced_emails: removeSyncedEmails });
export const fetchEmailFolders = (companyId, token) => useApi(token).api.get(`/companies/${companyId}/email/folders`);
export const fetchEmailSettings = (companyId, token) => useApi(token).api.get(`/companies/${companyId}/email/settings`);
export const updateEmailSettings = (companyId, settings, token) => useApi(token).api.put(`/companies/${companyId}/email/settings`, { settings });

/* ── MANUAL FILE UPLOAD ─────────────────────────────────────────────────────── */
export const uploadFiles = (companyId, formData, token) => {
  const { api } = useApi(token);
  return api.post(`/companies/${companyId}/files/upload`, formData, {
    headers: {
      "Content-Type": "multipart/form-data",
    },
  });
};

export const fetchManualFiles = (companyId, token) => useApi(token).api.get(`/companies/${companyId}/files`);
export const deleteManualFile = (companyId, fileId, token) => useApi(token).api.delete(`/companies/${companyId}/files/${fileId}`);

/* ── TOKEN USAGE STATISTICS ────────────────────────────────────────────────── */
export const fetchTokenUsage = (startTime, endTime, token, userId = null, companyId = null, companyEnv = null) => {
  const params = {
    start_time: startTime,
    end_time: endTime,
  };

  if (userId) {
    params.user_id = userId;
  }

  if (companyId) {
    params.company_id = companyId;
  }

  if (companyEnv) {
    params.company_env = companyEnv;
  }

  return useApi(token).api.get("/admin/token-usage", { params });
};

// Fetch metadata stats (counts by source/type) for a time range
export const fetchMetadataStats = (startTime, endTime, token, companyId = null) => {
  const params = {
    start_time: startTime,
    end_time: endTime,
  };

  if (companyId) {
    params.company_id = companyId;
  }

  return useApi(token).api.get("/admin/metadata-stats", { params });
};

// Fetch text-length mass by rag_document_class
export const fetchMetadataClassMass = (startTime, endTime, token, companyId = null) => {
  const params = {
    start_time: startTime,
    end_time: endTime,
  };

  if (companyId) {
    params.company_id = companyId;
  }

  return useApi(token).api.get("/admin/metadata-class-mass", { params });
};

// Fetch RAG class usage (references in chats) for a time range
export const fetchRagClassUsage = (startTime, endTime, token, companyId = null) => {
  const params = {
    start_time: startTime,
    end_time: endTime,
  };

  if (companyId) {
    params.company_id = companyId;
  }

  return useApi(token).api.get("/admin/rag-class-usage", { params });
};

// Fetch per-turn classifications with RAG document classes
export const fetchTurnClassifications = (startTime, endTime, token, userId = null, companyId = null) => {
  const params = {
    start_time: startTime,
    end_time: endTime,
  };

  if (userId) {
    params.user_id = userId;
  }

  if (companyId) {
    params.company_id = companyId;
  }

  return useApi(token).api.get("/admin/turn-classifications", { params });
};

// Fetch raw log entries for a time range (optionally filtered)
export const fetchLogEntries = (startTime, endTime, token, userId = null, companyId = null, companyEnv = null) => {
  const params = {
    start_time: startTime,
    end_time: endTime,
  };

  if (userId) {
    params.user_id = userId;
  }

  if (companyId) {
    params.company_id = companyId;
  }

  if (companyEnv) {
    params.company_env = companyEnv;
  }

  return useApi(token).api.get("/admin/log-entries", { params });
};

export const fetchReportScripts = (token) => useApi(token).api.get("/admin/report-scripts");

export const runReportScript = (scriptId, payload, token) =>
  useApi(token).api.post(`/admin/report-scripts/${scriptId}/run`, payload, {
    responseType: "blob",
  });
