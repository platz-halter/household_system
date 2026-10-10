import { CONFIG } from "./config.js";
import { api, fetchImageUrl, invalidateImageUrl } from "./api.js";
import { THEMES, getStoredTheme, applyTheme } from "./theme.js";
import { getCurrentUserInfo, logout } from "./auth.js";
import { icons } from "./icons.js";
import { showToast } from "./toast.js";
import { showConfirmDialog } from "./confirmDialog.js";
import { escapeHtml, showSkeletonAfterDelay } from "./util.js";
import { isPushSupported, getPushSubscription, subscribeToPush, unsubscribeFromPush } from "./push.js";
import { APP_VERSION } from "./version.js";
import { t, getLocale, setLocale, supportedLocales } from "./i18n.js";

const HB = CONFIG.HOUSEHOLD_BASE;

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
// name and stays as-is either way. (Same fix as storage/frontend's own
// settings.js — this exact gap was caught there first, by an
// independent audit, then mirrored back here for consistency.)
const ROLE_LABEL_KEYS = { admin: "settings.role_admin", user: "settings.role_user", viewer: "settings.role_viewer" };
const SOURCE_LABEL_KEYS = { local: "settings.source_local", authentik: "settings.source_authentik" };

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
  const roleLabel = user.role && ROLE_LABEL_KEYS[user.role] ? t(ROLE_LABEL_KEYS[user.role]) : t("settings.unknown_role");
  const sourceLabel = user.source && SOURCE_LABEL_KEYS[user.source] ? t(SOURCE_LABEL_KEYS[user.source]) : "";

  container.innerHTML = `
    <div class="page">
      <div class="settings-section">
        <h3>${escapeHtml(t("settings.account"))}</h3>
        <div class="user-info-card">
          <div class="user-avatar" id="account-avatar">${escapeHtml(initial)}</div>
          <div>
            <div style="font-weight:600;">${escapeHtml(user.subject || t("settings.unknown_user"))}</div>
            <div class="muted" style="font-size: var(--font-size-sm);">
              ${escapeHtml(roleLabel)} · ${escapeHtml(sourceLabel)}
            </div>
          </div>
        </div>
        ${
          writable
            ? `<div class="row" style="margin-top: var(--space-3);">
                 <label class="btn" for="avatar-file-input" style="cursor: pointer;">${icons.camera}<span>${escapeHtml(t("settings.change_photo"))}</span></label>
                 <input type="file" id="avatar-file-input" accept="image/png,image/jpeg,image/webp" class="sr-only" />
                 <button class="btn" id="avatar-remove-btn">${escapeHtml(t("settings.remove_photo"))}</button>
               </div>`
            : ""
        }
      </div>

      <div class="settings-section">
        <h3>${escapeHtml(t("settings.break_mode"))}</h3>
        <div id="break-mode-root"></div>
      </div>

      <div class="settings-section">
        <h3>${escapeHtml(t("settings.notifications"))}</h3>
        <div id="push-root"></div>
      </div>

      <div class="settings-section">
        <h3>${escapeHtml(t("settings.household"))}</h3>
        <div id="household-settings-root"></div>
      </div>

      ${
        admin
          ? `<div class="settings-section">
               <h3>${escapeHtml(t("settings.admin"))}</h3>
               <a href="/admin" class="list-row">
                 <div class="list-row-body">
                   <div class="list-row-title">${escapeHtml(t("settings.admin_panel"))}</div>
                   <div class="list-row-meta"><span>${escapeHtml(t("settings.admin_panel_desc"))}</span></div>
                 </div>
                 ${icons.chevronRight}
               </a>
             </div>`
          : ""
      }

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

  themeRoot.querySelectorAll("[data-theme-preview]").forEach((swatch) => {
    const id = swatch.getAttribute("data-theme-preview");
    swatch.style.background = id === "dark" ? "#0a0a0a" : "#ffffff";
    swatch.style.border = "1px solid var(--color-border)";
  });

  container.querySelector("#logout-btn").addEventListener("click", async () => {
    const ok = await showConfirmDialog({
      title: t("settings.logout_confirm_title"),
      message: t("settings.logout_confirm_message"),
      confirmLabel: t("settings.logout"),
    });
    if (ok) logout();
  });

  renderLanguageSection(container, writable);
  await loadAvatar(container, writable);
  await loadBreakMode(container, writable);
  await loadPushSection(container, writable);
  await loadHouseholdSettings(container);
}

// Read-only for a viewer — see main.PATCH /me/language's own docstring
// for why this is still can_read-gated rather than folded into the
// broader can_write-gated PATCH /me: a viewer has no business touching
// display_name/on_break, but switching their own UI language is
// harmless either way.
function renderLanguageSection(container, writable) {
  const root = container.querySelector("#language-root");
  if (!root) return;
  const current = getLocale();
  root.innerHTML = `
    <select class="select" id="language-select" ${writable ? "" : "disabled"}>
      ${supportedLocales()
        .map((id) => `<option value="${id}" ${id === current ? "selected" : ""}>${escapeHtml(LOCALE_NATIVE_NAMES[id] || id)}</option>`)
        .join("")}
    </select>
  `;
  if (!writable) return;

  root.querySelector("#language-select").addEventListener("change", async (e) => {
    const next = e.target.value;
    if (next === current) return;
    try {
      await api.patch(`${HB}/me/language`, { preferred_language: next });
    } catch {
      e.target.value = current; // api.js already showed a toast
      return;
    }
    // A full reload, same as every other language-change path (see
    // i18n.js's setLocale callers) — there's no in-place re-render
    // system for a locale switch, so this is consistent with how a
    // mismatch discovered at boot also just reloads once.
    setLocale(next);
    showToast(t("settings.language_saved"), "success");
    window.location.reload();
  });
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
      showToast(t("settings.photo_updated"), "success");
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
      showToast(t("settings.photo_removed"), "success");
    } catch {
      /* api.js already showed a toast */
    }
  });
}

async function loadBreakMode(container, writable) {
  const root = container.querySelector("#break-mode-root");
  if (!root) return;
  const cancelSkeleton = showSkeletonAfterDelay(root, `<div class="skeleton" style="height: 56px;"></div>`);
  try {
    const me = await api.get(`${HB}/me`);
    cancelSkeleton();
    root.innerHTML = `
      <div class="switch-row">
        <div class="switch-row-text">
          <span>${escapeHtml(t("settings.on_break_label"))}</span>
          <span class="muted">${escapeHtml(t("settings.on_break_desc"))}</span>
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
                title: t("settings.go_on_break_title"),
                message: t("settings.go_on_break_message"),
                confirmLabel: t("settings.go_on_break_confirm"),
              }
            : {
                title: t("settings.end_break_title"),
                message: t("settings.end_break_message"),
                confirmLabel: t("settings.end_break_confirm"),
              }
        );
        if (!ok) return;
        try {
          await api.patch(`${HB}/me`, { on_break: next });
          btn.classList.toggle("on", next);
          btn.setAttribute("aria-checked", String(next));
          showToast(next ? t("settings.on_break_toast") : t("settings.end_break_toast"), "success");
        } catch {
          /* api.js already showed a toast */
        }
      });
    }
  } catch {
    cancelSkeleton();
    root.innerHTML = `<div class="empty-state">${escapeHtml(t("settings.couldnt_load_break"))}</div>`;
  }
}

async function loadPushSection(container, writable) {
  const root = container.querySelector("#push-root");
  if (!root) return;
  const cancelSkeleton = showSkeletonAfterDelay(root, `<div class="skeleton" style="height: 56px;"></div>`);

  if (!isPushSupported()) {
    cancelSkeleton();
    root.innerHTML = `<div class="muted" style="font-size: var(--font-size-sm);">${escapeHtml(t("settings.push_not_supported"))}</div>`;
    return;
  }

  const subscription = await getPushSubscription();
  cancelSkeleton();
  root.innerHTML = `
    <div class="switch-row">
      <div class="switch-row-text">
        <span>${escapeHtml(t("settings.push_label"))}</span>
        <span class="muted">${escapeHtml(t("settings.push_desc"))}</span>
      </div>
      <button class="switch${subscription ? " on" : ""}" id="push-switch" role="switch" aria-checked="${Boolean(subscription)}" ${writable ? "" : "disabled"}></button>
    </div>
    ${
      subscription && writable
        ? `<button class="btn" id="push-test-btn" style="margin-top: var(--space-2);">${escapeHtml(t("settings.push_test_btn"))}</button>`
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
      showToast(turningOn ? t("settings.push_on_toast") : t("settings.push_off_toast"), "success");
      await loadPushSection(container, writable); // re-render: the test button only shows while subscribed
    } catch (err) {
      showToast(err.message || t("settings.push_error"), "danger");
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
          showToast(t("settings.push_test_sent"), "success");
        } else {
          showToast(t("settings.push_test_failed"), "warning");
        }
      } catch {
        /* api.js already showed a toast */
      } finally {
        testBtn.disabled = false;
      }
    });
  }
}

// Read-only for everyone here — only the Admin panel (/admin) can change
// it, which is why there's no input/save button in this section anymore.
async function loadHouseholdSettings(container) {
  const root = container.querySelector("#household-settings-root");
  if (!root) return;
  const cancelSkeleton = showSkeletonAfterDelay(root, `<div class="skeleton" style="height: 56px;"></div>`);
  try {
    const settings = await api.get(`${HB}/settings`);
    cancelSkeleton();
    root.innerHTML = `
      <div class="row-between">
        <span class="muted">${escapeHtml(t("settings.weekly_goal_label"))}</span>
        <span>${settings.weekly_points_goal ?? escapeHtml(t("settings.not_set"))}</span>
      </div>
    `;
  } catch {
    cancelSkeleton();
    root.innerHTML = `<div class="empty-state">${escapeHtml(t("settings.couldnt_load_household"))}</div>`;
  }
}
