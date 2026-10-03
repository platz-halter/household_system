import { isAuthenticated, getCurrentUserInfo } from "./auth.js";
import { renderLogin } from "./login.js";
import { renderHome } from "./home.js";
import { renderBoard } from "./board.js";
import { renderStats } from "./stats.js";
import { renderTasks } from "./tasks.js";
import { renderSettings } from "./settings.js";
import { renderAdmin } from "./admin.js";

const DEFAULT_PATH = "/home";

const routes = {
  "/login": { render: renderLogin, requiresAuth: false, chrome: false },
  "/home": { render: renderHome, requiresAuth: true, chrome: true },
  "/board": { render: renderBoard, requiresAuth: true, chrome: true },
  "/stats": { render: renderStats, requiresAuth: true, chrome: true },
  "/tasks": { render: renderTasks, requiresAuth: true, chrome: true },
  "/settings": { render: renderSettings, requiresAuth: true, chrome: true },
  "/admin": { render: renderAdmin, requiresAuth: true, chrome: true, adminOnly: true },
};

// Strips a trailing slash (except the bare root) so "/board/" and
// "/board" resolve to the same route — easy to end up with a trailing
// slash from a typed URL, an old bookmark, or browser autocomplete.
function normalizePath(pathname) {
  if (pathname.length > 1 && pathname.endsWith("/")) {
    return pathname.slice(0, -1);
  }
  return pathname;
}

function currentPath() {
  const path = normalizePath(window.location.pathname);
  return path === "/" ? DEFAULT_PATH : path;
}

/**
 * The one place that changes the URL for an in-app navigation. `replace`
 * is for corrective redirects (not-logged-in, already-logged-in,
 * admin-only) that shouldn't leave a back-button entry pointing at the
 * page that bounced the user away; omit it for a real, user-initiated
 * navigation.
 */
export function navigate(path, { replace = false } = {}) {
  if (replace) {
    window.history.replaceState({}, "", path);
  } else {
    window.history.pushState({}, "", path);
  }
  handleRoute();
}

function updateChrome(path, chrome) {
  const topbar = document.getElementById("topbar");
  const bottomNav = document.getElementById("bottom-nav");
  const app = document.getElementById("app");

  topbar.classList.toggle("hidden", !chrome);
  bottomNav.classList.toggle("hidden", !chrome);
  app.style.paddingTop = chrome ? "" : "0";
  app.style.paddingBottom = chrome ? "" : "0";

  bottomNav.querySelectorAll("a").forEach((a) => {
    a.classList.toggle("active", `/${a.dataset.route}` === path);
  });
}

async function handleRoute() {
  const path = currentPath();
  const route = routes[path] || routes[DEFAULT_PATH];

  if (route.requiresAuth && !isAuthenticated()) {
    navigate("/login", { replace: true });
    return;
  }
  if (path === "/login" && isAuthenticated()) {
    navigate(DEFAULT_PATH, { replace: true });
    return;
  }
  if (route.adminOnly) {
    const info = getCurrentUserInfo();
    if (!info || info.role !== "admin") {
      navigate("/settings", { replace: true });
      return;
    }
  }

  updateChrome(path, route.chrome);
  const app = document.getElementById("app");
  await route.render(app);
}

// Intercepts a click on any internal <a href="/..."> so it's a client-side
// navigation (no full page reload/server round-trip) — the standard
// no-framework SPA pattern. Deliberately narrow about what it takes:
// only a plain left-click on a same-origin link whose path is one of
// THIS app's known routes. Anything else (an API link, a synthetic
// download anchor like admin's PDF-export `<a download>`, a blob: URL,
// a modified click meant to open a new tab) is left to the browser's
// default handling untouched.
function onDocumentClick(event) {
  if (event.defaultPrevented || event.button !== 0) return;
  if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;

  const anchor = event.target.closest("a");
  if (!anchor || anchor.target || anchor.hasAttribute("download")) return;

  let url;
  try {
    url = new URL(anchor.href, window.location.href);
  } catch {
    return;
  }
  if (url.origin !== window.location.origin) return;

  const path = normalizePath(url.pathname);
  if (path !== "/" && !(path in routes)) return;

  event.preventDefault();
  const target = path === "/" ? DEFAULT_PATH : path;
  if (target === currentPath()) return;
  navigate(target);
}

export function startRouter() {
  window.addEventListener("popstate", handleRoute);
  document.addEventListener("click", onDocumentClick);
  handleRoute();
}
