import { getStoredTheme, applyTheme } from "./theme.js";
import { handleAuthentikCallback } from "./auth.js";
import { startRouter, navigate } from "./router.js";
import { showToast } from "./toast.js";
import { registerServiceWorker } from "./push.js";

// index.html's inline head script already applies the theme before first
// paint to avoid a flash; this just keeps the two in sync in case the
// stored value changes some other way.
applyTheme(getStoredTheme());

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
    showToast("Login with Authentik failed", "danger");
  }
  // Not navigate() — the router's click/popstate listeners aren't
  // attached yet, and startRouter()'s own initial render below would
  // then render a second time on top of this one.
  if (loggedIn) {
    window.history.replaceState({}, "", "/home");
  }

  registerServiceWorker();
  startRouter();
}

boot();
