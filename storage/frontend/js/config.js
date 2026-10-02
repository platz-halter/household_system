// Runtime config — edit these two lines to match how your reverse proxy
// routes to the backend services. Kept as plain relative paths by default
// on the assumption Caddy serves this frontend and proxies /api/auth and
// /api/storage to the auth and storage-backend containers on the SAME
// origin — that avoids CORS entirely. See README.md for a sample
// Caddyfile snippet.
export const CONFIG = {
  AUTH_BASE: "/api/auth",
  STORAGE_BASE: "/api/storage",

  // --- Authentik OIDC (Authorization Code + PKCE, public SPA client —
  // no client secret, since that can't be kept confidential in a
  // browser). AUTHENTIK_CLIENT_ID must be the SAME value as the
  // AUTHENTIK_CLIENT_ID env var the backends check the token audience
  // against. The authorize/token endpoints are instance-wide; the
  // end-session endpoint is per-application, matching the issuer
  // pattern already used in shared/config.py. Verify all of these
  // against <issuer>.well-known/openid-configuration if anything looks
  // off — paths can vary slightly by Authentik version.
  AUTHENTIK_CLIENT_ID: "",
  AUTHENTIK_AUTHORIZE_URL: "https://authentik.pressnet.duckdns.org/application/o/authorize/",
  AUTHENTIK_TOKEN_URL: "https://authentik.pressnet.duckdns.org/application/o/token/",
  AUTHENTIK_END_SESSION_URL: "https://authentik.pressnet.duckdns.org/application/o/household-system/end-session/",
  // Must exactly match a "Redirect URI" registered on the Authentik
  // provider — computed from wherever this page is actually served
  // rather than hardcoded, so it's correct through Caddy, localhost
  // testing, etc. without editing this file per environment.
  AUTHENTIK_REDIRECT_URI: window.location.origin + "/",
  // "groups" is NOT one of Authentik's built-in scopes — you need to
  // create a custom Scope Mapping that emits the groups claim and add
  // it to the provider. See README.md.
  AUTHENTIK_SCOPE: "openid profile email groups",
};
