import { CONFIG } from "./config.js";
import { api, fetchImageUrl } from "./api.js";
import { icons } from "./icons.js";
import { getCurrentUserInfo } from "./auth.js";
import { showToast } from "./toast.js";
import { showConfirmDialog } from "./confirmDialog.js";
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
    todos = await api.get(`${HB}/todos${qs}`);
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
             ${
               !todo.assigned_to
                 ? `<button class="btn btn-icon" data-action="claim" aria-label="Claim todo" title="Claim — assign this to me">${icons.handRaised}</button>`
                 : ""
             }
             <button class="btn btn-icon btn-danger" data-action="cancel" aria-label="Cancel todo">${icons.close}</button>
             <button class="btn btn-icon btn-primary" data-action="complete" aria-label="Complete todo">${icons.check}</button>
           </div>`
        : ""
    }
  `;

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
  const [users, tasks, categories] = await Promise.all([loadUsers(), loadTasks(), loadCategories()]);

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
  // A native <select> here turns into an unusably long, un-searchable
  // list on mobile once there are more than a handful of tasks — a
  // popup picker with search + category filtering stays usable at any
  // size (see openTaskPickerModal).
  overlay.querySelector("#t-task-btn").addEventListener("click", () => {
    openTaskPickerModal({
      tasks,
      categories,
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

// A full-screen popup for picking a task, stacked on top of whatever
// modal opened it (same nested-overlay pattern confirmDialog.js already
// uses) — search + category chips keep it usable with a list of any
// size, unlike a native <select> on mobile.
function openTaskPickerModal({ tasks, categories, onSelect }) {
  const overlay = document.createElement("div");
  overlay.className = "modal-overlay";
  overlay.innerHTML = `
    <div class="modal" role="dialog" aria-modal="true">
      <div class="modal-header">
        <h2>Choose a task</h2>
        <button class="btn btn-icon btn-ghost" id="tp-close" aria-label="Close">${icons.close}</button>
      </div>
      <div class="search-bar" style="margin-bottom: var(--space-3);">
        ${icons.search}
        <input type="search" id="tp-search" placeholder="Search tasks…" />
      </div>
      <div class="chip-row" id="tp-categories" style="margin-bottom: var(--space-3);"></div>
      <div id="tp-list" class="stack" style="max-height: 55vh; overflow-y: auto;"></div>
    </div>
  `;
  document.body.appendChild(overlay);

  const close = () => overlay.remove();
  overlay.querySelector("#tp-close").addEventListener("click", close);
  overlay.addEventListener("click", (e) => {
    if (e.target === overlay) close();
  });

  const pickerState = { q: "", categoryId: "" };

  const catRoot = overlay.querySelector("#tp-categories");
  const chips = [
    { id: "", label: "All" },
    ...categories.map((c) => ({ id: String(c.id), label: c.icon ? `${c.icon} ${c.name}` : c.name })),
  ];
  catRoot.innerHTML = chips
    .map(
      (c) =>
        `<span class="chip${pickerState.categoryId === c.id ? " chip-active" : ""}" data-cat="${escapeAttr(c.id)}">${escapeHtml(c.label)}</span>`
    )
    .join("");
  catRoot.querySelectorAll(".chip").forEach((chip) => {
    chip.addEventListener("click", () => {
      pickerState.categoryId = chip.dataset.cat;
      catRoot.querySelectorAll(".chip").forEach((c) => c.classList.toggle("chip-active", c === chip));
      renderList();
    });
  });

  let searchDebounce = null;
  overlay.querySelector("#tp-search").addEventListener("input", (e) => {
    clearTimeout(searchDebounce);
    searchDebounce = setTimeout(() => {
      pickerState.q = e.target.value.trim().toLowerCase();
      renderList();
    }, 200);
  });

  function renderList() {
    const listRoot = overlay.querySelector("#tp-list");
    let filtered = tasks;
    if (pickerState.q) filtered = filtered.filter((t) => t.name.toLowerCase().includes(pickerState.q));
    if (pickerState.categoryId) {
      filtered = filtered.filter((t) => t.categories.some((c) => String(c.id) === pickerState.categoryId));
    }

    listRoot.innerHTML = "";

    const customRow = document.createElement("button");
    customRow.type = "button";
    customRow.className = "list-row";
    customRow.innerHTML = `<div class="list-row-body"><div class="list-row-title">Custom (one-off)</div></div>`;
    customRow.addEventListener("click", () => {
      onSelect(null);
      close();
    });
    listRoot.appendChild(customRow);

    if (filtered.length === 0) {
      const empty = document.createElement("div");
      empty.className = "empty-state";
      empty.textContent = "No tasks match";
      listRoot.appendChild(empty);
      return;
    }

    filtered.forEach((t) => {
      const row = document.createElement("button");
      row.type = "button";
      row.className = "list-row";
      const catLabel = t.categories.map((c) => (c.icon ? `${c.icon} ${c.name}` : c.name)).join(" · ");
      row.innerHTML = `
        <div class="list-row-body">
          <div class="list-row-title">${escapeHtml(t.name)}</div>
          ${catLabel ? `<div class="list-row-meta"><span>${escapeHtml(catLabel)}</span></div>` : ""}
        </div>
        <div class="list-row-points"><span>${t.points}</span><span class="muted">pts</span></div>
      `;
      row.addEventListener("click", () => {
        onSelect(t);
        close();
      });
      listRoot.appendChild(row);
    });
  }

  renderList();
}
