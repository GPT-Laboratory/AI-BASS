// store/modules/admin.js
import {
  // --- Auth ---
  login as apiLogin,
  logout as apiLogout,

  // --- Companies ---
  fetchCompanies,
  fetchCompanyById,
  createCompany,
  updateCompany,
  deleteCompany,
  fetchCompanyApiKey as apiFetchCompanyApiKey,
  generateCompanyApiKey as apiGenerateCompanyApiKey,
  revokeCompanyApiKey as apiRevokeCompanyApiKey,

  // --- Metadata ---
  fetchMetadata,
  fetchMetadataById,
  fetchMetadataByCompanyId,
  createMetadata,
  updateMetadata,
  deleteMetadata,

  // --- Users ---
  fetchUsers,
  fetchUserById,
  fetchUsersByCompanyId,
  createUser,
  updateUser,
  deleteUser,

  // --- Settings ---
  fetchSettings,
  saveSettings,

  // --- Google Drive ---
  initiateGoogleDriveAuth,
  syncGoogleDrive,
  disconnectGoogleDrive,
  fetchGoogleDriveFolders,
  fetchGoogleDriveFolderChildren,
  updateMonitoredFolders,

  // --- OneDrive ---
  initiateOneDriveAuth,
  syncOneDrive,
  disconnectOneDrive,
  fetchOneDriveFolders,
  fetchOneDriveFolderChildren,
  updateMonitoredOneDriveFolders,

  // --- Email Integration ---
  initiateEmailAuth,
  connectGenericEmail,
  syncEmails,
  disconnectEmail,
  fetchEmailFolders,

  // --- Memories ---
  fetchMemoriesByCompanyId,
  deleteMemory,
  fetchMemoryStats,
  fetchEmailSettings,
  updateEmailSettings,

  // --- Manual File Upload ---
  uploadFiles,
  deleteManualFile,
} from "../services/adminServices.js";

import { isTokenValid } from "../utils/jwt.js";

export default {
  namespaced: true,
  state: () => ({
    authToken: "",
    companies: [],
    selectedCompany: null,
    companyMetadata: [],
    selectedMetadata: null,
    companyMemories: [],
    memoryStats: null,
    users: [],
    selectedUser: null,
    settings: null,
    googleDriveFolders: [],
    monitoredFolders: [],
    oneDriveFolders: [],
    monitoredOneDriveFolders: [],
    loading: false,
    error: null,
    appLanguage: "fi",
    sessionExpiredMessage: null,
  }),

  mutations: {
    SET_TOKEN(state, token) {
      state.authToken = token;
    },
    CLEAR_TOKEN(state) {
      state.authToken = null;
    },
    SET_LANGUAGE(state, language) {
      state.appLanguage = language;
    },
    SET_COMPANIES(state, companies) {
      state.companies = companies;
    },
    SET_SELECTED_COMPANY(state, company) {
      state.selectedCompany = company;
    },
    SET_COMPANY_METADATA(state, metadata) {
      state.companyMetadata = metadata;
    },
    SET_SELECTED_METADATA(state, metadata) {
      state.selectedMetadata = metadata;
    },
    SET_COMPANY_MEMORIES(state, memories) {
      state.companyMemories = memories;
    },
    SET_MEMORY_STATS(state, stats) {
      state.memoryStats = stats;
    },
    SET_USERS(state, users) {
      state.users = users;
    },
    SET_SELECTED_USER(state, user) {
      state.selectedUser = user;
    },
    SET_SETTINGS(state, settings) {
      state.settings = settings;
    },
    SET_GOOGLE_DRIVE_FOLDERS(state, folders) {
      state.googleDriveFolders = folders;
    },
    SET_MONITORED_FOLDERS(state, folders) {
      state.monitoredFolders = folders;
    },
    SET_ONEDRIVE_FOLDERS(state, folders) {
      state.oneDriveFolders = folders;
    },
    SET_MONITORED_ONEDRIVE_FOLDERS(state, folders) {
      state.monitoredOneDriveFolders = folders;
    },
    SET_LOADING(state, status) {
      state.loading = status;
    },
    SET_ERROR(state, error) {
      state.error = error;
    },
    SET_SESSION_EXPIRED_MESSAGE(state, message) {
      state.sessionExpiredMessage = message;
    },
    CLEAR_SESSION_EXPIRED_MESSAGE(state) {
      state.sessionExpiredMessage = null;
    },
  },

  actions: {
    async login({ commit }, { username, password }) {
      commit("SET_LOADING", true);
      try {
        const token = await apiLogin(username, password);
        commit("SET_TOKEN", token);
      } catch (err) {
        commit("SET_ERROR", err);
        throw err;
      } finally {
        commit("SET_LOADING", false);
      }
    },

    logout({ commit, state }) {
      commit("CLEAR_TOKEN");
      localStorage.removeItem("authToken");
      apiLogout(state.authToken);
      commit("SET_COMPANIES", []);
      commit("SET_USERS", []);
      commit("SET_COMPANY_METADATA", []);
      commit("CLEAR_SESSION_EXPIRED_MESSAGE");
    },

    // Validate current authentication state
    validateAuth({ commit, state }, i18n = null) {
      if (!isTokenValid(state.authToken)) {
        const message = i18n ? i18n.t("session_expired") : "Your session has expired. Please log in again.";
        commit("SET_SESSION_EXPIRED_MESSAGE", message);
        commit("CLEAR_TOKEN");
        localStorage.removeItem("authToken");
        commit("SET_COMPANIES", []);
        commit("SET_USERS", []);
        commit("SET_COMPANY_METADATA", []);
        return false;
      }
      return true;
    },

    async setAppLanguage({ commit }, language) {
      commit("SET_LOADING", true);
      try {
        $i18n.locale = language;
        commit("SET_LANGUAGE", language);
      } catch (err) {
        commit("SET_ERROR", err);
      } finally {
        commit("SET_LOADING", false);
      }
    },

    async loadCompanies({ commit, state }, filters = {}) {
      commit("SET_LOADING", true);
      try {
        const res = await fetchCompanies(filters, state.authToken);
        commit("SET_COMPANIES", res.data);
      } catch (err) {
        commit("SET_ERROR", err);
      } finally {
        commit("SET_LOADING", false);
      }
    },

    async loadCompany({ commit, state }, id) {
      commit("SET_LOADING", true);
      try {
        const res = await fetchCompanyById(id, state.authToken);
        commit("SET_SELECTED_COMPANY", res.data);
      } catch (err) {
        commit("SET_ERROR", err);
      } finally {
        commit("SET_LOADING", false);
      }
    },

    async fetchCompanyApiKey({ commit, state }, companyId) {
      try {
        const res = await apiFetchCompanyApiKey(companyId, state.authToken);
        commit("SET_SELECTED_COMPANY", {
          ...(state.selectedCompany || {}),
          api_key: res.data?.api_key || "",
          api_key_created_at: res.data?.created_at || null,
        });
      } catch (err) {
        commit("SET_ERROR", err);
        throw err;
      }
    },

    async regenerateCompanyApiKey({ commit, state }, companyId) {
      try {
        const res = await apiGenerateCompanyApiKey(companyId, state.authToken);
        commit("SET_SELECTED_COMPANY", {
          ...(state.selectedCompany || {}),
          api_key: res.data?.api_key || "",
          api_key_created_at: res.data?.created_at || null,
        });
        return res.data;
      } catch (err) {
        commit("SET_ERROR", err);
        throw err;
      }
    },

    async revokeCompanyApiKey({ commit, state }, companyId) {
      try {
        await apiRevokeCompanyApiKey(companyId, state.authToken);
        commit("SET_SELECTED_COMPANY", {
          ...(state.selectedCompany || {}),
          api_key: "",
          api_key_created_at: null,
        });
      } catch (err) {
        commit("SET_ERROR", err);
        throw err;
      }
    },

    async addCompany({ dispatch, state }, data) {
      await createCompany(data, state.authToken);
      await dispatch("loadCompanies");
    },

    async editCompany({ dispatch, state }, { id, data }) {
      await updateCompany(id, data, state.authToken);
      await dispatch("loadCompanies");
    },

    async removeCompany({ dispatch, state }, id) {
      await deleteCompany(id, state.authToken);
      await dispatch("loadCompanies");
    },

    async loadMetadata({ commit, state }, filters = {}) {
      commit("SET_LOADING", true);
      try {
        const res = await fetchMetadata(filters, state.authToken);
        commit("SET_COMPANY_METADATA", res.data);
      } catch (err) {
        commit("SET_ERROR", err);
      } finally {
        commit("SET_LOADING", false);
      }
    },

    async loadMetadataById({ commit, state }, id) {
      commit("SET_LOADING", true);
      try {
        const res = await fetchMetadataById(id, state.authToken);
        commit("SET_SELECTED_METADATA", res.data);
      } catch (err) {
        commit("SET_ERROR", err);
      } finally {
        commit("SET_LOADING", false);
      }
    },

    async loadMetadataByCompanyId({ commit, state }, companyId) {
      commit("SET_LOADING", true);
      try {
        const res = await fetchMetadataByCompanyId(companyId, state.authToken);
        commit("SET_COMPANY_METADATA", res.data);
      } catch (err) {
        commit("SET_ERROR", err);
      } finally {
        commit("SET_LOADING", false);
      }
    },

    async addMetadata({ dispatch, state }, data) {
      await createMetadata(data, state.authToken);
      await dispatch("loadMetadata", { company_id: data.company_id });
    },

    async editMetadata({ dispatch, state }, { id, data }) {
      await updateMetadata(id, data, state.authToken);
      await dispatch("loadMetadata", { company_id: data.company_id });
    },

    async removeMetadata({ dispatch, state }, { id, company_id }) {
      await deleteMetadata(id, state.authToken);
      await dispatch("loadMetadata", { company_id });
    },

    async loadUsers({ commit, state }, filters = {}) {
      commit("SET_LOADING", true);
      try {
        const res = await fetchUsers(filters, state.authToken);
        commit("SET_USERS", res.data);
      } catch (err) {
        commit("SET_ERROR", err);
      } finally {
        commit("SET_LOADING", false);
      }
    },

    async loadUserById({ commit, state }, id) {
      commit("SET_LOADING", true);
      try {
        const res = await fetchUserById(id, state.authToken);
        commit("SET_SELECTED_USER", res.data);
      } catch (err) {
        commit("SET_ERROR", err);
      } finally {
        commit("SET_LOADING", false);
      }
    },

    async loadUsersByCompanyId({ commit, state }, companyId) {
      commit("SET_LOADING", true);
      try {
        const res = await fetchUsersByCompanyId(companyId, state.authToken);
        commit("SET_USERS", res.data);
      } catch (err) {
        commit("SET_ERROR", err);
      } finally {
        commit("SET_LOADING", false);
      }
    },

    async addUser({ dispatch, state }, data) {
      await createUser(data, state.authToken);
      await dispatch("loadUsersByCompanyId", data.company_id);
    },

    async editUser({ dispatch, state }, { id, data }) {
      await updateUser(id, data, state.authToken);
      await dispatch("loadUsersByCompanyId", data.company_id);
    },

    async removeUser({ dispatch, state }, { id, company_id }) {
      await deleteUser(id, state.authToken);
      await dispatch("loadUsersByCompanyId", company_id);
    },

    async loadSettings({ commit, state }) {
      commit("SET_LOADING", true);
      try {
        const res = await fetchSettings(state.authToken);
        commit("SET_SETTINGS", res.data);
      } catch (err) {
        commit("SET_ERROR", err);
      } finally {
        commit("SET_LOADING", false);
      }
    },

    async saveSettings({ commit, dispatch, state }, data) {
      commit("SET_LOADING", true);
      try {
        await saveSettings(data, state.authToken);
        await dispatch("loadSettings");
      } catch (err) {
        commit("SET_ERROR", err);
      } finally {
        commit("SET_LOADING", false);
      }
    },

    // ─── Memory Actions ─────────────────────────────────────────────────────
    async loadMemoriesByCompanyId({ commit, state }, companyId) {
      commit("SET_LOADING", true);
      try {
        const res = await fetchMemoriesByCompanyId(companyId, state.authToken);
        commit("SET_COMPANY_MEMORIES", res.data);
      } catch (err) {
        commit("SET_ERROR", err);
      } finally {
        commit("SET_LOADING", false);
      }
    },

    async loadMemoryStats({ commit, state }, companyId) {
      try {
        const res = await fetchMemoryStats(companyId, state.authToken);
        commit("SET_MEMORY_STATS", res.data);
      } catch (err) {
        commit("SET_ERROR", err);
      }
    },

    async removeMemory({ dispatch, state }, { memoryId, companyId }) {
      await deleteMemory(memoryId, state.authToken);
      await dispatch("loadMemoriesByCompanyId", companyId);
    },

    async connectGoogleDrive({ commit, state }, companyId) {
      commit("SET_LOADING", true);
      try {
        const res = await initiateGoogleDriveAuth(companyId, state.authToken);

        // Open OAuth popup
        const popup = window.open(res.data.authorization_url, "google-drive-auth", "width=500,height=600,scrollbars=yes,resizable=yes");

        // Wait for popup to close (user completes auth)
        return new Promise((resolve, reject) => {
          const checkClosed = setInterval(() => {
            if (popup.closed) {
              clearInterval(checkClosed);
              resolve();
            }
          }, 1000);

          // Timeout after 5 minutes
          setTimeout(() => {
            clearInterval(checkClosed);
            if (!popup.closed) {
              popup.close();
            }
            reject(new Error("Authentication timeout"));
          }, 300000);
        });
      } catch (err) {
        commit("SET_ERROR", err);
        throw err;
      } finally {
        commit("SET_LOADING", false);
      }
    },

    async syncGoogleDrive({ commit, state }, companyId) {
      commit("SET_LOADING", true);
      try {
        const res = await syncGoogleDrive(companyId, state.authToken);
        return res.data;
      } catch (err) {
        commit("SET_ERROR", err);
        throw err;
      } finally {
        commit("SET_LOADING", false);
      }
    },

    async disconnectGoogleDrive({ commit, state }, { companyId, removeSyncedFiles = false }) {
      commit("SET_LOADING", true);
      try {
        const res = await disconnectGoogleDrive(companyId, removeSyncedFiles, state.authToken);
        return res.data;
      } catch (err) {
        commit("SET_ERROR", err);
        throw err;
      } finally {
        commit("SET_LOADING", false);
      }
    },

    async loadGoogleDriveFolders({ commit, state }, companyId) {
      commit("SET_LOADING", true);
      try {
        const res = await fetchGoogleDriveFolders(companyId, state.authToken);
        commit("SET_GOOGLE_DRIVE_FOLDERS", res.data.folders);
        commit("SET_MONITORED_FOLDERS", res.data.monitored_folders);
        return res.data;
      } catch (err) {
        commit("SET_ERROR", err);
        throw err;
      } finally {
        commit("SET_LOADING", false);
      }
    },

    async loadGoogleDriveFolderChildren({ commit, state }, { companyId, parentId, driveId = null }) {
      commit("SET_LOADING", true);
      try {
        const res = await fetchGoogleDriveFolderChildren(companyId, parentId, state.authToken, driveId);
        return res.data;
      } catch (err) {
        commit("SET_ERROR", err);
        throw err;
      } finally {
        commit("SET_LOADING", false);
      }
    },

    async updateMonitoredFolders({ commit, state }, { companyId, folderIds }) {
      commit("SET_LOADING", true);
      try {
        const res = await updateMonitoredFolders(companyId, folderIds, state.authToken);
        commit("SET_MONITORED_FOLDERS", folderIds);
        return res.data;
      } catch (err) {
        commit("SET_ERROR", err);
        throw err;
      } finally {
        commit("SET_LOADING", false);
      }
    },

    // --- OneDrive Integration ---
    async connectOneDrive({ commit, state }, companyId) {
      commit("SET_LOADING", true);
      try {
        const res = await initiateOneDriveAuth(companyId, state.authToken);

        // Open popup window for OAuth
        const popup = window.open(res.data.auth_url, "onedrive-auth", "width=500,height=600,scrollbars=yes,resizable=yes");

        // Wait for popup to close (user completes auth)
        return new Promise((resolve, reject) => {
          const checkClosed = setInterval(() => {
            if (popup.closed) {
              clearInterval(checkClosed);
              resolve();
            }
          }, 1000);

          // Timeout after 5 minutes
          setTimeout(() => {
            clearInterval(checkClosed);
            if (!popup.closed) {
              popup.close();
            }
            reject(new Error("OneDrive authentication timeout"));
          }, 300000);
        });
      } catch (err) {
        commit("SET_ERROR", err);
        throw err;
      } finally {
        commit("SET_LOADING", false);
      }
    },

    async syncOneDrive({ commit, state }, companyId) {
      commit("SET_LOADING", true);
      try {
        const res = await syncOneDrive(companyId, state.authToken);
        return res.data;
      } catch (err) {
        commit("SET_ERROR", err);
        throw err;
      } finally {
        commit("SET_LOADING", false);
      }
    },

    async disconnectOneDrive({ commit, state }, { companyId, removeSyncedFiles = false }) {
      commit("SET_LOADING", true);
      try {
        const res = await disconnectOneDrive(companyId, removeSyncedFiles, state.authToken);
        return res.data;
      } catch (err) {
        commit("SET_ERROR", err);
        throw err;
      } finally {
        commit("SET_LOADING", false);
      }
    },

    async loadOneDriveFolders({ commit, state }, companyId) {
      commit("SET_LOADING", true);
      try {
        const res = await fetchOneDriveFolders(companyId, state.authToken);
        commit("SET_ONEDRIVE_FOLDERS", res.data.folders);
        commit("SET_MONITORED_ONEDRIVE_FOLDERS", res.data.monitored_folders || []);
        return res.data;
      } catch (err) {
        commit("SET_ERROR", err);
        throw err;
      } finally {
        commit("SET_LOADING", false);
      }
    },

    async loadOneDriveFolderChildren({ commit, state }, { companyId, parentId }) {
      commit("SET_LOADING", true);
      try {
        const res = await fetchOneDriveFolderChildren(companyId, parentId, state.authToken);
        return res.data;
      } catch (err) {
        commit("SET_ERROR", err);
        throw err;
      } finally {
        commit("SET_LOADING", false);
      }
    },

    async updateMonitoredOneDriveFolders({ commit, state }, { companyId, folderIds }) {
      commit("SET_LOADING", true);
      try {
        const res = await updateMonitoredOneDriveFolders(companyId, folderIds, state.authToken);
        commit("SET_MONITORED_ONEDRIVE_FOLDERS", folderIds);
        return res.data;
      } catch (err) {
        commit("SET_ERROR", err);
        throw err;
      } finally {
        commit("SET_LOADING", false);
      }
    },

    // --- Email Integration ---
    async connectEmail({ commit, state }, { companyId, provider }) {
      commit("SET_LOADING", true);
      try {
        const res = await initiateEmailAuth(companyId, provider, state.authToken);

        // Open popup window for OAuth
        const popup = window.open(res.data.authorization_url, "emailAuth", "width=500,height=600,scrollbars=yes,resizable=yes");

        return new Promise((resolve, reject) => {
          const checkClosed = setInterval(() => {
            if (popup.closed) {
              clearInterval(checkClosed);
              resolve();
            }
          }, 1000);

          // Timeout after 5 minutes
          setTimeout(() => {
            clearInterval(checkClosed);
            if (!popup.closed) {
              popup.close();
            }
            reject(new Error("Authentication timeout"));
          }, 300000);
        });
      } catch (err) {
        commit("SET_ERROR", err);
        throw err;
      } finally {
        commit("SET_LOADING", false);
      }
    },

    async connectGenericEmail({ commit, state }, { companyId, credentials }) {
      commit("SET_LOADING", true);
      try {
        const res = await connectGenericEmail(companyId, credentials, state.authToken);
        return res.data;
      } catch (err) {
        commit("SET_ERROR", err);
        throw err;
      } finally {
        commit("SET_LOADING", false);
      }
    },

    async syncEmails({ commit, state }, companyId) {
      commit("SET_LOADING", true);
      try {
        const res = await syncEmails(companyId, state.authToken);
        return res.data;
      } catch (err) {
        commit("SET_ERROR", err);
        throw err;
      } finally {
        commit("SET_LOADING", false);
      }
    },

    async disconnectEmail({ commit, state }, { companyId, removeSyncedEmails = false }) {
      commit("SET_LOADING", true);
      try {
        const res = await disconnectEmail(companyId, removeSyncedEmails, state.authToken);
        return res.data;
      } catch (err) {
        commit("SET_ERROR", err);
        throw err;
      } finally {
        commit("SET_LOADING", false);
      }
    },

    async loadEmailFolders({ commit, state }, companyId) {
      commit("SET_LOADING", true);
      try {
        const res = await fetchEmailFolders(companyId, state.authToken);
        return res.data;
      } catch (err) {
        commit("SET_ERROR", err);
        throw err;
      } finally {
        commit("SET_LOADING", false);
      }
    },

    async loadEmailSettings({ commit, state }, companyId) {
      commit("SET_LOADING", true);
      try {
        const res = await fetchEmailSettings(companyId, state.authToken);
        return res.data;
      } catch (err) {
        commit("SET_ERROR", err);
        throw err;
      } finally {
        commit("SET_LOADING", false);
      }
    },

    async updateEmailSettings({ commit, state }, { companyId, settings }) {
      commit("SET_LOADING", true);
      try {
        const res = await updateEmailSettings(companyId, settings, state.authToken);
        return res.data;
      } catch (err) {
        commit("SET_ERROR", err);
        throw err;
      } finally {
        commit("SET_LOADING", false);
      }
    },

    // Manual file upload actions
    async uploadFiles({ commit, state }, { companyId, formData }) {
      commit("SET_LOADING", true);
      try {
        const res = await uploadFiles(companyId, formData, state.authToken);
        return res.data;
      } catch (err) {
        commit("SET_ERROR", err);
        throw err;
      } finally {
        commit("SET_LOADING", false);
      }
    },

    async deleteManualFile({ commit, state }, { companyId, fileId }) {
      commit("SET_LOADING", true);
      try {
        const res = await deleteManualFile(companyId, fileId, state.authToken);
        return res.data;
      } catch (err) {
        commit("SET_ERROR", err);
        throw err;
      } finally {
        commit("SET_LOADING", false);
      }
    },
  },

  getters: {
    isAuthenticated: (state) => isTokenValid(state.authToken),
    getCompanyById: (state) => (id) => state.companies.find((c) => c._id === id),
    getMetadataByType: (state) => (type) => state.companyMetadata.filter((m) => m.type === type),
    getUsersByCompanyId: (state) => (companyId) => state.users.filter((u) => u.company_id === companyId),
    getSettings: (state) => state.settings,
    getSessionExpiredMessage: (state) => state.sessionExpiredMessage,
  },
};
