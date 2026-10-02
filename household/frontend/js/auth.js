import { CONFIG } from "./config.js";

const TOKEN_KEY = "hs_token";
const SOURCE_KEY = "hs_auth_source"; // "local" | "authentik"
const REFRESH_TOKEN_KEY = "hs_refresh_token"; // authentik only
const ID_TOKEN_KEY = "hs_id_token"; // authentik only — needed as id_token_hint on logout
const OIDC_STATE_KEY = "hs_oidc_state"; // sessionStorage
const OIDC_VERIFIER_KEY = "hs_oidc_verifier"; // sessionStorage

// Mirrors shared/src/shared/auth.py's GROUP_ROLE_MAP. This copy is for
// UI display/gating ONLY (hiding the add-item button for viewers, etc.)
// — the backend independently enforces the real rule from the same
// groups claim, so a stale copy here is a UX annoyance, never a
// security hole. Keep the two in sync when group names change.
const ROLE_FROM_GROUPS = {
  "household-system-admins": "admin",
  "household-system-users": "user",
  "household-system-viewers": "viewer",
};

// Full-page redirects go through this indirection ONLY so tests can
// observe the target URL — jsdom doesn't implement real navigation, so
// window.location.assign() is unobservable there. Real app code always
// uses the default; __setNavigateForTests is not called outside tests.
let _navigate = (url) => window.location.assign(url);
export function __setNavigateForTests(fn) {
  _navigate = fn;
}

export function getToken() {
  return localStorage.getItem(TOKEN_KEY);
}

function setSession({ accessToken, source, refreshToken, idToken }) {
  localStorage.setItem(TOKEN_KEY, accessToken);
  localStorage.setItem(SOURCE_KEY, source);
  if (refreshToken) localStorage.setItem(REFRESH_TOKEN_KEY, refreshToken);
  if (idToken) localStorage.setItem(ID_TOKEN_KEY, idToken);
}

export function clearToken() {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(SOURCE_KEY);
  localStorage.removeItem(REFRESH_TOKEN_KEY);
  localStorage.removeItem(ID_TOKEN_KEY);
}

export function isAuthenticated() {
  return Boolean(getToken());
}

export function getAuthSource() {
  return localStorage.getItem(SOURCE_KEY);
}

/**
 * Decodes the JWT payload for DISPLAY purposes only. This does not
 * verify the signature — the backend is the only thing that actually
 * trusts this token. Never make an authorization decision in the
 * frontend based on this.
 */
export function decodeToken() {
  const token = getToken();
  if (!token) return null;
  try {
    const payload = token.split(".")[1];
    const json = atob(payload.replace(/-/g, "+").replace(/_/g, "/"));
    return JSON.parse(json);
  } catch {
    return null;
  }
}

/**
 * Resolves {subject, role, source} regardless of which token shape is
 * active — a local token carries `role` directly, an Authentik token
 * carries `groups` and needs mapping. Use this (not decodeToken()
 * directly) anywhere the UI needs the current user's role.
 */
export function getCurrentUserInfo() {
  const payload = decodeToken();
  if (!payload) return null;

  if (payload.role) {
    return { subject: payload.sub, role: payload.role, source: "local" };
  }
  if (payload.groups) {
    let role = "viewer";
    for (const group of payload.groups) {
      if (group in ROLE_FROM_GROUPS) {
        role = ROLE_FROM_GROUPS[group];
        break;
      }
    }
    return { subject: payload.preferred_username || payload.sub, role, source: "authentik" };
  }
  return { subject: payload.sub || "unknown", role: "viewer", source: getAuthSource() || "unknown" };
}

// --- Local account login -------------------------------------------

export async function login(username, password) {
  const body = new URLSearchParams();
  body.set("username", username);
  body.set("password", password);

  const resp = await fetch(`${CONFIG.AUTH_BASE}/token`, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body,
  });

  if (!resp.ok) {
    let detail = "Login failed";
    try {
      detail = (await resp.json()).detail || detail;
    } catch {
      /* ignore parse errors, use default message */
    }
    throw new Error(detail);
  }

  const data = await resp.json();
  clearToken(); // drop any leftover Authentik session state first
  setSession({ accessToken: data.access_token, source: "local" });
}

// --- Authentik OIDC (Authorization Code + PKCE, public SPA client) --

// Authentik being unreachable (down, DNS/network issue) must not hang
// forever — plain fetch() has no built-in timeout, and an unresolved
// await here blocks boot()'s startRouter() call, which looks like the
// app is stuck in an infinite loading loop with no way out but a hard
// refresh. Aborting after a few seconds lets the existing try/catch
// paths below treat it as an ordinary failure instead.
const AUTHENTIK_FETCH_TIMEOUT_MS = 8000;

async function fetchWithTimeout(url, options) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), AUTHENTIK_FETCH_TIMEOUT_MS);
  try {
    return await fetch(url, { ...options, signal: controller.signal });
  } finally {
    clearTimeout(timer);
  }
}

function base64UrlEncode(bytes) {
  let str = "";
  for (const b of bytes) str += String.fromCharCode(b);
  return btoa(str).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

function randomString(byteLength = 48) {
  const bytes = new Uint8Array(byteLength);
  crypto.getRandomValues(bytes);
  return base64UrlEncode(bytes);
}

async function sha256Base64Url(text) {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
  return base64UrlEncode(new Uint8Array(digest));
}

/** Redirects the browser to Authentik's login page. Never returns. */
export async function loginWithAuthentik() {
  const verifier = randomString(48);
  const challenge = await sha256Base64Url(verifier);
  const state = randomString(24);

  sessionStorage.setItem(OIDC_VERIFIER_KEY, verifier);
  sessionStorage.setItem(OIDC_STATE_KEY, state);

  const params = new URLSearchParams({
    response_type: "code",
    client_id: CONFIG.AUTHENTIK_CLIENT_ID,
    redirect_uri: CONFIG.AUTHENTIK_REDIRECT_URI,
    scope: CONFIG.AUTHENTIK_SCOPE,
    state,
    code_challenge: challenge,
    code_challenge_method: "S256",
  });
  _navigate(`${CONFIG.AUTHENTIK_AUTHORIZE_URL}?${params}`);
}

/**
 * Called once on app boot. If the current URL is an Authentik callback
 * (?code=...&state=...), exchanges the code for tokens and cleans the
 * URL up. No-ops (returns false) for a normal page load. Returns true
 * only on a successful login.
 */
export async function handleAuthentikCallback() {
  const params = new URLSearchParams(window.location.search);
  const code = params.get("code");
  const error = params.get("error");

  if (!code && !error) return false;

  // Clean the callback params out of the URL either way, so a reload
  // doesn't try to replay an already-used authorization code.
  const cleanUrl = window.location.origin + window.location.pathname + window.location.hash;
  window.history.replaceState({}, "", cleanUrl);

  const expectedState = sessionStorage.getItem(OIDC_STATE_KEY);
  const verifier = sessionStorage.getItem(OIDC_VERIFIER_KEY);
  sessionStorage.removeItem(OIDC_STATE_KEY);
  sessionStorage.removeItem(OIDC_VERIFIER_KEY);

  if (error) return false; // e.g. the user cancelled at Authentik's consent screen
  if (!verifier || !expectedState || params.get("state") !== expectedState) return false;

  try {
    const body = new URLSearchParams({
      grant_type: "authorization_code",
      code,
      redirect_uri: CONFIG.AUTHENTIK_REDIRECT_URI,
      client_id: CONFIG.AUTHENTIK_CLIENT_ID,
      code_verifier: verifier,
    });
    const resp = await fetchWithTimeout(CONFIG.AUTHENTIK_TOKEN_URL, {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body,
    });
    if (!resp.ok) return false;

    const data = await resp.json();
    clearToken();
    setSession({
      accessToken: data.access_token,
      source: "authentik",
      refreshToken: data.refresh_token,
      idToken: data.id_token,
    });
    return true;
  } catch {
    return false;
  }
}

/**
 * Used by api.js on a 401 for an Authentik-sourced session — tries to
 * get a new access token with the stored refresh token before giving up
 * and sending the user back to login. Returns true on success.
 */
export async function tryRefreshAuthentikToken() {
  const refreshToken = localStorage.getItem(REFRESH_TOKEN_KEY);
  if (!refreshToken) return false;

  try {
    const body = new URLSearchParams({
      grant_type: "refresh_token",
      refresh_token: refreshToken,
      client_id: CONFIG.AUTHENTIK_CLIENT_ID,
    });
    const resp = await fetchWithTimeout(CONFIG.AUTHENTIK_TOKEN_URL, {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body,
    });
    if (!resp.ok) return false;

    const data = await resp.json();
    localStorage.setItem(TOKEN_KEY, data.access_token);
    // Authentik rotates refresh tokens by default — if it didn't send a
    // new one, keep using the current one rather than discard it.
    if (data.refresh_token) localStorage.setItem(REFRESH_TOKEN_KEY, data.refresh_token);
    return true;
  } catch {
    return false;
  }
}

export function logout() {
  const source = getAuthSource();
  const idToken = localStorage.getItem(ID_TOKEN_KEY);
  clearToken();

  if (source === "authentik" && CONFIG.AUTHENTIK_END_SESSION_URL) {
    const params = new URLSearchParams({ post_logout_redirect_uri: window.location.origin + "/" });
    if (idToken) params.set("id_token_hint", idToken);
    _navigate(`${CONFIG.AUTHENTIK_END_SESSION_URL}?${params}`);
    return; // browser is navigating away — nothing left to do here
  }
  window.location.hash = "#/login";
}
