const ROOT_ID = "toast-root";
const DEFAULT_DURATION_MS = 4000;

export function showToast(message, type = "info", duration = DEFAULT_DURATION_MS) {
  const root = document.getElementById(ROOT_ID);
  if (!root) return;

  const el = document.createElement("div");
  el.className = `toast toast-${type}`;
  el.setAttribute("role", "status");
  el.textContent = message;
  root.appendChild(el);

  setTimeout(() => {
    el.remove();
  }, duration);
}
