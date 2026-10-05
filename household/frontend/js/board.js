import { CONFIG } from "./config.js";
import { api, fetchImageUrl } from "./api.js";
import { icons } from "./icons.js";
import { getCurrentUserInfo } from "./auth.js";
import { showToast } from "./toast.js";
import { showConfirmDialog } from "./confirmDialog.js";
import { openTaskPickerModal } from "./taskPicker.js";
import { takeoverControl } from "./takeover.js";
import { escapeHtml, escapeAttr, dueBadge, initials, showSkeletonAfterDelay } from "./util.js";

const HB = CONFIG.HOUSEHOLD_BASE;

const STATUS_FILTERS = [
  { id: "open", label: "Open" },
  { id: "completed", label: "Completed" },
  { id: "cancelled", label: "Cancelled" },
  { id: "", label: "All" },
];

const state = { status: "open" };
let usersCache = null;
let tasksCache = null;
let categoriesCache = null;
let meCache = null;
// Pending takeover requests this user has sent — swaps a row's "ask to
// take over" button for an "Asked {target} [cancel]" state (see
// takeover.js). Refetched alongside every todo list refresh so it never
// goes stale after an ask/cancel/accept.
let outgoingRequestsCache = [];

function canWrite() {
  const info = getCurrentUserInfo();
  return info && (info.role === "admin" || info.role === "user");
}

function isAdmin() {
  const info = getCurrentUserInfo();
  return info && info.role === "admin";
}

// Users on break aren't expected to be doing anything right now — hide
// them from every "assign this to someone" picker (request-from,
// reassign). Enforced server-side too (see crud._check_assignable); this
// is just so the option isn't offered in the first place.
function assignableUsers(users) {
  return users.filter((u) => !u.on_break);
}

export async function renderBoard(container) {
  const writable = canWrite();

  container.innerHTML = `
    <div class="page">
      <div class="chip-row" id="status-chips" style="margin-bottom: var(--space-3);">
        ${STATUS_FILTERS.map((f) => `<span class="chip${state.status === f.id ? " chip-active" : ""}" data-status="${f.id}">${f.label}</span>`).join("")}
      </div>
      <div id="todo-list" class="stack"></div>
    </div>
    ${writable ? `<button class="fab" id="add-todo-fab" aria-label="New todo">${icons.plus}</button>` : ""}
  `;

  container.querySelectorAll("#status-chips .chip").forEach((chip) => {
    chip.addEventListener("click", () => {
      state.status = chip.dataset.status;
      container.querySelectorAll("#status-chips .chip").forEach((c) => c.classList.remove("chip-active"));
      chip.classList.add("chip-active");
      refreshTodos(container, writable);
    });
  });

  if (writable) {
    container.querySelector("#add-todo-fab").addEventListener("click", () => openTodoModal(container));
  }

  await refreshTodos(container, writable);
}

// `force` refetches even if cached — used right before showing an
// assign/reassign picker, since on_break can change between page load
// and the moment someone opens that picker, and a stale "on break" flag
// there would wrongly show (or hide) someone.
async function loadUsers(force = false) {
  if (!usersCache || force) {
    try {
      usersCache = await api.get(`${HB}/users`);
    } catch {
      usersCache = usersCache || [];
    }
  }
  return usersCache;
}

// Always fresh (not cached-once like users above) — tasks can be added/
// edited on the Task management panel, and the modal shouldn't offer a
// stale list after a visit there.
async function loadTasks() {
  try {
    tasksCache = await api.get(`${HB}/tasks?active=true`);
  } catch {
    tasksCache = tasksCache || [];
  }
  return tasksCache;
}

async function loadCategories() {
  if (!categoriesCache) {
    try {
      categoriesCache = await api.get(`${HB}/categories`);
    } catch {
      categoriesCache = [];
    }
  }
  return categoriesCache;
}

async function refreshTodos(container, writable) {
  const root = container.querySelector("#todo-list");
  if (!root) return;
  const cancelSkeleton = showSkeletonAfterDelay(
    root,
    `<div class="skeleton" style="height: 64px;"></div><div class="skeleton" style="height: 64px; margin-top: 8px;"></div>`
  );

  let todos;
  try {
    const qs = state.status ? `?status=${encodeURIComponent(state.status)}` : "";
    const fetches = [api.get(`${HB}/todos${qs}`)];
    // Only a writable user can hold or ask about anything, so skip these
    // two fetches entirely for a read-only viewer.
    if (writable) {
      if (!meCache) fetches.push(api.get(`${HB}/me`));
      fetches.push(api.get(`${HB}/takeover-requests?direction=outgoing`));
    }
    const results = await Promise.all(fetches);
    todos = results[0];
    if (writable) {
      if (!meCache) meCache = results[1];
      outgoingRequestsCache = results[results.length - 1];
    }
  } catch {
    cancelSkeleton();
    root.innerHTML = `<div class="empty-state">Couldn't load the todo board</div>`;
    return;
  }
  cancelSkeleton();

  if (todos.length === 0) {
    root.innerHTML = `<div class="empty-state">${icons.board}<p style="margin-top: var(--space-2);">Nothing here</p></div>`;
    return;
  }

  root.innerHTML = "";
  todos.forEach((todo) => root.appendChild(todoRow(todo, container, writable)));
  hydrateAvatars(root);
}

// Photos load in after the initial render rather than blocking it.
async function hydrateAvatars(root) {
  const els = root.querySelectorAll("[data-avatar-user-id]");
  await Promise.all(
    [...els].map(async (el) => {
      const objectUrl = await fetchImageUrl(`${HB}/users/${el.dataset.avatarUserId}/photo`);
      if (objectUrl) {
        el.innerHTML = `<img src="${objectUrl}" alt="" style="width:100%; height:100%; object-fit:cover;" />`;
      }
    })
  );
}

function todoRow(todo, container, writable) {
  const row = document.createElement("div");
  row.className = "list-row";
  row.style.cursor = "default";

  const badge = dueBadge(todo.due_date);
  const assignee = todo.assigned_to
    ? `<span class="row" style="gap:4px;"><span class="avatar-sm"${todo.assigned_to.image_path ? ` data-avatar-user-id="${todo.assigned_to.id}"` : ""}>${escapeHtml(initials(todo.assigned_to.display_name))}</span>${escapeHtml(todo.assigned_to.display_name)}</span>`
    : `<span>Anyone</span>`;

  const statusBadge =
    todo.status === "completed"
      ? `<span class="badge badge-success">Completed${todo.completed_by ? ` by ${escapeHtml(todo.completed_by.display_name)}` : ""}</span>`
      : todo.status === "cancelled"
        ? `<span class="badge badge-neutral">Cancelled</span>`
        : badge
          ? `<span class="badge badge-${badge.tone}">${escapeHtml(badge.label)}</span>`
          : "";
  const chainBadge = todo.chain_parent_task_name
    ? `<span class="badge badge-neutral">After: ${escapeHtml(todo.chain_parent_task_name)}</span>`
    : "";

  const iHoldIt = writable && meCache && todo.assigned_to && todo.assigned_to.id === meCache.id;

  row.innerHTML = `
    <div class="list-row-body">
      <div class="list-row-title">${escapeHtml(todo.title)}</div>
      ${todo.description ? `<div class="muted" style="font-size: var(--font-size-xs);">${escapeHtml(todo.description)}</div>` : ""}
      <div class="list-row-meta">
        ${assignee}
        ${statusBadge}
        ${chainBadge}
        <span>by ${escapeHtml(todo.created_by.display_name)}</span>
      </div>
    </div>
    <div class="list-row-points"><span>${todo.points}</span><span class="muted">pts</span></div>
    ${
      writable && todo.status === "open"
        ? `<div class="list-row-actions">
             ${iHoldIt ? `<span class="takeover-slot"></span>` : ""}
             ${
               !todo.assigned_to
                 ? `<button class="btn btn-icon" data-action="claim" aria-label="Claim todo" title="Claim — assign this to me">${icons.handRaised}</button>`
                 : ""
             }
             ${
               isAdmin()
                 ? `<button class="btn btn-icon" data-action="reassign" aria-label="Reassign now" title="Reassign now — moves it instantly, no approval needed (for asking first, see the request icon on your own items)">${icons.swap}</button>`
                 : ""
             }
             <button class="btn btn-icon btn-danger" data-action="cancel" aria-label="Cancel todo">${icons.close}</button>
             <button class="btn btn-icon btn-primary" data-action="complete" aria-label="Complete todo">${icons.check}</button>
           </div>`
        : ""
    }
  `;

  if (iHoldIt) {
    row.querySelector(".takeover-slot").replaceWith(
      takeoverControl({
        requests: outgoingRequestsCache,
        kind: "todo",
        id: todo.id,
        label: todo.title,
        onChange: () => refreshTodos(container, writable),
      })
    );
  }

  if (writable && todo.status === "open" && !todo.assigned_to) {
    row.querySelector('[data-action="claim"]').addEventListener("click", async () => {
      try {
        await api.post(`${HB}/todos/${todo.id}/claim`);
        showToast(`Claimed "${todo.title}"`, "success");
        refreshTodos(container, writable);
      } catch {
        /* api.js already showed a toast (e.g. 409 if someone else just claimed it) */
      }
    });
  }

  if (writable && todo.status === "open" && isAdmin()) {
    row.querySelector('[data-action="reassign"]').addEventListener("click", () => {
      openReassignModal(container, todo, writable);
    });
  }

  if (writable && todo.status === "open") {
    row.querySelector('[data-action="complete"]').addEventListener("click", async () => {
      try {
        await api.post(`${HB}/todos/${todo.id}/complete`);
        showToast(`Completed "${todo.title}" (+${todo.points} pts)`, "success");
        refreshTodos(container, writable);
      } catch {
        /* api.js already showed a toast */
      }
    });
    row.querySelector('[data-action="cancel"]').addEventListener("click", async () => {
      const ok = await showConfirmDialog({
        title: "Cancel todo",
        message: `Cancel "${todo.title}"?`,
        confirmLabel: "Cancel todo",
        danger: true,
      });
      if (!ok) return;
      try {
        await api.post(`${HB}/todos/${todo.id}/cancel`);
        showToast("Todo cancelled", "success");
        refreshTodos(container, writable);
      } catch {
        /* api.js already showed a toast */
      }
    });
  }

  return row;
}

async function openReassignModal(container, todo, writable) {
  const users = assignableUsers(await loadUsers(true));

  const overlay = document.createElement("div");
  overlay.className = "modal-overlay";
  overlay.innerHTML = `
    <div class="modal" role="dialog" aria-modal="true">
      <div class="modal-header">
        <h2>Reassign</h2>
        <button class="btn btn-icon btn-ghost" id="modal-close" aria-label="Close">${icons.close}</button>
      </div>
      <div class="stack">
        <div class="field">
          <label for="ra-assignee">"${escapeHtml(todo.title)}" goes to</label>
          <select class="select" id="ra-assignee" ${users.length === 0 ? "disabled" : ""}>
            ${
              users.length === 0
                ? `<option value="">No eligible users (everyone's on break)</option>`
                : users
                    .map(
                      (u) =>
                        `<option value="${u.id}"${todo.assigned_to && u.id === todo.assigned_to.id ? " selected" : ""}>${escapeAttr(u.display_name)}</option>`
                    )
                    .join("")
            }
          </select>
        </div>
      </div>
      <div class="modal-footer">
        <button class="btn btn-primary grow" id="ra-save" ${users.length === 0 ? "disabled" : ""}>Reassign</button>
      </div>
    </div>
  `;
  document.body.appendChild(overlay);
  const close = () => overlay.remove();
  overlay.querySelector("#modal-close").addEventListener("click", close);
  overlay.addEventListener("click", (e) => {
    if (e.target === overlay) close();
  });

  overlay.querySelector("#ra-save").addEventListener("click", async () => {
    const assignedToId = Number(overlay.querySelector("#ra-assignee").value);
    try {
      await api.post(`${HB}/todos/${todo.id}/reassign`, { assigned_to_id: assignedToId });
      showToast("Reassigned", "success");
      close();
      refreshTodos(container, writable);
    } catch {
      /* api.js already showed a toast */
    }
  });
}

async function openTodoModal(container) {
  const [users, tasks, categories] = await Promise.all([loadUsers(true), loadTasks(), loadCategories()]);

  const overlay = document.createElement("div");
  overlay.className = "modal-overlay";
  overlay.innerHTML = `
    <div class="modal" role="dialog" aria-modal="true">
      <div class="modal-header">
        <h2>New todo</h2>
        <button class="btn btn-icon btn-ghost" id="modal-close" aria-label="Close">${icons.close}</button>
      </div>
      <div class="stack">
        <div class="field">
          <label>From task</label>
          <button type="button" class="btn btn-block" id="t-task-btn" style="justify-content: space-between;">
            <span id="t-task-label">Custom (one-off)</span>
            ${icons.chevronRight}
          </button>
        </div>
        <div class="field">
          <label for="t-title">Title</label>
          <input class="input" id="t-title" required />
        </div>
        <div class="field">
          <label for="t-description">Description</label>
          <textarea class="input" id="t-description" rows="2"></textarea>
        </div>
        <div class="field-row">
          <div class="field">
            <label for="t-points">Points</label>
            <input class="input" type="number" min="0" id="t-points" value="1" />
          </div>
          <div class="field">
            <label for="t-due">Due</label>
            <select class="select" id="t-due">
              <option value="">No due date</option>
              <option value="0" selected>Today</option>
              <option value="1">Tomorrow</option>
              <option value="3">In 3 days</option>
              <option value="7">In a week</option>
            </select>
          </div>
        </div>
        <div class="field">
          <label for="t-assignee">Request from</label>
          <select class="select" id="t-assignee">
            <option value="">Anyone</option>
            ${assignableUsers(users).map((u) => `<option value="${u.id}">${escapeAttr(u.display_name)}</option>`).join("")}
          </select>
        </div>
      </div>
      <div class="modal-footer">
        <button class="btn btn-primary grow" id="t-save">Post to board</button>
      </div>
    </div>
  `;
  document.body.appendChild(overlay);

  const close = () => overlay.remove();
  overlay.querySelector("#modal-close").addEventListener("click", close);
  overlay.addEventListener("click", (e) => {
    if (e.target === overlay) close();
  });
  overlay.querySelector("#t-title").focus();

  // Picking a task prefills title/description/points as a starting point
  // — the board item created is still a plain, independent TodoItem (not
  // linked back to the task), so it's fine to tweak these before posting.
  // A native <select> here turns into an unusably long, un-searchable
  // list on mobile once there are more than a handful of tasks — a
  // popup picker with search + category filtering stays usable at any
  // size (see openTaskPickerModal).
  overlay.querySelector("#t-task-btn").addEventListener("click", () => {
    openTaskPickerModal({
      tasks,
      categories,
      customOption: { label: "Custom (one-off)" },
      onSelect: (task) => {
        overlay.querySelector("#t-task-label").textContent = task ? task.name : "Custom (one-off)";
        overlay.querySelector("#t-title").value = task ? task.name : "";
        overlay.querySelector("#t-description").value = task ? task.description || "" : "";
        overlay.querySelector("#t-points").value = task ? task.points : 1;
      },
    });
  });

  overlay.querySelector("#t-save").addEventListener("click", async () => {
    const title = overlay.querySelector("#t-title").value.trim();
    if (!title) {
      showToast("Title is required", "warning");
      return;
    }
    const dueRaw = overlay.querySelector("#t-due").value;
    const assigneeRaw = overlay.querySelector("#t-assignee").value;

    const payload = {
      title,
      description: overlay.querySelector("#t-description").value.trim() || null,
      points: Number(overlay.querySelector("#t-points").value || 0),
      due_in_days: dueRaw === "" ? null : Number(dueRaw),
      assigned_to_id: assigneeRaw === "" ? null : Number(assigneeRaw),
    };

    try {
      await api.post(`${HB}/todos`, payload);
      showToast("Posted to the board", "success");
      close();
      state.status = "open";
      container.querySelectorAll("#status-chips .chip").forEach((c) => c.classList.toggle("chip-active", c.dataset.status === "open"));
      refreshTodos(container, true);
    } catch {
      /* api.js already showed a toast */
    }
  });
}

