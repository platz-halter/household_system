import { isAuthenticated } from "./auth.js";
import { renderLogin } from "./login.js";
import { renderOverview } from "./overview.js";
import { renderSettings } from "./settings.js";

const routes = {
  "/login": { render: renderLogin, requiresAuth: false, chrome: false },
  "/overview": { render: renderOverview, requiresAuth: true, chrome: true },
  "/settings": { render: renderSettings, requiresAuth: true, chrome: true },
};

function currentPath() {
  const hash = window.location.hash.replace(/^#/, "");
  return hash || "/overview";
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
  const route = routes[path] || routes["/overview"];

  if (route.requiresAuth && !isAuthenticated()) {
    window.location.hash = "#/login";
    return;
  }
  if (path === "/login" && isAuthenticated()) {
    window.location.hash = "#/overview";
    return;
  }

  updateChrome(path, route.chrome);
  const app = document.getElementById("app");
  await route.render(app);
}

export function startRouter() {
  window.addEventListener("hashchange", handleRoute);
  handleRoute();
}
