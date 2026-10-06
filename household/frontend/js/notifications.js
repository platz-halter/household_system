// The bell icon in the topbar, next to Settings — a persistent inbox,
// on top of the one-shot Web Push notifications push.js already sends.
// Two kinds live here: incoming takeover requests (actionable —
// Accept/Decline right from the panel) and plain notifications (new
// chore request, admin reassign, takeover responded, new report, the
// weekly nudge — anything crud._notify creates; see that function's own
// docstring for why these are a durable in-app record and not just a
// push). Extend both `refreshNotificationBadge`/`renderPanelList` if a
// third kind is ever needed, rather than inventing a parallel mechanism.
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
import { navigate } from "./router.js";
import { escapeHtml, timeAgo } from "./util.js";

const HB = CONFIG.HOUSEHOLD_BASE;
const POLL_INTERVAL_MS = 30_000;

let bellBtn = null;
let badgeEl = null;

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
    // request's target (see crud._validate_takeover_target) and gets
    // none of the other notification kinds either, so their inbox is
    // always empty. Hide the bell rather than show a control that can
    // never do anything, and skip the network calls.
    //
    // Uses the `.hidden` CSS class (base.css, `!important`), not the
    // native `hidden` IDL property/attribute — `.btn`'s own
    // `display: inline-flex` has the same specificity as the browser's
    // built-in `[hidden] { display: none }` and comes later in the
    // cascade, so plain `bellBtn.hidden = true` silently loses that
    // fight and the button stays visually shown despite the attribute
    // being set (caught live: getAttribute("hidden") was correctly
    // non-null, but isVisible() was still true).
    bellBtn.classList.add("hidden");
    return;
  }
  bellBtn.classList.remove("hidden");
  let incoming, unread;
  try {
    [incoming, unread] = await Promise.all([
      api.get(`${HB}/takeover-requests?direction=incoming`, { silent: true }),
      api.get(`${HB}/notifications?unread_only=true&limit=50`, { silent: true }),
    ]);
  } catch {
    return; // transient network/auth hiccup — leave the last-known count showing
  }
  const count = incoming.length + unread.length;
  badgeEl.classList.toggle("hidden", count === 0);
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
      <div id="notif-panel-takeover" class="stack"></div>
      <div id="notif-panel-plain-section" class="section-heading" style="margin-top: var(--space-4);">
        <h2>Recent</h2>
        <button class="btn btn-ghost" id="notif-mark-all-read" style="font-size: var(--font-size-xs);">Mark all read</button>
      </div>
      <div id="notif-panel-plain" class="stack"></div>
    </div>
  `;
  document.body.appendChild(overlay);
  const close = () => overlay.remove();
  overlay.querySelector("#notif-panel-close").addEventListener("click", close);
  overlay.addEventListener("click", (e) => {
    if (e.target === overlay) close();
  });
  overlay.querySelector("#notif-mark-all-read").addEventListener("click", async () => {
    try {
      await api.post(`${HB}/notifications/read-all`);
      await renderPanelList(overlay);
      refreshNotificationBadge();
    } catch {
      /* api.js already showed a toast */
    }
  });

  renderPanelList(overlay, { initial: true });
}

// `initial` only shows a loading skeleton for the very first render,
// right after the panel's just been created with nothing in it yet.
// Every other call (after mark-all-read, accept/decline, dismiss) is a
// RE-render of an already-open panel, which already has real content
// on screen — clearing it to a skeleton/blank first, then refilling
// once the refetch lands, put a visible empty gap between the two,
// which read as the whole panel flickering closed and reopening. Not
// clearing anything upfront means the old content just sits there
// unchanged until renderTakeoverSection/renderPlainSection swap it for
// the new content in one go — no intermediate empty state to see.
async function renderPanelList(overlay, { initial = false } = {}) {
  const takeoverRoot = overlay.querySelector("#notif-panel-takeover");
  const plainRoot = overlay.querySelector("#notif-panel-plain");
  if (initial) {
    takeoverRoot.innerHTML = `<div class="skeleton" style="height: 64px;"></div>`;
  }

  let incoming, notifications;
  try {
    [incoming, notifications] = await Promise.all([
      api.get(`${HB}/takeover-requests?direction=incoming`),
      api.get(`${HB}/notifications?limit=30`),
    ]);
  } catch {
    takeoverRoot.innerHTML = `<div class="empty-state">Couldn't load notifications</div>`;
    return;
  }
  await refreshNotificationBadge();
  renderTakeoverSection(overlay, takeoverRoot, incoming);
  renderPlainSection(overlay, plainRoot, notifications);
}

function renderTakeoverSection(overlay, root, incoming) {
  if (incoming.length === 0) {
    root.innerHTML = `<div class="empty-state">${icons.bell}<p style="margin-top: var(--space-2);">Nothing new</p></div>`;
    return;
  }

  root.innerHTML = "";
  incoming.forEach((req) => {
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

// Plain notifications — nothing to accept/decline, just dismiss (mark
// read) or tap to go wherever it points. Shown newest-first regardless
// of read state (so dismissing one doesn't make the list visually jump
// around), with unread ones visually distinct.
function renderPlainSection(overlay, root, notifications) {
  const sectionHeader = overlay.querySelector("#notif-panel-plain-section");
  if (notifications.length === 0) {
    sectionHeader.classList.add("hidden");
    root.innerHTML = "";
    return;
  }
  sectionHeader.classList.remove("hidden");

  root.innerHTML = "";
  notifications.forEach((n) => {
    const row = document.createElement("div");
    row.className = "list-row";
    row.innerHTML = `
      <div class="list-row-body">
        <div class="list-row-title">${!n.read_at ? `<span class="badge badge-info" style="margin-right:4px;">New</span>` : ""}${escapeHtml(n.title)}</div>
        <div class="list-row-meta"><span>${escapeHtml(n.body)}</span></div>
        <div class="list-row-meta"><span class="muted">${escapeHtml(timeAgo(n.created_at))}</span></div>
      </div>
      <div class="list-row-actions">
        <button class="btn btn-icon btn-ghost" data-action="dismiss" aria-label="Dismiss">${icons.close}</button>
      </div>
    `;
    row.addEventListener("click", (e) => {
      if (e.target.closest('[data-action="dismiss"]')) return;
      overlay.remove();
      navigate(n.url);
    });
    row.querySelector('[data-action="dismiss"]').addEventListener("click", async (e) => {
      e.stopPropagation();
      try {
        await api.post(`${HB}/notifications/${n.id}/read`);
        await renderPanelList(overlay);
        refreshNotificationBadge();
      } catch {
        /* api.js already showed a toast */
      }
    });
    root.appendChild(row);
  });
}
