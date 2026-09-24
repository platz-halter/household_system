import { CONFIG } from "./config.js";

const TOKEN_KEY = "hs_token";

export function getToken() {
  return localStorage.getItem(TOKEN_KEY);
}

function setToken(token) {
  localStorage.setItem(TOKEN_KEY, token);
}

export function clearToken() {
  localStorage.removeItem(TOKEN_KEY);
}

export function isAuthenticated() {
  return Boolean(getToken());
}

/**
 * Decodes the JWT payload for DISPLAY purposes only (username, role in
 * the Settings page). This does not verify the signature — the backend
 * is the only thing that actually trusts this token. Never make an
 * authorization decision in the frontend based on this.
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
  setToken(data.access_token);
}

export function logout() {
  clearToken();
  window.location.hash = "#/login";
}
