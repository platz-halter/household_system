import { THEMES, getStoredTheme, applyTheme } from "./theme.js";
import { getCurrentUserInfo, logout } from "./auth.js";
import { icons } from "./icons.js";
import { showConfirmDialog } from "./confirmDialog.js";
import { APP_VERSION } from "./version.js";
import { t, getLocale, setLocale, supportedLocales } from "./i18n.js";

// Each language's own name for itself, shown regardless of the current
// UI language — the convention almost every app's language switcher
// uses (an English speaker looking for German should see "Deutsch," not
// a translated "German" they might not recognize as the same word).
// Deliberately NOT run through t(): these name the language itself, not
// UI text to translate.
const LOCALE_NATIVE_NAMES = { en: "English", de: "Deutsch" };

// `user.role`/`user.source` are raw values straight from the decoded
// token ("admin"/"user"/"viewer", "local"/"authentik") — displaying
// them as-is would leave two ordinary English words sitting in an
// otherwise-translated account card. "Authentik" itself is a brand
// name and stays as-is either way.
const ROLE_LABEL_KEYS = { admin: "settings.role_admin", user: "settings.role_user", viewer: "settings.role_viewer" };
const SOURCE_LABEL_KEYS = { local: "settings.source_local", authentik: "settings.source_authentik" };

export function renderSettings(container) {
  const user = getCurrentUserInfo() || {};
  const currentTheme = getStoredTheme();
  const initial = (user.subject || "?").slice(0, 1).toUpperCase();
  const roleLabel = user.role && ROLE_LABEL_KEYS[user.role] ? t(ROLE_LABEL_KEYS[user.role]) : t("settings.unknown_role");
  const sourceLabel = user.source && SOURCE_LABEL_KEYS[user.source] ? t(SOURCE_LABEL_KEYS[user.source]) : "";

  container.innerHTML = `
    <div class="page">
      <div class="settings-section">
        <h3>${escapeHtml(t("settings.account"))}</h3>
        <div class="user-info-card">
          <div class="user-avatar">${escapeHtml(initial)}</div>
          <div>
            <div style="font-weight:600;">${escapeHtml(user.subject || t("settings.unknown_user"))}</div>
            <div class="muted" style="font-size: var(--font-size-sm);">
              ${escapeHtml(roleLabel)} · ${escapeHtml(sourceLabel)}
            </div>
          </div>
        </div>
      </div>

      <div class="settings-section">
        <h3>${escapeHtml(t("settings.storage_heading"))}</h3>
        <a href="/rooms" class="btn btn-block">${icons.box}<span>${escapeHtml(t("settings.manage_rooms"))}</span></a>
      </div>

      <div class="settings-section">
        <h3>${escapeHtml(t("settings.theme"))}</h3>
        <div id="theme-options"></div>
      </div>

      <div class="settings-section">
        <h3>${escapeHtml(t("settings.language"))}</h3>
        <p class="muted" style="font-size: var(--font-size-xs); margin-top: -4px;">${escapeHtml(t("settings.language_desc"))}</p>
        <div id="language-root"></div>
      </div>

      <div class="settings-section">
        <button class="btn btn-block" id="logout-btn">${icons.logout}<span>${escapeHtml(t("settings.logout"))}</span></button>
      </div>

      <p class="muted" style="font-size: var(--font-size-xs); text-align: center;">${escapeHtml(t("settings.version", { version: APP_VERSION }))}</p>
    </div>
  `;

  const themeRoot = container.querySelector("#theme-options");
  THEMES().forEach((theme) => {
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

  renderLanguageSection(container);

  container.querySelector("#logout-btn").addEventListener("click", async () => {
    const ok = await showConfirmDialog({
      title: t("settings.logout_confirm_title"),
      message: t("settings.logout_confirm_message"),
      confirmLabel: t("settings.logout"),
    });
    if (ok) logout();
  });
}

// No backend to persist this against at all (see i18n.js's own module
// docstring — storage has no per-service user table) — a plain
// localStorage choice, same storage model the theme picker above
// already uses. Changing it reloads the page, same as a theme change
// effectively does via applyTheme's own immediate DOM update, except
// a language change has no in-place re-render path so a real reload is
// the only way to apply it everywhere at once.
function renderLanguageSection(container) {
  const root = container.querySelector("#language-root");
  if (!root) return;
  const current = getLocale();
  root.innerHTML = `
    <select class="select" id="language-select">
      ${supportedLocales()
        .map((id) => `<option value="${id}" ${id === current ? "selected" : ""}>${escapeHtml(LOCALE_NATIVE_NAMES[id] || id)}</option>`)
        .join("")}
    </select>
  `;

  root.querySelector("#language-select").addEventListener("change", (e) => {
    const next = e.target.value;
    if (next === current) return;
    const persisted = setLocale(next);
    if (!persisted) {
      e.target.value = current; // private browsing / blocked storage — don't reload into a value we can't re-detect next load
      return;
    }
    window.location.reload();
  });
}

function escapeHtml(str) {
  return String(str ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
}
