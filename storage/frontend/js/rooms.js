import { CONFIG } from "./config.js";
import { api } from "./api.js";
import { icons } from "./icons.js";
import { getCurrentUserInfo } from "./auth.js";
import { showToast } from "./toast.js";
import { showConfirmDialog } from "./confirmDialog.js";

function canWrite() {
  const info = getCurrentUserInfo();
  return info && (info.role === "admin" || info.role === "user");
}

export async function renderRooms(container) {
  const writable = canWrite();

  container.innerHTML = `
    <div class="page">
      <div class="row-between" style="margin-bottom: var(--space-2);">
        <h1 style="margin: 0; font-size: var(--font-size-lg);">Rooms</h1>
      </div>
      <p class="muted" style="font-size: var(--font-size-sm);">
        The rooms available when setting an item's location — add one here
        before using it on an item, instead of typing a new one each time.
      </p>

      ${
        writable
          ? `<div class="row" style="margin-bottom: var(--space-4);">
               <input class="input" id="new-room-name" placeholder="New room name" maxlength="64" />
               <button class="btn btn-primary" id="add-room-btn">${icons.plus}<span>Add</span></button>
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
        showToast("Enter a room name", "warning");
        return;
      }
      addBtn.disabled = true;
      try {
        await api.post(`${CONFIG.STORAGE_BASE}/rooms`, { name });
        nameInput.value = "";
        showToast(`Added "${name}"`, "success");
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
    root.innerHTML = `<div class="empty-state">Couldn't load rooms</div>`;
    return;
  }
  cancelSkeleton();

  if (rooms.length === 0) {
    root.innerHTML = `<div class="empty-state">${icons.box}<p style="margin-top: var(--space-2);">No rooms yet</p></div>`;
    return;
  }

  root.innerHTML = rooms
    .map(
      (room) => `
      <div class="row-between" style="padding: var(--space-3) var(--space-4); border: 1px solid var(--color-border); border-radius: var(--radius-md);">
        <span>${escapeHtml(room.name)}</span>
        ${writable ? `<button class="btn btn-icon" data-room-id="${room.id}" data-room-name="${escapeAttr(room.name)}" aria-label="Delete ${escapeAttr(room.name)}">${icons.trash}</button>` : ""}
      </div>`
    )
    .join("");

  if (writable) {
    root.querySelectorAll("[data-room-id]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const ok = await showConfirmDialog({
          title: "Delete room",
          message: `Delete "${btn.dataset.roomName}"? This only works while no item is stored there.`,
          confirmLabel: "Delete",
          danger: true,
        });
        if (!ok) return;
        try {
          await api.del(`${CONFIG.STORAGE_BASE}/rooms/${btn.dataset.roomId}`);
          showToast("Room deleted", "success");
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
