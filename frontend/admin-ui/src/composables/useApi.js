// composables/useApi.js
import axios from "axios";
import store from "../store"; // adjust path as needed
import { isTokenValid } from "../utils/jwt.js";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || "http://localhost:5000";

/**
 * Create an Axios instance.
 * @param {string|null} token – Bearer token or null for public calls.
 */
export function useApi(token = null) {
  const api = axios.create({
    baseURL: API_BASE_URL,
    headers: { "Content-Type": "application/json" },
  });

  api.interceptors.request.use(
    (cfg) => {
      // Check token validity before making the request
      if (token && !isTokenValid(token)) {
        store.dispatch("admin/logout");
        return Promise.reject(new Error("Token expired"));
      }

      if (token) cfg.headers.Authorization = `Bearer ${token}`;
      return cfg;
    },
    (err) => Promise.reject(err)
  );

  api.interceptors.response.use(
    (res) => res,
    (err) => {
      console.error("API Error:", err.response || err.message);
      if (err.response && err.response.status === 401) {
        // Use a generic message since we can't access i18n here easily
        store.commit("admin/SET_SESSION_EXPIRED_MESSAGE", "Your session has expired. Please log in again.");
        store.dispatch("admin/logout");
        // Redirect to login if not already there
        const currentPath = window.location.pathname;
        if (currentPath !== "/login") {
          window.location.href = "/login";
        }
      }
      return Promise.reject(err);
    }
  );

  return { api };
}
