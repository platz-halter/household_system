// Runtime config — edit these two lines to match how your reverse proxy
// routes to the backend services. Kept as plain relative paths by default
// on the assumption Caddy serves this frontend and proxies /api/auth and
// /api/household to the auth and household-backend containers on the SAME
// origin — that avoids CORS entirely. See README.md for a sample
// Caddyfile snippet.
export const CONFIG = {
  AUTH_BASE: "/api/auth",
  HOUSEHOLD_BASE: "/api/household",

  // No-proxy placeholder — only needed if you're running the backends
  // directly (not through this container's nginx or an external
  // reverse proxy) and hitting CORS as a result. Swap the two lines
  // above for these if so:
  // AUTH_BASE: "http://127.0.0.1:8001",
  // HOUSEHOLD_BASE: "http://127.0.0.1:8002",

  // --- Authentik OIDC (Authorization Code + PKCE, public SPA client —
  // no client secret, since that can't be kept confidential in a
  // browser). client_id, the authorize/token/end-session URLs, and the
  // scope string used to be hardcoded here — they now live in the auth
  // service's database (admin-editable through this app's own Admin
  // panel instead of hand-editing this file + .env on every service;
  // see auth_service.main's GET/PUT /authentik-config), and js/auth.js
  // fetches them at runtime. This file only needs the one thing that
  // genuinely can't come from the backend: the redirect URI, since it
  // has to be wherever THIS page is actually being served from — this
  // is the same Authentik Application as storage's frontend, just
  // served from a different origin, so its provider needs this origin
  // added as an additional Redirect URI.
  //
  // Must exactly match a "Redirect URI" registered on the Authentik
  // provider — computed from wherever this page is actually served
  // rather than hardcoded, so it's correct through Caddy, localhost
  // testing, etc. without editing this file per environment.
  AUTHENTIK_REDIRECT_URI: window.location.origin + "/",
};
