import { getToken, clearToken, getAuthSource, tryRefreshAuthentikToken } from "./auth.js";
import { showToast } from "./toast.js";
import { t } from "./i18n.js";

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
    if (!silent) showToast(t("api.network_error"), "danger");
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
    throw new ApiError(t("api.session_expired"), 401);
  }

  if (resp.status === 204) {
    return null;
  }

  const contentType = resp.headers.get("content-type") || "";
  const data = contentType.includes("application/json") ? await resp.json() : await resp.blob();

  if (!resp.ok) {
    // `data.detail` is a backend-produced message, not run through this
    // frontend's own t() — it's plain English either way for now (same
    // gap household/frontend's own i18n round left in its backend's
    // HTTPException details), so it's shown as-is rather than mixed
    // with a mistranslated fallback.
    const message = (data && data.detail) || t("api.request_failed");
    if (!silent) {
      if (resp.status === 403) {
        showToast(t("api.forbidden"), "warning");
      } else {
        showToast(typeof message === "string" ? message : t("api.request_failed"), "danger");
      }
    }
    throw new ApiError(typeof message === "string" ? message : t("api.request_failed"), resp.status);
  }

  return data;
}

export const api = {
  get: (url) => request(url),
  post: (url, body) => request(url, { method: "POST", body: body instanceof FormData ? body : JSON.stringify(body) }),
  patch: (url, body) => request(url, { method: "PATCH", body: JSON.stringify(body) }),
  del: (url) => request(url, { method: "DELETE" }),
  postForm: (url, formData) => request(url, { method: "POST", body: formData }),
};

/**
 * <img src="..."> can't send an Authorization header, and the image
 * endpoints require one (same role-gating as everything else) — so we
 * fetch the image ourselves with auth and hand back a blob: object URL
 * for the <img> to point at instead. Returns null on failure (missing
 * image, 403, etc.) rather than throwing/toasting — a thumbnail quietly
 * falling back to the placeholder icon is better UX than an error toast
 * every time a card renders.
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
 * Call after uploading a new photo for an item — the API URL doesn't
 * change on re-upload, so without this the cache would keep serving the
 * previous image's blob.
 */
export function invalidateImageUrl(url) {
  const cached = objectUrlCache.get(url);
  if (cached) {
    URL.revokeObjectURL(cached);
    objectUrlCache.delete(url);
  }
}

export { ApiError };
