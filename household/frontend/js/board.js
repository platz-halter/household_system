import { CONFIG } from "./config.js";
import { api, fetchImageUrl } from "./api.js";
import { icons } from "./icons.js";
import { getCurrentUserInfo } from "./auth.js";
import { showToast } from "./toast.js";
import { showConfirmDialog } from "./confirmDialog.js";
import { openTaskPickerModal } from "./taskPicker.js";
import { takeoverControl } from "./takeover.js";
import { openEventGroupPickerModal, openTriggerConfirmModal } from "./eventGroups.js";
import { escapeHtml, escapeAttr, dueBadge, initials, showSkeletonAfterDelay } from "./util.js";

const HB = CONFIG.HOUSEHOLD_BASE;

const STATUS_FILTERS = [
  { id: "open", label: "Open" },
  { id: "completed", label: "Completed" },
  { id: "cancelled", label: "Cancelled" },
  { id: "", label: "All" },
];

// Per-viewer display preference, not server state — wrapped in try/catch
// since a private-browsing/blocked-storage context can throw on either
// read or write (see artifact/storage guidance this codebase otherwise
// follows for localStorage). Defaults to grouped: the whole point of
// event groups is that "Dinner"'s tasks read as one occurrence, not
// scattered board rows.
function loadGroupByEventPref() {
  try {
    const v = localStorage.getItem("household.board.groupByEvent");
    return v === null ? true : v === "true";
  } catch {
    return true;
  }
}
function saveGroupByEventPref(value) {
  try {
    localStorage.setItem("household.board.groupByEvent", String(value));
  } catch {
    /* ignore — per-viewer convenience only */
  }
}

const state = { status: "open", groupByEvent: loadGroupByEventPref() };
let usersCache = null;
let tasksCache = null;
let categoriesCache = null;
let meCache = null;
// Last-fetched page of todos — kept so toggling "group by event" can
// re-render instantly without a refetch (grouping is purely a render-time
// concern; the status filter is the only thing that needs the server).
let todosCache = [];
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
    <div class="page${writable ? " page-dual-fab" : ""}">
      <div class="chip-row" id="status-chips" style="margin-bottom: var(--space-3);">
        ${STATUS_FILTERS.map((f) => `<span class="chip${state.status === f.id ? " chip-active" : ""}" data-status="${f.id}">${f.label}</span>`).join("")}
        <span class="chip${state.groupByEvent ? " chip-active" : ""}" id="group-toggle-chip">${icons.checklist} Group by event</span>
      </div>
      <div id="todo-list" class="stack"></div>
    </div>
    ${
      writable
        ? `<button class="fab-secondary" id="trigger-event-group-fab" aria-label="Trigger an event group" title="Trigger an event group">${icons.calendar}</button>
           <button class="fab" id="add-todo-fab" aria-label="New todo">${icons.plus}</button>`
        : ""
    }
  `;

  // Scoped to [data-status] — #group-toggle-chip now shares this same
  // row (user feedback: it used to sit on its own line below) but isn't
  // a status filter, so it must stay out of both this click handler and
  // the chip-active reset it does, or clicking it would overwrite
  // state.status with undefined and clear every status chip's active
  // state in the process.
  container.querySelectorAll("#status-chips .chip[data-status]").forEach((chip) => {
    chip.addEventListener("click", () => {
      state.status = chip.dataset.status;
      container.querySelectorAll("#status-chips .chip[data-status]").forEach((c) => c.classList.remove("chip-active"));
      chip.classList.add("chip-active");
      refreshTodos(container, writable);
    });
  });

  container.querySelector("#group-toggle-chip").addEventListener("click", (e) => {
    state.groupByEvent = !state.groupByEvent;
    saveGroupByEventPref(state.groupByEvent);
    e.currentTarget.classList.toggle("chip-active", state.groupByEvent);
    renderTodoList(container, writable);
  });

  if (writable) {
    container.querySelector("#add-todo-fab").addEventListener("click", () => openTodoModal(container));
    // Its own dedicated FAB rather than a button buried in the New Todo
    // modal's footer — user feedback called that "not intuitive and
    // hard to find." A direct entry point: straight to the group
    // picker, no detour through the todo form first.
    container.querySelector("#trigger-event-group-fab").addEventListener("click", () => {
      openEventGroupPickerModal({
        onSelect: (group) => {
          openTriggerConfirmModal(group, {
            onTriggered: () => refreshTodos(container, true),
          });
        },
      });
    });
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

  todosCache = todos;
  renderTodoList(container, writable);
}

// Re-renders from todosCache without refetching — used both after a real
// refresh and when the "group by event" toggle flips, since grouping is
// purely how this function lays out already-fetched rows.
function renderTodoList(container, writable) {
  const root = container.querySelector("#todo-list");
  if (!root) return;

  if (todosCache.length === 0) {
    root.innerHTML = `<div class="empty-state">${icons.board}<p style="margin-top: var(--space-2);">Nothing here</p></div>`;
    return;
  }

  root.innerHTML = "";
  // Every member of a run is pulled into ONE card, together, regardless
  // of where each one sits in todosCache's own order — a chain
  // descendant tagged with the same run usually spawns later (after its
  // root is created) and so would otherwise land far below its root in
  // a plain flat render. The card appears at the position of whichever
  // member comes FIRST in list order (usually a root); every later
  // member of that same run is skipped here since it's already inside
  // that card.
  const renderedRuns = new Set();
  todosCache.forEach((todo) => {
    if (state.groupByEvent && todo.event_group_run_id) {
      if (renderedRuns.has(todo.event_group_run_id)) return;
      renderedRuns.add(todo.event_group_run_id);
      const members = todosCache.filter((t) => t.event_group_run_id === todo.event_group_run_id);
      root.appendChild(eventCard(todo, members, container, writable));
      return;
    }
    root.appendChild(todoRow(todo, container, writable));
  });
  hydrateAvatars(root);
}

// One bordered card per EventGroupRun — so its members visually read as
// "belong together," not just a heading floating above an otherwise
// plain flat list (user feedback). Only ever shown while "group by
// event" is on; the bulk-delete button below lives here too, so it's
// only reachable in grouped view as well — flagged in the report, not
// silently decided.
function eventCard(firstTodo, members, container, writable) {
  const card = document.createElement("div");
  card.className = "event-card";
  card.innerHTML = `
    <div class="event-card-header">
      <div class="event-card-title-group">
        <span class="event-card-title">${escapeHtml(firstTodo.event_group_name || "Event")}</span>
        <span class="event-card-date">${formatGroupDate(firstTodo.event_group_triggered_at)}</span>
      </div>
      ${writable ? `<button class="btn btn-icon btn-ghost" data-action="delete-event" aria-label="Delete this event" title="Delete this event">${icons.trash}</button>` : ""}
    </div>
    <div class="event-card-body stack"></div>
  `;
  const body = card.querySelector(".event-card-body");
  members.forEach((m) => body.appendChild(todoRow(m, container, writable)));

  if (writable) {
    card.querySelector('[data-action="delete-event"]').addEventListener("click", () => {
      openDeleteEventModal(container, writable, firstTodo.event_group_run_id, firstTodo.event_group_name);
    });
  }
  return card;
}

// Bulk-delete everything from one event group run. A real delete, not a
// cancel (user asked for "delete," and a soft cancel would just
// reappear under the Cancelled/All filters) — crud.
// delete_event_group_run_todos keeps anything already completed rather
// than sweeping it away, so the warning has to name exactly what WILL
// go, from the same server-side computation that performs the delete,
// not a client-side guess from todosCache (which wouldn't know about a
// chain descendant excluded from the group's own tag).
async function openDeleteEventModal(container, writable, runId, groupName) {
  let preview;
  try {
    preview = await api.get(`${HB}/event-group-runs/${runId}/delete-preview`);
  } catch {
    return; // api.js already showed a toast
  }
  if (preview.to_delete.length === 0) {
    showToast("Nothing to delete — everything in this event is already completed", "warning");
    return;
  }
  const names = preview.to_delete.map((t) => t.title).join(", ");
  const keptNote = preview.to_keep.length
    ? ` ${preview.to_keep.length} completed task${preview.to_keep.length === 1 ? "" : "s"} will be kept.`
    : "";
  const ok = await showConfirmDialog({
    title: "Delete event",
    message: `Delete "${groupName || "this event"}"? This permanently removes: ${names}.${keptNote}`,
    confirmLabel: "Delete",
    danger: true,
  });
  if (!ok) return;
  try {
    const result = await api.post(`${HB}/event-group-runs/${runId}/delete`);
    showToast(`Deleted ${result.to_delete.length} task${result.to_delete.length === 1 ? "" : "s"}`, "success");
    refreshTodos(container, writable);
  } catch {
    /* api.js already showed a toast */
  }
}

function formatGroupDate(iso) {
  if (!iso) return "";
  return new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric" }).format(new Date(iso));
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
  // "Chained from," not "After" — chain children now spawn alongside
  // their parent, not once it's completed, so this row can easily be
  // sitting open at the same time as the parent it's chained from, not
  // strictly after it.
  const chainBadge = todo.chain_parent_task_name
    ? `<span class="badge badge-neutral">Chained from: ${escapeHtml(todo.chain_parent_task_name)}</span>`
    : "";
  // Shown regardless of the "group by event" toggle — when grouping is
  // off there's no cluster header to carry this information, and even
  // when it's on, a row can end up far from its header (see
  // renderTodoList), so the badge is the only reliable place to see it.
  const eventBadge = todo.event_group_name
    ? `<span class="badge badge-info">${escapeHtml(todo.event_group_name)}</span>`
    : "";

  // Also requires status === "open": the `.takeover-slot` markup below
  // only renders inside the open-only actions block, so without this a
  // completed/cancelled todo you still happen to hold (nothing clears
  // assigned_to on completion/cancel) would try to replaceWith() a slot
  // that was never rendered — found live by filtering the Board to
  // "Completed" while signed in as whoever held one.
  const iHoldIt =
    writable && meCache && todo.status === "open" && todo.assigned_to && todo.assigned_to.id === meCache.id;

  row.innerHTML = `
    <div class="list-row-body">
      <div class="list-row-title">${escapeHtml(todo.title)}</div>
      ${todo.description ? `<div class="muted" style="font-size: var(--font-size-xs);">${escapeHtml(todo.description)}</div>` : ""}
      <div class="list-row-meta">
        ${assignee}
        ${statusBadge}
        ${chainBadge}
        ${eventBadge}
        <span>${todo.created_by ? `by ${escapeHtml(todo.created_by.display_name)}` : "Scheduled"}</span>
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
      // Cancelling deletes any still-open chain task(s) this todo
      // pre-spawned at its own creation (crud.cancel_todo) — warn by
      // name before doing it, rather than silently removing them.
      let chainChildren = [];
      try {
        chainChildren = await api.get(`${HB}/todos/${todo.id}/chain-children`, { silent: true });
      } catch {
        chainChildren = [];
      }
      const message = chainChildren.length
        ? `Cancel "${todo.title}"? This will also delete its chain task${chainChildren.length === 1 ? "" : "s"}: ${chainChildren.map((c) => c.title).join(", ")}.`
        : `Cancel "${todo.title}"?`;
      const ok = await showConfirmDialog({
        title: "Cancel todo",
        message,
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
        <div class="field hidden" id="t-chain-field">
          <label class="row"><input type="checkbox" id="t-spawn-chain" checked /> <span>Also create its chain task(s) now</span></label>
          <p class="muted" id="t-chain-preview" style="font-size: var(--font-size-xs); margin: 4px 0 0 24px;"></p>
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
  // Set when a real task is picked (not "Custom") — sent as
  // source_task_id so its chain children spawn immediately alongside
  // this todo (crud._spawn_chain_children_on_creation), the same as an
  // event group's own root todos. Stays set even if the prefilled
  // title/points get edited afterward — it's still logically an
  // instance of that task's occurrence.
  let selectedSourceTaskId = null;
  const chainFieldEl = overlay.querySelector("#t-chain-field");
  const spawnChainCheckbox = overlay.querySelector("#t-spawn-chain");
  const chainPreviewEl = overlay.querySelector("#t-chain-preview");
  // Discards a stale fetch's result if picking task A, then quickly
  // picking task B before A's own GET /chain-links lands — without
  // this, A's chain task names could render under B's checkbox.
  let chainLinksSeq = 0;
  function renderChainPreview(links) {
    chainPreviewEl.textContent = spawnChainCheckbox.checked
      ? `Will also create: ${links.map((l) => l.child_task_name).join(", ")}`
      : "";
  }
  overlay.querySelector("#t-task-btn").addEventListener("click", () => {
    openTaskPickerModal({
      tasks,
      categories,
      customOption: { label: "Custom (one-off)" },
      onSelect: async (task) => {
        selectedSourceTaskId = task ? task.id : null;
        overlay.querySelector("#t-task-label").textContent = task ? task.name : "Custom (one-off)";
        overlay.querySelector("#t-title").value = task ? task.name : "";
        overlay.querySelector("#t-description").value = task ? task.description || "" : "";
        overlay.querySelector("#t-points").value = task ? task.points : 1;

        // The checkbox only matters — and only shows — when the picked
        // task actually has a chain task to skip; nothing to deactivate
        // otherwise. Defaults checked (spawn) every time a new task is
        // picked, so an earlier uncheck doesn't silently carry over to
        // a different task.
        spawnChainCheckbox.checked = true;
        chainFieldEl.classList.add("hidden");
        chainPreviewEl.textContent = "";
        const seq = ++chainLinksSeq;
        if (task) {
          let links = [];
          try {
            links = await api.get(`${HB}/tasks/${task.id}/chain-links`, { silent: true });
          } catch {
            links = [];
          }
          if (seq !== chainLinksSeq) return; // a newer pick already landed
          chainFieldEl.classList.toggle("hidden", links.length === 0);
          renderChainPreview(links);
          spawnChainCheckbox.onchange = () => renderChainPreview(links);
        }
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
      source_task_id: selectedSourceTaskId,
      spawn_chain_children: spawnChainCheckbox.checked,
    };

    try {
      await api.post(`${HB}/todos`, payload);
      showToast("Posted to the board", "success");
      close();
      state.status = "open";
      container.querySelectorAll("#status-chips .chip[data-status]").forEach((c) => c.classList.toggle("chip-active", c.dataset.status === "open"));
      refreshTodos(container, true);
    } catch {
      /* api.js already showed a toast */
    }
  });
}

