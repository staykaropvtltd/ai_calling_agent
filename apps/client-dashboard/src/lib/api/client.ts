// Central axios instance.
// Attaches the JWT to every request and handles silent token refresh.
// Import this — never use raw fetch/axios elsewhere.

import axios, { type AxiosRequestConfig, type AxiosResponse } from "axios";

const BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost/api";

const client = axios.create({
  baseURL: BASE_URL,
  headers: { "Content-Type": "application/json" },
  timeout: 10_000,
});

// ── Request interceptor — attach access token ─────────────────────────────
client.interceptors.request.use((config) => {
  const token = getAccessToken();
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

// ── Response interceptor — silent refresh on 401 ─────────────────────────
let isRefreshing = false;
let refreshQueue: Array<(token: string) => void> = [];

client.interceptors.response.use(
  (res) => res,
  async (error) => {
    const original = error.config as AxiosRequestConfig & { _retry?: boolean };

    if (error.response?.status !== 401 || original._retry) {
      return Promise.reject(error);
    }

    if (isRefreshing) {
      return new Promise((resolve) => {
        refreshQueue.push((token) => {
          original.headers = { ...original.headers, Authorization: `Bearer ${token}` };
          resolve(client(original));
        });
      });
    }

    original._retry = true;
    isRefreshing = true;

    try {
      const refreshToken = getRefreshToken();
      if (!refreshToken) throw new Error("No refresh token");

      const { data } = await axios.post<{ access_token: string; refresh_token: string }>(
        `${BASE_URL}/auth/refresh`,
        { refresh_token: refreshToken },
      );

      setTokens(data.access_token, data.refresh_token);
      refreshQueue.forEach((cb) => cb(data.access_token));
      refreshQueue = [];

      original.headers = { ...original.headers, Authorization: `Bearer ${data.access_token}` };
      return client(original);
    } catch {
      clearTokens();
      // This runs inside an axios interceptor, outside React's render tree —
      // no useRouter() available here, so a raw navigation is the only option.
      // Bypasses Next's basePath-aware router, so "/client" (next.config.js)
      // must be spelled out explicitly.
      // eslint-disable-next-line @next/next/no-location-assign-relative-destination
      window.location.href = "/client/login/";
      return Promise.reject(error);
    } finally {
      isRefreshing = false;
    }
  },
);

// ── Token storage ─────────────────────────────────────────────────────────
// Using sessionStorage so tokens die with the browser tab.
// Switch to httpOnly cookies (server-side) when NK-05 supports it.
const TOKEN_KEY = "sk_access";
const REFRESH_KEY = "sk_refresh";

export function getAccessToken() {
  return typeof window !== "undefined" ? sessionStorage.getItem(TOKEN_KEY) : null;
}

function getRefreshToken() {
  return typeof window !== "undefined" ? sessionStorage.getItem(REFRESH_KEY) : null;
}

export function setTokens(access: string, refresh: string) {
  sessionStorage.setItem(TOKEN_KEY, access);
  sessionStorage.setItem(REFRESH_KEY, refresh);
}

export function clearTokens() {
  sessionStorage.removeItem(TOKEN_KEY);
  sessionStorage.removeItem(REFRESH_KEY);
}

export default client;
