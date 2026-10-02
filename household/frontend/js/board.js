import { CONFIG } from "./config.js";
import { api, fetchImageUrl } from "./api.js";
import { icons } from "./icons.js";
import { getCurrentUserInfo } from "./auth.js";
import { showToast } from "./toast.js";
import { showConfirmDialog } from "./confirmDialog.js";
import { escapeHtml, escapeAttr, dueBadge, initials } from "./util.js";

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

function canWrite() {
  const info = getCurrentUserInfo();
  return info && (info.role === "admin" || info.role === "user");
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

async function loadUsers() {
  if (!usersCache) {
    try {
      usersCache = await api.get(`${HB}/users`);
    } catch {
      usersCache = [];
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

async function refreshTodos(container, writable) {
  const root = container.querySelector("#todo-list");
  if (!root) return;
  root.innerHTML = `<div class="skeleton" style="height: 64px;"></div><div class="skeleton" style="height: 64px; margin-top: 8px;"></div>`;

  let todos;
  try {
    const qs = state.status ? `?status=${encodeURIComponent(state.status)}` : "";
    todos = await api.get(`${HB}/todos${qs}`);
  } catch {
    root.innerHTML = `<div class="empty-state">Couldn't load the todo board</div>`;
    return;
  }

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

  row.innerHTML = `
    <div class="list-row-body">
      <div class="list-row-title">${escapeHtml(todo.title)}</div>
      ${todo.description ? `<div class="muted" style="font-size: var(--font-size-xs);">${escapeHtml(todo.description)}</div>` : ""}
      <div class="list-row-meta">
        ${assignee}
        ${statusBadge}
        <span>by ${escapeHtml(todo.created_by.display_name)}</span>
      </div>
    </div>
    <div class="list-row-points"><span>${todo.points}</span><span class="muted">pts</span></div>
    ${
      writable && todo.status === "open"
        ? `<div class="list-row-actions">
             <button class="btn btn-icon btn-danger" data-action="cancel" aria-label="Cancel todo">${icons.close}</button>
             <button class="btn btn-icon btn-primary" data-action="complete" aria-label="Complete todo">${icons.check}</button>
           </div>`
        : ""
    }
  `;

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

async function openTodoModal(container) {
  const [users, tasks] = await Promise.all([loadUsers(), loadTasks()]);

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
          <label for="t-task">From task</label>
          <select class="select" id="t-task">
            <option value="">Custom (one-off)</option>
            ${tasks.map((t) => `<option value="${t.id}">${escapeAttr(t.name)}</option>`).join("")}
          </select>
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
            ${users.map((u) => `<option value="${u.id}">${escapeAttr(u.display_name)}</option>`).join("")}
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
  overlay.querySelector("#t-task").addEventListener("change", (e) => {
    const task = tasks.find((t) => String(t.id) === e.target.value);
    overlay.querySelector("#t-title").value = task ? task.name : "";
    overlay.querySelector("#t-description").value = task ? task.description || "" : "";
    overlay.querySelector("#t-points").value = task ? task.points : 1;
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
