import { isAuthenticated, getCurrentUserInfo } from "./auth.js";
import { renderLogin } from "./login.js";
import { renderHome } from "./home.js";
import { renderBoard } from "./board.js";
import { renderStats } from "./stats.js";
import { renderTasks } from "./tasks.js";
import { renderSettings } from "./settings.js";
import { renderAdmin } from "./admin.js";

const routes = {
  "/login": { render: renderLogin, requiresAuth: false, chrome: false },
  "/home": { render: renderHome, requiresAuth: true, chrome: true },
  "/board": { render: renderBoard, requiresAuth: true, chrome: true },
  "/stats": { render: renderStats, requiresAuth: true, chrome: true },
  "/tasks": { render: renderTasks, requiresAuth: true, chrome: true },
  "/settings": { render: renderSettings, requiresAuth: true, chrome: true },
  "/admin": { render: renderAdmin, requiresAuth: true, chrome: true, adminOnly: true },
};

function currentPath() {
  const hash = window.location.hash.replace(/^#/, "");
  return hash || "/home";
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
  const route = routes[path] || routes["/home"];

  if (route.requiresAuth && !isAuthenticated()) {
    window.location.hash = "#/login";
    return;
  }
  if (path === "/login" && isAuthenticated()) {
    window.location.hash = "#/home";
    return;
  }
  if (route.adminOnly) {
    const info = getCurrentUserInfo();
    if (!info || info.role !== "admin") {
      window.location.hash = "#/settings";
      return;
    }
  }

  updateChrome(path, route.chrome);
  const app = document.getElementById("app");
  await route.render(app);
}

export function startRouter() {
  window.addEventListener("hashchange", handleRoute);
  handleRoute();
}
