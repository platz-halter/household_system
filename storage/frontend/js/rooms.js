import { CONFIG } from "./config.js";
import { api } from "./api.js";
import { icons } from "./icons.js";
import { getCurrentUserInfo } from "./auth.js";
import { showToast } from "./toast.js";
import { showConfirmDialog } from "./confirmDialog.js";
import { t } from "./i18n.js";

function canWrite() {
  const info = getCurrentUserInfo();
  return info && (info.role === "admin" || info.role === "user");
}

export async function renderRooms(container) {
  const writable = canWrite();

  container.innerHTML = `
    <div class="page">
      <div class="row-between" style="margin-bottom: var(--space-2);">
        <h1 style="margin: 0; font-size: var(--font-size-lg);">${escapeHtml(t("rooms.heading"))}</h1>
      </div>
      <p class="muted" style="font-size: var(--font-size-sm);">
        ${escapeHtml(t("rooms.desc"))}
      </p>

      ${
        writable
          ? `<div class="row" style="margin-bottom: var(--space-4);">
               <input class="input" id="new-room-name" placeholder="${escapeAttr(t("rooms.new_room_placeholder"))}" maxlength="64" />
               <button class="btn btn-primary" id="add-room-btn">${icons.plus}<span>${escapeHtml(t("rooms.add_btn"))}</span></button>
             </div>`
          : ""
      }

      <div id="rooms-list" class="stack"></div>
    </div>
  `;

  if (writable) {
    const nameInput = container.querySelector("#new-room-name");
    const addBtn = container.querySelector("#add-room-btn");
    const submit = async () => {
      const name = nameInput.value.trim();
      if (!name) {
        showToast(t("rooms.enter_name_warning"), "warning");
        return;
      }
      addBtn.disabled = true;
      try {
        await api.post(`${CONFIG.STORAGE_BASE}/rooms`, { name });
        nameInput.value = "";
        showToast(t("common.added_toast", { name }), "success");
        await loadRooms(container, writable);
      } catch {
        /* api.js already showed a toast */
      } finally {
        addBtn.disabled = false;
      }
    };
    addBtn.addEventListener("click", submit);
    nameInput.addEventListener("keydown", (e) => {
      if (e.key === "Enter") submit();
    });
  }

  await loadRooms(container, writable);
}

async function loadRooms(container, writable) {
  const root = container.querySelector("#rooms-list");
  if (!root) return;
  const cancelSkeleton = showSkeletonAfterDelay(root, `<div class="skeleton" style="height: 48px;"></div>`);

  let rooms;
  try {
    rooms = await api.get(`${CONFIG.STORAGE_BASE}/rooms`);
  } catch {
    cancelSkeleton();
    root.innerHTML = `<div class="empty-state">${escapeHtml(t("rooms.couldnt_load"))}</div>`;
    return;
  }
  cancelSkeleton();

  if (rooms.length === 0) {
    root.innerHTML = `<div class="empty-state">${icons.box}<p style="margin-top: var(--space-2);">${escapeHtml(t("rooms.no_rooms_yet"))}</p></div>`;
    return;
  }

  root.innerHTML = rooms
    .map(
      (room) => `
      <div class="row-between" style="padding: var(--space-3) var(--space-4); border: 1px solid var(--color-border); border-radius: var(--radius-md);">
        <span>${escapeHtml(room.name)}</span>
        ${writable ? `<button class="btn btn-icon" data-room-id="${room.id}" data-room-name="${escapeAttr(room.name)}" aria-label="${escapeAttr(t("rooms.delete_aria", { name: room.name }))}">${icons.trash}</button>` : ""}
      </div>`
    )
    .join("");

  if (writable) {
    root.querySelectorAll("[data-room-id]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const ok = await showConfirmDialog({
          title: t("rooms.delete_title"),
          message: t("rooms.delete_message", { name: btn.dataset.roomName }),
          confirmLabel: t("common.delete"),
          danger: true,
        });
        if (!ok) return;
        try {
          await api.del(`${CONFIG.STORAGE_BASE}/rooms/${btn.dataset.roomId}`);
          showToast(t("rooms.deleted_toast"), "success");
          await loadRooms(container, writable);
        } catch {
          /* api.js already showed a toast (e.g. 409 if still in use) */
        }
      });
    });
  }
}

function escapeHtml(str) {
  return String(str ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
}

function escapeAttr(str) {
  return escapeHtml(str);
}

// A skeleton shown immediately flashes for anything that resolves fast
// (typical on a local network) — delaying when it's allowed to appear
// means a quick response never shows one at all, only a genuinely slow
// one does. Call this right before the request starts, then call the
// returned function as soon as it settles.
function showSkeletonAfterDelay(root, html, delayMs = 200) {
  const timer = setTimeout(() => {
    root.innerHTML = html;
  }, delayMs);
  return () => clearTimeout(timer);
}
