import { getToken, clearToken } from "./auth.js";
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
    clearToken();
    window.location.hash = "#/login";
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
