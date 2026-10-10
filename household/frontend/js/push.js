import { CONFIG } from "./config.js";
import { api } from "./api.js";
import { t } from "./i18n.js";

const HB = CONFIG.HOUSEHOLD_BASE;

function urlBase64ToUint8Array(base64String) {
  const padding = "=".repeat((4 - (base64String.length % 4)) % 4);
  const base64 = (base64String + padding).replace(/-/g, "+").replace(/_/g, "/");
  const rawData = atob(base64);
  return Uint8Array.from([...rawData].map((c) => c.charCodeAt(0)));
}

export function isPushSupported() {
  return "serviceWorker" in navigator && "PushManager" in window;
}

// iOS only exposes PushManager to a page running as an installed Home
// Screen app (Safari 16.4+) — a plain browser tab always fails
// isPushSupported() above, indistinguishably from a browser that
// doesn't support push at all. These two let settings.js tell those
// cases apart and point an iOS user at the actual fix (install it)
// instead of a flat, misleading "not supported."
export function isIOS() {
  // iPadOS 13+ reports as "MacIntel" in the UA string like a real Mac —
  // maxTouchPoints is what actually tells the two apart.
  return (
    /iPad|iPhone|iPod/.test(navigator.userAgent) ||
    (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1)
  );
}

export function isStandalone() {
  return (
    window.matchMedia?.("(display-mode: standalone)").matches ||
    // navigator.standalone is Safari's own older, non-standard signal for
    // the exact same thing — kept as a fallback for older iOS/webkit.
    window.navigator.standalone === true
  );
}

/** Called once on boot — registering is cheap/idempotent even if the user
 * never opts into notifications. */
export async function registerServiceWorker() {
  if (!isPushSupported()) return null;
  try {
    // Root-absolute: a relative "sw.js" resolves against the current
    // page's path, so a boot from a deep route like /admin would
    // register (and fail to find) /admin/sw.js instead of the real file.
    return await navigator.serviceWorker.register("/sw.js");
  } catch {
    return null;
  }
}

export async function getPushSubscription() {
  if (!isPushSupported()) return null;
  const reg = await navigator.serviceWorker.ready.catch(() => null);
  if (!reg) return null;
  return reg.pushManager.getSubscription();
}

export async function subscribeToPush() {
  if (!isPushSupported()) {
    throw new Error(t("push.not_supported_err"));
  }
  const permission = await Notification.requestPermission();
  if (permission !== "granted") {
    throw new Error(t("push.permission_denied_err"));
  }

  const { public_key } = await api.get(`${HB}/push/vapid-public-key`);
  if (!public_key) {
    throw new Error(t("push.not_configured_err"));
  }

  const reg = await navigator.serviceWorker.ready;
  const subscription = await reg.pushManager.subscribe({
    userVisibleOnly: true,
    applicationServerKey: urlBase64ToUint8Array(public_key),
  });
  await api.post(`${HB}/push/subscribe`, subscription.toJSON());
  return subscription;
}

export async function unsubscribeFromPush() {
  const subscription = await getPushSubscription();
  if (!subscription) return;
  const endpoint = subscription.endpoint;
  await subscription.unsubscribe();
  try {
    await api.post(`${HB}/push/unsubscribe`, { endpoint });
  } catch {
    /* already gone locally; a stale row server-side is harmless */
  }
}
