import { getStoredTheme, applyTheme } from "./theme.js";
import { handleAuthentikCallback, warmGroupRoleMap, isAuthenticated } from "./auth.js";
import { startRouter, navigate } from "./router.js";
import { showToast } from "./toast.js";
import { registerServiceWorker } from "./push.js";
import { initNotificationInbox } from "./notifications.js";
import { t, applyStaticTranslations, syncLocaleFromServer } from "./i18n.js";
import { installScrollHideFab } from "./util.js";
import { initInstallPrompt } from "./installPrompt.js";

// index.html's inline head script already applies the theme before first
// paint to avoid a flash; this just keeps the two in sync in case the
// stored value changes some other way.
applyTheme(getStoredTheme());

// i18n.js's own module-level code (imported transitively by many modules
// already loaded above) has already resolved a locale and set <html
// lang> by this point — this just applies it to the static chrome
// (topbar/bottom-nav labels, aria-labels, the document title) that lives
// in index.html rather than being rendered by any page module.
document.title = t("app.title");
applyStaticTranslations();

// A notification click in sw.js focuses an existing tab rather than
// opening a new one, then posts here to do the actual in-app navigation
// (a service worker can't touch this page's window.location directly).
navigator.serviceWorker?.addEventListener("message", (event) => {
  if (event.data?.type === "navigate" && event.data.url) {
    navigate(event.data.url);
  }
});

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
    window.history.replaceState({}, "", "/home");
  }

  // Deliberately NOT awaited — an unreachable auth service must not
  // delay the first render (same reasoning as the rest of this file's
  // network calls, see fetchWithTimeout's own comment in auth.js). The
  // role mapping it warms self-corrects within this page load once it
  // resolves; the brief window before then only matters for role-gated
  // UI a user couldn't reach this fast anyway (e.g. the /admin route,
  // which needs at least one more navigation to get to).
  warmGroupRoleMap();
  installScrollHideFab();
  initInstallPrompt();
  registerServiceWorker();
  initNotificationInbox();
  // Same "don't let an unreachable backend delay the first render"
  // reasoning as warmGroupRoleMap above — reconciling a stale cached
  // locale against the server's real value reloads the page when it
  // finds a mismatch (see i18n.js's reconcileLocale), which is fine to
  // happen a moment after the first paint. Only worth trying once
  // there's a token to call /me with at all.
  if (isAuthenticated()) syncLocaleFromServer();
  startRouter();
}

boot();
