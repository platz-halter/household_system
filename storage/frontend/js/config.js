// Runtime config — edit these two lines to match how your reverse proxy
// routes to the backend services. Kept as plain relative paths by default
// on the assumption Caddy serves this frontend and proxies /api/auth and
// /api/storage to the auth and storage-backend containers on the SAME
// origin — that avoids CORS entirely. See README.md for a sample
// Caddyfile snippet.
export const CONFIG = {
  AUTH_BASE: "/api/auth",
  STORAGE_BASE: "/api/storage",
};
