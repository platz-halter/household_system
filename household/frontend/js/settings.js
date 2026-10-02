import { CONFIG } from "./config.js";
import { api, fetchImageUrl, invalidateImageUrl } from "./api.js";
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
          <div class="user-avatar" id="account-avatar">${escapeHtml(initial)}</div>
          <div>
            <div style="font-weight:600;">${escapeHtml(user.subject || "Unknown user")}</div>
            <div class="muted" style="font-size: var(--font-size-sm); text-transform: capitalize;">
              ${escapeHtml(user.role || "unknown role")} · ${escapeHtml(user.source || "")}
            </div>
          </div>
        </div>
        ${
          writable
            ? `<div class="row" style="margin-top: var(--space-3);">
                 <label class="btn" for="avatar-file-input" style="cursor: pointer;">${icons.camera}<span>Change photo</span></label>
                 <input type="file" id="avatar-file-input" accept="image/png,image/jpeg,image/webp" class="sr-only" />
                 <button class="btn" id="avatar-remove-btn">Remove photo</button>
               </div>`
            : ""
        }
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

  await loadAvatar(container, writable);
  await loadBreakMode(container, writable);
  await loadPushSection(container, writable);
  await loadHouseholdSettings(container);
}

async function loadAvatar(container, writable) {
  const avatarEl = container.querySelector("#account-avatar");
  if (!avatarEl) return;

  let me;
  try {
    me = await api.get(`${HB}/me`);
  } catch {
    return; // leave the initials fallback in place
  }
  const photoUrl = `${HB}/users/${me.id}/photo`;

  const applyPhoto = async () => {
    if (!me.image_path) return;
    const objectUrl = await fetchImageUrl(photoUrl);
    if (!objectUrl) return;
    avatarEl.innerHTML = `<img src="${objectUrl}" alt="" style="width:100%; height:100%; object-fit:cover;" />`;
  };
  await applyPhoto();

  if (!writable) return;

  container.querySelector("#avatar-file-input").addEventListener("change", async (e) => {
    const file = e.target.files[0];
    if (!file) return;
    const fd = new FormData();
    fd.append("file", file);
    try {
      me = await api.postForm(`${HB}/me/photo`, fd);
      invalidateImageUrl(photoUrl);
      await applyPhoto();
      showToast("Photo updated", "success");
    } catch {
      /* api.js already showed a toast */
    } finally {
      e.target.value = "";
    }
  });

  container.querySelector("#avatar-remove-btn").addEventListener("click", async () => {
    try {
      me = await api.del(`${HB}/me/photo`);
      invalidateImageUrl(photoUrl);
      avatarEl.innerHTML = escapeHtml((getCurrentUserInfo()?.subject || "?").slice(0, 1).toUpperCase());
      showToast("Photo removed", "success");
    } catch {
      /* api.js already showed a toast */
    }
  });
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
        const ok = await showConfirmDialog(
          next
            ? {
                title: "Go on break?",
                message: "You'll be hidden from the leaderboard and new task assignments until you turn this off again.",
                confirmLabel: "Go on break",
              }
            : {
                title: "End your break?",
                message: "You'll reappear on the leaderboard and be eligible for task assignments again.",
                confirmLabel: "End break",
              }
        );
        if (!ok) return;
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
    ${
      subscription && writable
        ? `<button class="btn" id="push-test-btn" style="margin-top: var(--space-2);">Send test notification</button>`
        : ""
    }
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
      showToast(turningOn ? "Notifications on" : "Notifications off", "success");
      await loadPushSection(container, writable); // re-render: the test button only shows while subscribed
    } catch (err) {
      showToast(err.message || "Couldn't change notification settings", "danger");
    } finally {
      btn.disabled = false;
    }
  });

  const testBtn = container.querySelector("#push-test-btn");
  if (testBtn) {
    testBtn.addEventListener("click", async () => {
      testBtn.disabled = true;
      try {
        const result = await api.post(`${HB}/push/test`);
        if (result.sent > 0) {
          showToast(`Sent — check this device for a notification`, "success");
        } else {
          showToast("Nothing was delivered — the subscription may be stale; try turning notifications off and on again", "warning");
        }
      } catch {
        /* api.js already showed a toast */
      } finally {
        testBtn.disabled = false;
      }
    });
  }
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
