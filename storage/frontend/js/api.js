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

  let resp;
  try {
    resp = await fetch(url, { ...options, headers });
  } catch (err) {
    showToast("Network error — is the server reachable?", "danger");
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
    if (resp.status === 403) {
      showToast("You don't have permission to do that", "warning");
    } else {
      showToast(typeof message === "string" ? message : "Request failed", "danger");
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

export { ApiError };
