import { THEMES, getStoredTheme, applyTheme } from "./theme.js";
import { decodeToken, logout } from "./auth.js";
import { icons } from "./icons.js";

export function renderSettings(container) {
  const user = decodeToken() || {};
  const currentTheme = getStoredTheme();
  const initial = (user.sub || "?").slice(0, 1).toUpperCase();

  container.innerHTML = `
    <div class="page">
      <div class="settings-section">
        <h3>Account</h3>
        <div class="user-info-card">
          <div class="user-avatar">${escapeHtml(initial)}</div>
          <div>
            <div style="font-weight:600;">${escapeHtml(user.sub || "Unknown user")}</div>
            <div class="muted" style="font-size: var(--font-size-sm); text-transform: capitalize;">
              ${escapeHtml(user.role || "unknown role")} · ${escapeHtml(user.source || "")}
            </div>
          </div>
        </div>
      </div>

      <div class="settings-section">
        <h3>Theme</h3>
        <div id="theme-options"></div>
      </div>

      <div class="settings-section">
        <button class="btn btn-block" id="logout-btn">${icons.logout}<span>Log out</span></button>
      </div>
    </div>
  `;

  const themeRoot = container.querySelector("#theme-options");
  THEMES.forEach((theme) => {
    const option = document.createElement("div");
    option.className = "theme-option";
    option.setAttribute("role", "radio");
    option.setAttribute("aria-checked", String(theme.id === currentTheme));
    option.innerHTML = `
      <span>${escapeHtml(theme.label)}</span>
      <span class="theme-swatch" data-theme-preview="${theme.id}"></span>
    `;
    option.addEventListener("click", () => {
      applyTheme(theme.id);
      themeRoot.querySelectorAll(".theme-option").forEach((el) => el.setAttribute("aria-checked", "false"));
      option.setAttribute("aria-checked", "true");
    });
    themeRoot.appendChild(option);
  });

  // Give each swatch its theme's actual background/text colors so it
  // previews correctly without needing to switch to see it.
  themeRoot.querySelectorAll("[data-theme-preview]").forEach((swatch) => {
    const id = swatch.getAttribute("data-theme-preview");
    swatch.style.background = id === "dark" ? "#0a0a0a" : "#ffffff";
    swatch.style.border = "1px solid var(--color-border)";
  });

  container.querySelector("#logout-btn").addEventListener("click", () => {
    if (confirm("Log out?")) logout();
  });
}

function escapeHtml(str) {
  return String(str ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
}
