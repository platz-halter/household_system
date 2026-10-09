import { login, loginWithAuthentik } from "./auth.js";
import { showToast } from "./toast.js";
import { icons } from "./icons.js";
import { navigate } from "./router.js";
import { refreshNotificationBadge } from "./notifications.js";
import { t, syncLocaleFromServer } from "./i18n.js";
import { escapeHtml } from "./util.js";

export function renderLogin(container) {
  container.innerHTML = `
    <div class="container-narrow center" style="min-height: 100vh; flex-direction: column;">
      <div style="margin-bottom: var(--space-6);">${icons.checklist}</div>

      <button class="btn btn-primary btn-block" id="authentik-login-btn">${escapeHtml(t("login.with_authentik"))}</button>

      <button class="btn btn-ghost" id="toggle-local-login" style="margin-top: var(--space-4);">
        ${escapeHtml(t("login.use_local"))}
      </button>

      <form id="login-form" class="stack hidden" style="width: 100%; margin-top: var(--space-4);">
        <div class="field">
          <label for="login-username">${escapeHtml(t("login.username"))}</label>
          <input class="input" id="login-username" autocomplete="username" required />
        </div>
        <div class="field">
          <label for="login-password">${escapeHtml(t("login.password"))}</label>
          <input class="input" id="login-password" type="password" autocomplete="current-password" required />
        </div>
        <button class="btn btn-block" type="submit" id="login-submit">${escapeHtml(t("login.submit"))}</button>
      </form>
    </div>
  `;

  container.querySelector("#authentik-login-btn").addEventListener("click", async () => {
    // On success this redirects the browser away and never returns. On
    // failure (auth service unreachable, or Authentik simply not
    // configured yet on a fresh deploy) it throws instead — show that
    // as an ordinary toast rather than an unhandled rejection.
    try {
      await loginWithAuthentik();
    } catch {
      showToast(t("login.authentik_unreachable"), "danger");
    }
  });

  const form = container.querySelector("#login-form");
  const toggleBtn = container.querySelector("#toggle-local-login");
  toggleBtn.addEventListener("click", () => {
    const nowShown = form.classList.toggle("hidden") === false;
    toggleBtn.textContent = nowShown ? t("login.use_authentik_instead") : t("login.use_local");
  });

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const submitBtn = container.querySelector("#login-submit");
    const username = container.querySelector("#login-username").value.trim();
    const password = container.querySelector("#login-password").value;

    submitBtn.disabled = true;
    submitBtn.textContent = t("login.submitting");
    try {
      await login(username, password);
      navigate("/home");
      // No full page reload happens here (unlike the Authentik redirect
      // flow), so the bell's own canWrite() check never gets re-run
      // until its next poll — nudge it now instead of waiting up to
      // POLL_INTERVAL_MS for it to notice this session is logged in.
      refreshNotificationBadge();
      // Same reasoning, for the viewer's own language: boot()'s own
      // sync only ever runs once, at the page's original load — a local
      // login never re-triggers it, so without this a fresh local login
      // on a device whose cached locale disagrees with this account's
      // HouseholdUser.preferred_language would silently stay wrong
      // until the next real page load.
      syncLocaleFromServer();
    } catch (err) {
      showToast(err.message || t("login.failed"), "danger");
      submitBtn.disabled = false;
      submitBtn.textContent = t("login.submit");
    }
  });
}
