import { CONFIG } from "./config.js";
import { t } from "./i18n.js";

const TOKEN_KEY = "hs_token";
const SOURCE_KEY = "hs_auth_source"; // "local" | "authentik"
const REFRESH_TOKEN_KEY = "hs_refresh_token"; // authentik only
const ID_TOKEN_KEY = "hs_id_token"; // authentik only — needed as id_token_hint on logout
// Stashed at login time so logout() needs no fetch — see getAuthentikConfig()
// below for why end_session_url specifically can't come from a static
// constant anymore, and why logout() still shouldn't need a network call.
const END_SESSION_URL_KEY = "hs_end_session_url";
const OIDC_STATE_KEY = "hs_oidc_state"; // sessionStorage
const OIDC_VERIFIER_KEY = "hs_oidc_verifier"; // sessionStorage

// The admin/user/viewer group NAMES, for UI display/gating ONLY (hiding
// the add-item button for viewers, the router's /admin guard, etc.) —
// the backend independently enforces the real rule from the same groups
// claim via its own copy of this same config, so a stale value here is a
// UX annoyance, never a security hole (proved live: a real production
// user whose Authentik groups had been renamed via the admin panel kept
// getting 200s from admin-only API routes the whole time, while the
// frontend wrongly showed them as "viewer" and blocked /admin — this
// mapping was still the old hardcoded default and nothing had told it
// otherwise).
//
// Starts at the same generic defaults the project always shipped with,
// in case warmGroupRoleMap() below hasn't completed yet or fails — gets
// replaced with the real values (same admin_group/user_group/
// viewer_group an admin can set through the panel) once that first
// fetch resolves. Deliberately the SAME field names/shape as the
// backend's own config dict (shared.auth._role_from_groups) rather than
// a {groupName: role} map, so the matching logic below can mirror the
// backend's fixed admin > user > viewer precedence exactly, instead of
// the old "whichever recognized group the token happens to list first"
// behavior, which was never a deliberate design, just an artifact of
// how the old hardcoded dict got checked.
let groupRoleConfig = {
  admin_group: "household-system-admins",
  user_group: "household-system-users",
  viewer_group: "household-system-viewers",
};

/**
 * Kicks off a fetch to pick up the real, possibly-admin-customized group
 * names — call this once at boot, but NEVER awaited there (see
 * main.js's boot()): an unreachable auth service must not delay the
 * very first render the same way an unawaited Authentik token exchange
 * could, which is exactly the failure mode `fetchWithTimeout` elsewhere
 * in this file already exists to prevent. Safe to call repeatedly;
 * cheap no-op once `getAuthentikConfig()`'s own cache is warm.
 */
export async function warmGroupRoleMap() {
  try {
    const config = await getAuthentikConfig();
    groupRoleConfig = {
      admin_group: config.admin_group,
      user_group: config.user_group,
      viewer_group: config.viewer_group,
    };
  } catch {
    // Keep whatever's already in groupRoleConfig (the default, or a
    // previously successful fetch) — same "don't let an unreachable
    // auth service break what's already working" principle as every
    // other getAuthentikConfig() caller in this file.
  }
}

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

function setSession({ accessToken, source, refreshToken, idToken, endSessionUrl }) {
  localStorage.setItem(TOKEN_KEY, accessToken);
  localStorage.setItem(SOURCE_KEY, source);
  if (refreshToken) localStorage.setItem(REFRESH_TOKEN_KEY, refreshToken);
  if (idToken) localStorage.setItem(ID_TOKEN_KEY, idToken);
  if (endSessionUrl) localStorage.setItem(END_SESSION_URL_KEY, endSessionUrl);
}

export function clearToken() {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(SOURCE_KEY);
  localStorage.removeItem(REFRESH_TOKEN_KEY);
  localStorage.removeItem(ID_TOKEN_KEY);
  localStorage.removeItem(END_SESSION_URL_KEY);
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
    // Fixed admin > user > viewer precedence, matching
    // shared.auth._role_from_groups exactly — not whatever order the
    // token happens to list its groups in.
    let role = "viewer";
    if (payload.groups.includes(groupRoleConfig.admin_group)) role = "admin";
    else if (payload.groups.includes(groupRoleConfig.user_group)) role = "user";
    else if (payload.groups.includes(groupRoleConfig.viewer_group)) role = "viewer";
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
    // The real `detail` text below, when the backend sends one (e.g. a
    // bad password, or auth_service/rate_limit.py's lockout message),
    // is backend-produced and stays English-only regardless of locale
    // — a known, documented gap (same category as household/frontend's
    // own i18n round: translating it would need real backend error
    // codes, not just a frontend string lookup). This fallback is the
    // one piece that IS fixable client-side: it's only ever used if the
    // response body can't even be parsed as JSON.
    let detail = t("login.failed");
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

// The actual Authentik connection details (client_id, authorize/token/
// end_session URLs, scope) used to be hardcoded here in config.js. They
// now live in the auth service's database, editable through the admin
// panel instead of hand-editing this file + .env on every service — see
// auth_service.main's GET/PUT /authentik-config and shared.auth
// ._AuthentikConfigCache (the backend-side equivalent of this same
// cache). Fetched once per page load and cached in-module; a stale copy
// for the rest of this tab's session is an acceptable tradeoff for not
// hitting this on every call, and a fresh page load always re-fetches.
let authentikConfigCache = null;

async function getAuthentikConfig() {
  if (!authentikConfigCache) {
    const resp = await fetchWithTimeout(`${CONFIG.AUTH_BASE}/authentik-config`);
    if (!resp.ok) throw new Error("Could not load Authentik configuration");
    authentikConfigCache = await resp.json();
  }
  return authentikConfigCache;
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
  const config = await getAuthentikConfig();
  const verifier = randomString(48);
  const challenge = await sha256Base64Url(verifier);
  const state = randomString(24);

  sessionStorage.setItem(OIDC_VERIFIER_KEY, verifier);
  sessionStorage.setItem(OIDC_STATE_KEY, state);

  const params = new URLSearchParams({
    response_type: "code",
    client_id: config.client_id,
    redirect_uri: CONFIG.AUTHENTIK_REDIRECT_URI,
    scope: config.scope,
    state,
    code_challenge: challenge,
    code_challenge_method: "S256",
  });
  _navigate(`${config.authorize_url}?${params}`);
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
  // doesn't try to replay an already-used authorization code. Pathname
  // only — AUTHENTIK_REDIRECT_URI is always origin + "/", so this is
  // always just the bare root; main.js's boot() sends it on to the
  // default route right after this resolves.
  const cleanUrl = window.location.origin + window.location.pathname;
  window.history.replaceState({}, "", cleanUrl);

  const expectedState = sessionStorage.getItem(OIDC_STATE_KEY);
  const verifier = sessionStorage.getItem(OIDC_VERIFIER_KEY);
  sessionStorage.removeItem(OIDC_STATE_KEY);
  sessionStorage.removeItem(OIDC_VERIFIER_KEY);

  if (error) return false; // e.g. the user cancelled at Authentik's consent screen
  if (!verifier || !expectedState || params.get("state") !== expectedState) return false;

  // Only reached once we know this really is a callback — a normal page
  // load returned false above already, so boot() never waits on this
  // fetch for the common case.
  try {
    const config = await getAuthentikConfig();
    const body = new URLSearchParams({
      grant_type: "authorization_code",
      code,
      redirect_uri: CONFIG.AUTHENTIK_REDIRECT_URI,
      client_id: config.client_id,
      code_verifier: verifier,
    });
    const resp = await fetchWithTimeout(config.token_url, {
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
      endSessionUrl: config.end_session_url,
    });
    return true;
  } catch {
    return false;
  }
}

// Authentik rotates refresh tokens by default — each one is single-use,
// so once a refresh call consumes it, the old value is dead even if the
// call is still in flight. api.js calls tryRefreshAuthentikToken() from
// EVERY 401'd request independently, and a page frequently fires several
// requests at once (e.g. on load) — if more than one happens to 401 at
// the same moment, without this guard each would read the SAME
// not-yet-rotated refresh token and race to spend it. Authentik accepts
// only the first; every other concurrent caller gets a flat rejection
// and (per api.js) treats that as a real logout — dropping an otherwise
// perfectly good, just-renewed session. Sharing one in-flight promise
// means every concurrent 401 waits on and gets the exact same outcome
// as the single real refresh request. (Same fix as household/frontend's
// own auth.js — this exact bug, independently found there first.)
let refreshInFlight = null;

/**
 * Used by api.js on a 401 for an Authentik-sourced session — tries to
 * get a new access token with the stored refresh token before giving up
 * and sending the user back to login. Returns true on success. Safe to
 * call concurrently — see refreshInFlight above.
 */
export async function tryRefreshAuthentikToken() {
  if (refreshInFlight) return refreshInFlight;
  refreshInFlight = _doRefresh();
  try {
    return await refreshInFlight;
  } finally {
    refreshInFlight = null;
  }
}

async function _doRefresh() {
  const refreshToken = localStorage.getItem(REFRESH_TOKEN_KEY);
  if (!refreshToken) return false;

  try {
    const config = await getAuthentikConfig();
    const body = new URLSearchParams({
      grant_type: "refresh_token",
      refresh_token: refreshToken,
      client_id: config.client_id,
      // Repeated explicitly, matching the original /authorize request —
      // without this, some Authentik setups don't reliably re-apply a
      // custom scope's claim mapping to the refreshed access token.
      scope: config.scope,
    });
    const resp = await fetchWithTimeout(config.token_url, {
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
  // Read before clearToken() wipes it — stashed at login time (see
  // setSession/handleAuthentikCallback) specifically so logout never
  // needs a fetch for this: it has to work instantly and can't be
  // allowed to hang just because the auth service (or Authentik
  // itself) happens to be unreachable right now.
  const endSessionUrl = localStorage.getItem(END_SESSION_URL_KEY);
  clearToken();

  if (source === "authentik" && endSessionUrl) {
    const params = new URLSearchParams({ post_logout_redirect_uri: window.location.origin + "/" });
    if (idToken) params.set("id_token_hint", idToken);
    _navigate(`${endSessionUrl}?${params}`);
    return; // browser is navigating away — nothing left to do here
  }
  // A full reload (same _navigate indirection used above), not
  // router.js's navigate() — see api.js's 401 handler for why this
  // low-level module never imports the router.
  _navigate("/login");
}
