// The bell icon in the topbar, next to Settings — a persistent inbox for
// things that need a response, on top of the one-shot Web Push
// notifications push.js already sends. Currently the only notification
// kind is an incoming takeover request (see PROJECT_SPEC.md's "Handing
// off an assigned task"); extend `fetchIncoming`/`renderPanel` here if a
// second kind is ever added, rather than inventing a parallel mechanism.
//
// Lives outside router.js on purpose — it's chrome (same as the topbar
// itself), not a page, so it's wired up once from main.js's boot() and
// polls independently of navigation. Pages that also show takeover
// requests inline (home.js's "Takeover requests" section, board.js's
// per-row controls) call refreshNotificationBadge() after their own
// accept/decline/cancel so the bell's count doesn't go stale until the
// next poll.
import { api } from "./api.js";
import { CONFIG } from "./config.js";
import { icons } from "./icons.js";
import { getCurrentUserInfo } from "./auth.js";
import { showToast } from "./toast.js";
import { escapeHtml } from "./util.js";

const HB = CONFIG.HOUSEHOLD_BASE;
const POLL_INTERVAL_MS = 30_000;

let bellBtn = null;
let badgeEl = null;
let incomingCache = [];

function canWrite() {
  const info = getCurrentUserInfo();
  return info && (info.role === "admin" || info.role === "user");
}

// Wired once at boot, regardless of whether the user is logged in yet —
// local login (login.js) is an in-SPA navigate(), not a full page
// reload, so there's no second boot() call to re-run this after
// someone logs in. refreshNotificationBadge() re-checks canWrite() on
// every call instead (including every poll tick), so the bell shows up
// within one poll interval of logging in on its own; login.js also
// calls it directly right after a successful local login so it doesn't
// have to wait that long.
export function initNotificationInbox() {
  bellBtn = document.getElementById("notif-bell");
  badgeEl = document.getElementById("notif-badge");
  if (!bellBtn || !badgeEl) return;

  bellBtn.addEventListener("click", openNotificationPanel);
  refreshNotificationBadge();
  setInterval(refreshNotificationBadge, POLL_INTERVAL_MS);
}

export async function refreshNotificationBadge() {
  if (!bellBtn || !badgeEl) return;
  if (!canWrite()) {
    // Not logged in, or a viewer — a viewer can never be a takeover
    // request's target (see crud._validate_takeover_target), so their
    // inbox is always empty. Hide the bell rather than show a control
    // that can never do anything, and skip the network call.
    bellBtn.hidden = true;
    return;
  }
  bellBtn.hidden = false;
  try {
    incomingCache = await api.get(`${HB}/takeover-requests?direction=incoming`, { silent: true });
  } catch {
    return; // transient network/auth hiccup — leave the last-known count showing
  }
  const count = incomingCache.length;
  badgeEl.hidden = count === 0;
  badgeEl.textContent = count > 9 ? "9+" : String(count);
}

function openNotificationPanel() {
  const overlay = document.createElement("div");
  overlay.className = "modal-overlay";
  overlay.innerHTML = `
    <div class="modal" role="dialog" aria-modal="true">
      <div class="modal-header">
        <h2>Notifications</h2>
        <button class="btn btn-icon btn-ghost" id="notif-panel-close" aria-label="Close">${icons.close}</button>
      </div>
      <div class="stack" id="notif-panel-list"></div>
    </div>
  `;
  document.body.appendChild(overlay);
  const close = () => overlay.remove();
  overlay.querySelector("#notif-panel-close").addEventListener("click", close);
  overlay.addEventListener("click", (e) => {
    if (e.target === overlay) close();
  });

  renderPanelList(overlay);
}

async function renderPanelList(overlay) {
  const root = overlay.querySelector("#notif-panel-list");
  root.innerHTML = `<div class="skeleton" style="height: 64px;"></div>`;
  try {
    incomingCache = await api.get(`${HB}/takeover-requests?direction=incoming`);
  } catch {
    root.innerHTML = `<div class="empty-state">Couldn't load notifications</div>`;
    return;
  }
  await refreshNotificationBadge();

  if (incomingCache.length === 0) {
    root.innerHTML = `<div class="empty-state">${icons.bell}<p style="margin-top: var(--space-2);">Nothing new</p></div>`;
    return;
  }

  root.innerHTML = "";
  incomingCache.forEach((req) => {
    const label = req.todo_title || req.task_name;
    const row = document.createElement("div");
    row.className = "list-row";
    row.style.cursor = "default";
    row.innerHTML = `
      <div class="list-row-body">
        <div class="list-row-title">${escapeHtml(label)}</div>
        <div class="list-row-meta"><span>${escapeHtml(req.requester.display_name)} asked you to take this over</span></div>
      </div>
      <div class="list-row-actions">
        <button class="btn btn-icon btn-danger" data-action="decline" aria-label="Decline">${icons.close}</button>
        <button class="btn btn-icon btn-primary" data-action="accept" aria-label="Accept">${icons.check}</button>
      </div>
    `;
    row.querySelector('[data-action="accept"]').addEventListener("click", async () => {
      try {
        await api.post(`${HB}/takeover-requests/${req.id}/accept`);
        showToast(`Took over "${label}"`, "success");
        await renderPanelList(overlay);
      } catch {
        /* api.js already showed a toast (e.g. 409 if it changed hands first) */
        await renderPanelList(overlay);
      }
    });
    row.querySelector('[data-action="decline"]').addEventListener("click", async () => {
      try {
        await api.post(`${HB}/takeover-requests/${req.id}/decline`);
        showToast("Declined", "success");
        await renderPanelList(overlay);
      } catch {
        /* api.js already showed a toast */
      }
    });
    root.appendChild(row);
  });
}
