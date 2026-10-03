import { getToken, clearToken, getAuthSource, tryRefreshAuthentikToken } from "./auth.js";
import { showToast } from "./toast.js";

class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.status = status;
  }
}

async function request(url, options = {}) {
  const token = getToken();
  const headers = { ...(options.headers || {}) };
  if (token) headers.Authorization = `Bearer ${token}`;

  const isFormData = options.body instanceof FormData;
  if (!isFormData && options.body && !headers["Content-Type"]) {
    headers["Content-Type"] = "application/json";
  }

  const silent = options.silent;

  let resp;
  try {
    resp = await fetch(url, { ...options, headers });
  } catch (err) {
    if (!silent) showToast("Network error — is the server reachable?", "danger");
    throw new ApiError(err.message, 0);
  }

  if (resp.status === 401) {
    // Access tokens (especially Authentik's) can be short-lived — try a
    // silent refresh and retry once before treating this as a real
    // logout. Only attempted once per original call (_retried guards
    // against a refresh loop if the new token is somehow also rejected).
    if (!options._retried && getAuthSource() === "authentik") {
      const refreshed = await tryRefreshAuthentikToken();
      if (refreshed) {
        return request(url, { ...options, _retried: true });
      }
    }
    clearToken();
    // A full reload, not router.js's navigate() — this is a low-level
    // module nearly every page imports; importing the router back into
    // it would create a router -> page -> api -> router cycle. A hard
    // reload also guarantees any module-level cache gets dropped along
    // with the now-cleared token.
    window.location.assign("/login");
    throw new ApiError("Session expired", 401);
  }

  if (resp.status === 204) {
    return null;
  }

  const contentType = resp.headers.get("content-type") || "";
  const data = contentType.includes("application/json") ? await resp.json() : await resp.blob();

  if (!resp.ok) {
    const message = (data && data.detail) || `Request failed (${resp.status})`;
    if (!silent) {
      if (resp.status === 403) {
        showToast("You don't have permission to do that", "warning");
      } else {
        showToast(typeof message === "string" ? message : "Request failed", "danger");
      }
    }
    throw new ApiError(typeof message === "string" ? message : "Request failed", resp.status);
  }

  return data;
}

// The optional 3rd `options` arg (currently just `{ silent: true }`) lets
// a caller suppress the automatic error toast and show its own instead —
// needed where the generic "(403) you don't have permission" toast would
// be actively misleading, e.g. the Authentik admin panel's reauth check,
// which 403s for a WRONG REAUTH PASSWORD even though the caller already
// has a perfectly valid admin bearer token.
export const api = {
  get: (url) => request(url),
  post: (url, body, options) =>
    request(url, { method: "POST", body: body !== undefined ? JSON.stringify(body) : undefined, ...options }),
  patch: (url, body) => request(url, { method: "PATCH", body: JSON.stringify(body) }),
  put: (url, body, options) => request(url, { method: "PUT", body: JSON.stringify(body), ...options }),
  del: (url) => request(url, { method: "DELETE" }),
  postForm: (url, formData) => request(url, { method: "POST", body: formData }),
};

/**
 * <img src="..."> can't send an Authorization header, and photo endpoints
 * require one (same role-gating as everything else) — so we fetch the
 * image ourselves with auth and hand back a blob: object URL for the
 * <img> to point at instead. Returns null on failure (no photo set, 403,
 * etc.) rather than throwing/toasting — an avatar quietly falling back to
 * initials is better UX than an error toast every time one renders.
 */
const objectUrlCache = new Map(); // api url -> blob: url, avoids re-fetching the same image repeatedly

export async function fetchImageUrl(url) {
  if (objectUrlCache.has(url)) return objectUrlCache.get(url);
  try {
    const blob = await request(url, { silent: true });
    const objectUrl = URL.createObjectURL(blob);
    objectUrlCache.set(url, objectUrl);
    return objectUrl;
  } catch {
    return null;
  }
}

/**
 * Call after uploading a new photo — the API URL doesn't change on
 * re-upload, so without this the cache would keep serving the previous
 * photo's blob.
 */
export function invalidateImageUrl(url) {
  const cached = objectUrlCache.get(url);
  if (cached) {
    URL.revokeObjectURL(cached);
    objectUrlCache.delete(url);
  }
}

export { ApiError };
