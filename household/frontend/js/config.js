// Runtime config — edit these two lines to match how your reverse proxy
// routes to the backend services. Kept as plain relative paths by default
// on the assumption Caddy serves this frontend and proxies /api/auth and
// /api/household to the auth and household-backend containers on the SAME
// origin — that avoids CORS entirely. See README.md for a sample
// Caddyfile snippet.
export const CONFIG = {
  //AUTH_BASE: "/api/auth",
  //HOUSEHOLD_BASE: "/api/household",

  // No-proxy placeholder for local dev — see README.md.
  AUTH_BASE: "http://127.0.0.1:8001",
  HOUSEHOLD_BASE: "http://127.0.0.1:8002",

  // --- Authentik OIDC (Authorization Code + PKCE, public SPA client —
  // no client secret, since that can't be kept confidential in a
  // browser). AUTHENTIK_CLIENT_ID must be the SAME value as the
  // AUTHENTIK_CLIENT_ID env var the backends check the token audience
  // against — this is the same Authentik Application as storage's
  // frontend, just served from a different origin, so its provider
  // needs this origin added as an additional Redirect URI. Verify all
  // of these against <issuer>/.well-known/openid-configuration if
  // anything looks off — paths can vary slightly by Authentik version.
  AUTHENTIK_CLIENT_ID: "",
  AUTHENTIK_AUTHORIZE_URL:
    "https://authentik.pressnet.duckdns.org/application/o/authorize/",
  AUTHENTIK_TOKEN_URL:
    "https://authentik.pressnet.duckdns.org/application/o/token/",
  AUTHENTIK_END_SESSION_URL:
    "https://authentik.pressnet.duckdns.org/application/o/household-system/end-session/",
  // Must exactly match a "Redirect URI" registered on the Authentik
  // provider — computed from wherever this page is actually served
  // rather than hardcoded, so it's correct through Caddy, localhost
  // testing, etc. without editing this file per environment.
  AUTHENTIK_REDIRECT_URI: window.location.origin + "/",
  // "groups" is NOT one of Authentik's built-in scopes — you need to
  // create a custom Scope Mapping that emits the groups claim and add
  // it to the provider. See storage/frontend/README.md.
  AUTHENTIK_SCOPE: "openid profile email groups",
};
