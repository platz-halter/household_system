import { CONFIG } from "./config.js";
import { api } from "./api.js";
import { THEMES, getStoredTheme, applyTheme } from "./theme.js";
import { getCurrentUserInfo, logout } from "./auth.js";
import { icons } from "./icons.js";
import { showToast } from "./toast.js";
import { showConfirmDialog } from "./confirmDialog.js";
import { escapeHtml } from "./util.js";
import { isPushSupported, getPushSubscription, subscribeToPush, unsubscribeFromPush } from "./push.js";

const HB = CONFIG.HOUSEHOLD_BASE;

function canWrite() {
  const info = getCurrentUserInfo();
  return info && (info.role === "admin" || info.role === "user");
}

function isAdmin() {
  const info = getCurrentUserInfo();
  return Boolean(info && info.role === "admin");
}

export async function renderSettings(container) {
  const user = getCurrentUserInfo() || {};
  const currentTheme = getStoredTheme();
  const writable = canWrite();
  const admin = isAdmin();
  const initial = (user.subject || "?").slice(0, 1).toUpperCase();

  container.innerHTML = `
    <div class="page">
      <div class="settings-section">
        <h3>Account</h3>
        <div class="user-info-card">
          <div class="user-avatar">${escapeHtml(initial)}</div>
          <div>
            <div style="font-weight:600;">${escapeHtml(user.subject || "Unknown user")}</div>
            <div class="muted" style="font-size: var(--font-size-sm); text-transform: capitalize;">
              ${escapeHtml(user.role || "unknown role")} · ${escapeHtml(user.source || "")}
            </div>
          </div>
        </div>
      </div>

      <div class="settings-section">
        <h3>Break mode</h3>
        <div id="break-mode-root"><div class="skeleton" style="height: 56px;"></div></div>
      </div>

      <div class="settings-section">
        <h3>Notifications</h3>
        <div id="push-root"><div class="skeleton" style="height: 56px;"></div></div>
      </div>

      <div class="settings-section">
        <h3>Household</h3>
        <div id="household-settings-root"><div class="skeleton" style="height: 56px;"></div></div>
      </div>

      ${
        admin
          ? `<div class="settings-section">
               <h3>Admin</h3>
               <a href="#/admin" class="list-row">
                 <div class="list-row-body">
                   <div class="list-row-title">Admin panel</div>
                   <div class="list-row-meta"><span>Settings only admins can change</span></div>
                 </div>
                 ${icons.chevronRight}
               </a>
             </div>`
          : ""
      }

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

  themeRoot.querySelectorAll("[data-theme-preview]").forEach((swatch) => {
    const id = swatch.getAttribute("data-theme-preview");
    swatch.style.background = id === "dark" ? "#0a0a0a" : "#ffffff";
    swatch.style.border = "1px solid var(--color-border)";
  });

  container.querySelector("#logout-btn").addEventListener("click", async () => {
    const ok = await showConfirmDialog({ title: "Log out", message: "Are you sure you want to log out?", confirmLabel: "Log out" });
    if (ok) logout();
  });

  await loadBreakMode(container, writable);
  await loadPushSection(container, writable);
  await loadHouseholdSettings(container);
}

async function loadBreakMode(container, writable) {
  const root = container.querySelector("#break-mode-root");
  if (!root) return;
  try {
    const me = await api.get(`${HB}/me`);
    root.innerHTML = `
      <div class="switch-row">
        <div class="switch-row-text">
          <span>I'm on a break</span>
          <span class="muted">Hides you from the leaderboard and task assignments</span>
        </div>
        <button class="switch${me.on_break ? " on" : ""}" id="break-switch" role="switch" aria-checked="${me.on_break}" ${writable ? "" : "disabled"}></button>
      </div>
    `;
    if (writable) {
      container.querySelector("#break-switch").addEventListener("click", async (e) => {
        const btn = e.currentTarget;
        const next = !btn.classList.contains("on");
        try {
          await api.patch(`${HB}/me`, { on_break: next });
          btn.classList.toggle("on", next);
          btn.setAttribute("aria-checked", String(next));
          showToast(next ? "You're now on break" : "Welcome back", "success");
        } catch {
          /* api.js already showed a toast */
        }
      });
    }
  } catch {
    root.innerHTML = `<div class="empty-state">Couldn't load break status</div>`;
  }
}

async function loadPushSection(container, writable) {
  const root = container.querySelector("#push-root");
  if (!root) return;

  if (!isPushSupported()) {
    root.innerHTML = `<div class="muted" style="font-size: var(--font-size-sm);">Not supported in this browser</div>`;
    return;
  }

  const subscription = await getPushSubscription();
  root.innerHTML = `
    <div class="switch-row">
      <div class="switch-row-text">
        <span>Push notifications on this device</span>
        <span class="muted">Chore requests addressed to you, and weekly reminders</span>
      </div>
      <button class="switch${subscription ? " on" : ""}" id="push-switch" role="switch" aria-checked="${Boolean(subscription)}" ${writable ? "" : "disabled"}></button>
    </div>
  `;

  if (!writable) return;

  container.querySelector("#push-switch").addEventListener("click", async (e) => {
    const btn = e.currentTarget;
    const turningOn = !btn.classList.contains("on");
    btn.disabled = true;
    try {
      if (turningOn) {
        await subscribeToPush();
      } else {
        await unsubscribeFromPush();
      }
      btn.classList.toggle("on", turningOn);
      btn.setAttribute("aria-checked", String(turningOn));
      showToast(turningOn ? "Notifications on" : "Notifications off", "success");
    } catch (err) {
      showToast(err.message || "Couldn't change notification settings", "danger");
    } finally {
      btn.disabled = false;
    }
  });
}

// Read-only for everyone here — only the Admin panel (#/admin) can change
// it, which is why there's no input/save button in this section anymore.
async function loadHouseholdSettings(container) {
  const root = container.querySelector("#household-settings-root");
  if (!root) return;
  try {
    const settings = await api.get(`${HB}/settings`);
    root.innerHTML = `
      <div class="row-between">
        <span class="muted">Weekly points goal</span>
        <span>${settings.weekly_points_goal ?? "Not set"}</span>
      </div>
    `;
  } catch {
    root.innerHTML = `<div class="empty-state">Couldn't load household settings</div>`;
  }
}
