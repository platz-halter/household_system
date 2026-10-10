import { icons } from "./icons.js";
import { t } from "./i18n.js";

// "On first page opening" across devices, in practice, means two very
// different mechanisms:
//  - Android/Chrome fires `beforeinstallprompt` once it decides the page
//    is actually installable (manifest + service worker + HTTPS) — we
//    can only show a real "Install" action once that's fired, not on a
//    fixed timer, and calling .prompt() is the only way to trigger the
//    native install flow at all.
//  - iOS Safari has no such event and no programmatic install API,
//    ever — the only path is Share -> "Add to Home Screen", so there's
//    nothing to wait for; the banner there is instructions, not a button.
// (Same module as household/frontend's own installPrompt.js — this
// frontend keeps its own copy of everything rather than sharing code
// with household's, see this project's own frontend conventions.)
const DISMISSED_KEY = "hs-install-prompt-dismissed";

// Not shared with other files here on purpose — see this app's own
// escapeHtml precedent (overview.js etc.): no shared util.js, unlike
// household/frontend.
function escapeHtml(str) {
  return String(str ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
}

function escapeAttr(str) {
  return escapeHtml(str);
}

function isIOS() {
  // iPadOS 13+ reports as "MacIntel" in the UA string like a real Mac —
  // maxTouchPoints is what actually tells the two apart (a real Mac has
  // none).
  return (
    /iPad|iPhone|iPod/.test(navigator.userAgent) ||
    (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1)
  );
}

function isAndroid() {
  return /Android/.test(navigator.userAgent);
}

function isStandalone() {
  return (
    window.matchMedia?.("(display-mode: standalone)").matches ||
    // navigator.standalone is Safari's own older, non-standard signal
    // for the exact same thing.
    window.navigator.standalone === true
  );
}

function isDismissed() {
  try {
    return localStorage.getItem(DISMISSED_KEY) === "1";
  } catch {
    return false;
  }
}

function markDismissed() {
  try {
    localStorage.setItem(DISMISSED_KEY, "1");
  } catch {
    /* ignore — worst case it can show again next visit */
  }
}

let deferredInstallEvent = null;

function showBanner({ installable }) {
  if (document.getElementById("install-banner")) return; // already up

  const banner = document.createElement("div");
  banner.id = "install-banner";
  banner.className = "install-banner";
  banner.innerHTML = `
    <span class="install-banner-text">${escapeHtml(t(installable ? "install.android_message" : "install.ios_message"))}</span>
    <div class="row" style="gap: var(--space-2); flex-shrink: 0;">
      ${installable ? `<button class="btn btn-primary" id="install-banner-install">${escapeHtml(t("install.install_btn"))}</button>` : `<button class="btn btn-primary" id="install-banner-ok">${escapeHtml(t("install.got_it_btn"))}</button>`}
      <button class="btn btn-icon" id="install-banner-dismiss" aria-label="${escapeAttr(t("install.dismiss_aria"))}">${icons.close}</button>
    </div>
  `;
  document.body.appendChild(banner);

  const dismiss = () => {
    banner.remove();
    markDismissed();
  };

  banner.querySelector("#install-banner-dismiss").addEventListener("click", dismiss);
  banner.querySelector("#install-banner-ok")?.addEventListener("click", dismiss);
  banner.querySelector("#install-banner-install")?.addEventListener("click", async () => {
    dismiss();
    if (!deferredInstallEvent) return;
    deferredInstallEvent.prompt();
    await deferredInstallEvent.userChoice;
    deferredInstallEvent = null;
  });
}

/** Called once on boot. */
export function initInstallPrompt() {
  if (isStandalone() || isDismissed()) return;

  if (isAndroid()) {
    // Only Chrome/Chromium-based Android browsers fire this — nothing
    // to show on Android browsers that don't (Firefox, etc.); there's
    // no fallback instructional path for those the way there is for iOS,
    // since "how" varies too much browser to browser to write one.
    window.addEventListener("beforeinstallprompt", (event) => {
      event.preventDefault();
      deferredInstallEvent = event;
      showBanner({ installable: true });
    });
    // Covers installing some OTHER way (the browser's own menu, not this
    // banner's button) — either way, don't ask again.
    window.addEventListener("appinstalled", markDismissed);
  } else if (isIOS()) {
    showBanner({ installable: false });
  }
}
