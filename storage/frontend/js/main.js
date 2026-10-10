import { getStoredTheme, applyTheme } from "./theme.js";
import { handleAuthentikCallback, warmGroupRoleMap } from "./auth.js";
import { startRouter } from "./router.js";
import { showToast } from "./toast.js";
import { t, applyStaticTranslations } from "./i18n.js";
import { initInstallPrompt } from "./installPrompt.js";

// index.html's inline head script already applies the theme before first
// paint to avoid a flash; this just keeps the two in sync in case the
// stored value changes some other way.
applyTheme(getStoredTheme());

// i18n.js's own module-level code (imported transitively by many modules
// already loaded above) has already resolved a locale and set <html
// lang> by this point — this just applies it to the static chrome
// (topbar/bottom-nav labels) that lives in index.html rather than being
// rendered by any page module.
document.title = t("app.title");
applyStaticTranslations();

async function boot() {
  // Cheap no-op unless the URL is actually an Authentik callback
  // (?code=...&state=...) — handles the token exchange and strips the
  // query params either way, so this must run before the router reads
  // the URL.
  const hadCallback = new URLSearchParams(window.location.search).has("code");
  const loggedIn = await handleAuthentikCallback();

  if (hadCallback && !loggedIn) {
    showToast(t("login.authentik_callback_failed"), "danger");
  }
  // Not navigate() — the router's click/popstate listeners aren't
  // attached yet, and startRouter()'s own initial render below would
  // then render a second time on top of this one.
  if (loggedIn) {
    window.history.replaceState({}, "", "/overview");
  }

  // Deliberately NOT awaited — an unreachable auth service must not
  // delay the first render (same reasoning as the rest of this file's
  // network calls, see fetchWithTimeout's own comment in auth.js). The
  // role mapping it warms self-corrects within this page load once it
  // resolves; the brief window before then only matters for role-gated
  // UI a user couldn't reach this fast anyway (e.g. the /admin route,
  // which needs at least one more navigation to get to).
  warmGroupRoleMap();
  initInstallPrompt();
  startRouter();
}

boot();
