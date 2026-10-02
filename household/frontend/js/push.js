import { CONFIG } from "./config.js";
import { api } from "./api.js";

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

/** Called once on boot — registering is cheap/idempotent even if the user
 * never opts into notifications. */
export async function registerServiceWorker() {
  if (!isPushSupported()) return null;
  try {
    return await navigator.serviceWorker.register("sw.js");
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
    throw new Error("Push notifications aren't supported in this browser");
  }
  const permission = await Notification.requestPermission();
  if (permission !== "granted") {
    throw new Error("Notification permission was denied");
  }

  const { public_key } = await api.get(`${HB}/push/vapid-public-key`);
  if (!public_key) {
    throw new Error("Push isn't configured on the server yet");
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
