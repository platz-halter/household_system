import { CONFIG } from "./config.js";
import { api } from "./api.js";
import { icons } from "./icons.js";
import { getCurrentUserInfo } from "./auth.js";
import { showToast } from "./toast.js";
import { showConfirmDialog } from "./confirmDialog.js";
import { openTaskPickerModal } from "./taskPicker.js";
import { openTriggerConfirmModal } from "./eventGroups.js";
import { escapeHtml, escapeAttr, showSkeletonAfterDelay, WEEKDAY_LABELS } from "./util.js";

const HB = CONFIG.HOUSEHOLD_BASE;

function canWrite() {
  const info = getCurrentUserInfo();
  return info && (info.role === "admin" || info.role === "user");
}

let categoriesCache = [];
let tasksCache = [];
let eventGroupsCache = [];
// Used only to LABEL an event group's "At ..." hour (both the schedule
// badge on its list row and the create/edit modal's own picker) — the
// hour itself is stored/interpreted server-side (crud._event_group_due);
// this is purely so the admin isn't shown "09:00" with no indication of
// which timezone that actually means.
let timezoneCache = "UTC";

// Persists across re-renders within the same page load (same pattern as
// board.js's status filter / home.js's search state) — switching to
// Calendar, visiting another page via the bottom nav, then coming back
// shouldn't reset either the chosen view or which month was showing.
const taskViewState = { view: "list" };
let calendarMonth = new Date(new Date().getFullYear(), new Date().getMonth(), 1);

export async function renderTasks(container) {
  const writable = canWrite();

  container.innerHTML = `
    <div class="page${writable ? " page-dual-fab" : ""}">
      <div class="section-heading">
        <h2>Categories</h2>
        ${writable ? `<button class="btn btn-icon" id="add-category-btn" aria-label="New category">${icons.plus}</button>` : ""}
      </div>
      <div class="chip-row" id="category-list" style="margin-bottom: var(--space-2);"></div>

      <div class="section-heading">
        <h2>Event Groups</h2>
      </div>
      <p class="muted" style="font-size: var(--font-size-xs); margin-top: 0;">
        One tap creates several tasks at once — "Dinner" can post "Set the table" and "Fill
        dishwasher" together, chain tasks included.
      </p>
      <div id="event-group-list" class="stack" style="margin-bottom: var(--space-2);"></div>

      <div class="section-heading">
        <h2>Tasks</h2>
        <div class="chip-row" id="task-view-toggle">
          <span class="chip${taskViewState.view === "list" ? " chip-active" : ""}" data-view="list">List</span>
          <span class="chip${taskViewState.view === "calendar" ? " chip-active" : ""}" data-view="calendar">Calendar</span>
        </div>
      </div>
      <div id="task-view-root"></div>
    </div>
    ${
      writable
        ? `<button class="fab-secondary" id="add-event-group-fab" aria-label="New event group" title="New event group">${icons.calendar}</button>
           <button class="fab" id="add-task-fab" aria-label="New task">${icons.plus}</button>`
        : ""
    }
  `;

  if (writable) {
    container.querySelector("#add-category-btn").addEventListener("click", () => openCategoryModal(container, writable));
    container.querySelector("#add-task-fab").addEventListener("click", () => openTaskModal(container, writable));
    // A dedicated FAB, consistent with the Board's own "trigger an event
    // group" one — previously a full-width inline button, itself a fix
    // for an earlier "hard to find" icon-only button; this round's
    // feedback was that THAT button still didn't feel intuitive, so it
    // moved again, this time to match the Board's new pattern exactly.
    container.querySelector("#add-event-group-fab").addEventListener("click", () => openEventGroupModal(container, writable));
  }

  container.querySelectorAll("#task-view-toggle .chip").forEach((chip) => {
    chip.addEventListener("click", () => {
      taskViewState.view = chip.dataset.view;
      container.querySelectorAll("#task-view-toggle .chip").forEach((c) => c.classList.toggle("chip-active", c === chip));
      renderTaskView(container, writable);
    });
  });

  try {
    timezoneCache = (await api.get(`${HB}/settings`, { silent: true })).timezone;
  } catch {
    timezoneCache = "UTC";
  }
  await loadCategories(container, writable);
  await loadEventGroups(container, writable);
  await renderTaskView(container, writable);
}

// Unfiltered (incl. inactive tasks), independent of which Tasks sub-view
// (list vs. calendar) is currently showing — the Event Group modal's
// root-task picker needs this even when the page loaded straight into
// Calendar view, where loadTasks() below never runs (it targets
// #task-list, which only exists in list view).
async function ensureTasksCache() {
  try {
    tasksCache = await api.get(`${HB}/tasks`);
  } catch {
    tasksCache = tasksCache || [];
  }
  return tasksCache;
}

async function renderTaskView(container, writable) {
  const root = container.querySelector("#task-view-root");
  if (!root) return;

  if (taskViewState.view === "calendar") {
    root.innerHTML = `
      <div class="row-between" style="margin-bottom: var(--space-3);">
        <button class="btn btn-icon" id="cal-prev" aria-label="Previous month">${icons.chevronLeft}</button>
        <h3 id="cal-month-label" style="margin: 0;"></h3>
        <button class="btn btn-icon" id="cal-next" aria-label="Next month">${icons.chevronRight}</button>
      </div>
      <div id="cal-monthly-list" style="margin-bottom: var(--space-3);"></div>
      <div class="cal-daylabels" id="cal-daylabels"></div>
      <div id="cal-grid" class="cal-grid"></div>
    `;
    root.querySelector("#cal-prev").addEventListener("click", () => {
      calendarMonth = new Date(calendarMonth.getFullYear(), calendarMonth.getMonth() - 1, 1);
      renderCalendar(root);
    });
    root.querySelector("#cal-next").addEventListener("click", () => {
      calendarMonth = new Date(calendarMonth.getFullYear(), calendarMonth.getMonth() + 1, 1);
      renderCalendar(root);
    });
    await renderCalendar(root);
  } else {
    root.innerHTML = `<div id="task-list" class="stack"></div>`;
    await loadTasks(container, writable);
  }
}

function isSameLocalDay(a, b) {
  return a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();
}

// A month grid of every WEEKLY task scheduled on each day, plus a
// summary strip for MONTHLY ones (which have no specific day of the
// month to place them on — just "sometime this month"). DAILY tasks
// show on every cell too, dimmed (.cal-day-task-daily) so a weekly
// task — the one actually scheduled for that specific day — still
// stands out; daily tasks used to be left off entirely on the
// reasoning that "on every cell by definition" wouldn't tell anyone
// anything a plain list doesn't already, but a user still expects a
// task they set to Daily to actually show up as scheduled somewhere on
// this page. Leaves out chain-child tasks regardless of recurrence —
// they have no independent schedule of their own (see TaskChainLink).
async function renderCalendar(root) {
  const labelEl = root.querySelector("#cal-month-label");
  const monthlyRoot = root.querySelector("#cal-monthly-list");
  const dayLabelsRoot = root.querySelector("#cal-daylabels");
  const gridRoot = root.querySelector("#cal-grid");
  if (!gridRoot) return;

  labelEl.textContent = new Intl.DateTimeFormat(undefined, { month: "long", year: "numeric" }).format(calendarMonth);

  let weekStart = 0;
  try {
    const settings = await api.get(`${HB}/settings`);
    weekStart = settings.week_start_weekday ?? 0;
  } catch {
    weekStart = 0;
  }
  dayLabelsRoot.innerHTML = WEEKDAY_LABELS.slice(weekStart)
    .concat(WEEKDAY_LABELS.slice(0, weekStart))
    .map((l) => `<span>${l}</span>`)
    .join("");

  let tasks;
  try {
    tasks = await api.get(`${HB}/tasks?active=true`);
  } catch {
    gridRoot.innerHTML = `<div class="empty-state">Couldn't load tasks</div>`;
    return;
  }

  const dailyTasks = tasks.filter((t) => t.recurrence === "daily" && !t.is_chain_child);
  const weeklyTasks = tasks.filter((t) => t.recurrence === "weekly" && !t.is_chain_child);
  const monthlyTasks = tasks.filter((t) => t.recurrence === "monthly" && !t.is_chain_child);

  monthlyRoot.innerHTML = monthlyTasks.length
    ? `<div class="list-row-meta" style="flex-wrap: wrap;">
         <span class="muted" style="font-size: var(--font-size-xs);">This month:</span>
         ${monthlyTasks.map((t) => `<span class="badge badge-neutral">${escapeHtml(t.name)}</span>`).join("")}
       </div>`
    : "";

  const year = calendarMonth.getFullYear();
  const month = calendarMonth.getMonth();
  const firstOfMonth = new Date(year, month, 1);
  const daysInMonth = new Date(year, month + 1, 0).getDate();
  const mondayFirst = (firstOfMonth.getDay() + 6) % 7; // JS getDay(): 0=Sun..6=Sat -> 0=Mon..6=Sun
  const leadingBlanks = (mondayFirst - weekStart + 7) % 7;
  const today = new Date();

  const cells = Array(leadingBlanks).fill(null);
  for (let d = 1; d <= daysInMonth; d++) cells.push(d);
  while (cells.length % 7 !== 0) cells.push(null);

  gridRoot.innerHTML = cells
    .map((d) => {
      if (d === null) return `<div class="cal-day cal-day-empty"></div>`;
      const dateObj = new Date(year, month, d);
      const weekday = (dateObj.getDay() + 6) % 7; // 0=Mon..6=Sun, matches Task.weekdays
      const weeklyDayTasks = weeklyTasks.filter((t) => (t.weekdays || []).includes(weekday));
      return `
        <div class="cal-day${isSameLocalDay(dateObj, today) ? " cal-day-today" : ""}">
          <div class="cal-day-number">${d}</div>
          ${weeklyDayTasks.map((t) => `<div class="cal-day-task" title="${escapeAttr(t.name)} (${t.points} pts)">${escapeHtml(t.name)}</div>`).join("")}
          ${dailyTasks.map((t) => `<div class="cal-day-task cal-day-task-daily" title="${escapeAttr(t.name)} (${t.points} pts) — every day">${escapeHtml(t.name)}</div>`).join("")}
        </div>
      `;
    })
    .join("");
}

async function loadCategories(container, writable) {
  const root = container.querySelector("#category-list");
  if (!root) return;
  try {
    categoriesCache = await api.get(`${HB}/categories`);
  } catch {
    categoriesCache = [];
  }

  if (categoriesCache.length === 0) {
    root.innerHTML = `<span class="muted" style="font-size: var(--font-size-sm);">No categories yet</span>`;
    return;
  }
  root.innerHTML = categoriesCache
    .map((c) => `<span class="chip" data-id="${c.id}">${c.icon ? escapeHtml(c.icon) + " " : ""}${escapeHtml(c.name)}</span>`)
    .join("");

  if (writable) {
    root.querySelectorAll(".chip").forEach((chip) => {
      chip.addEventListener("click", () => {
        const cat = categoriesCache.find((c) => String(c.id) === chip.dataset.id);
        if (cat) openCategoryModal(container, writable, cat);
      });
    });
  }
}

async function loadTasks(container, writable) {
  const root = container.querySelector("#task-list");
  if (!root) return;
  const cancelSkeleton = showSkeletonAfterDelay(root, `<div class="skeleton" style="height: 64px;"></div>`);

  let tasks;
  try {
    tasks = await api.get(`${HB}/tasks`);
  } catch {
    cancelSkeleton();
    root.innerHTML = `<div class="empty-state">Couldn't load tasks</div>`;
    return;
  }
  cancelSkeleton();

  if (tasks.length === 0) {
    root.innerHTML = `<div class="empty-state">No tasks yet${writable ? " — add one below" : ""}</div>`;
    return;
  }

  tasksCache = tasks;
  root.innerHTML = "";
  tasks.forEach((task) => root.appendChild(taskRow(task, container, writable)));
}

function scheduleLabel(task) {
  if (task.recurrence === "weekly") {
    return task.weekdays && task.weekdays.length ? task.weekdays.map((w) => WEEKDAY_LABELS[w]).join(" ") : "Weekly";
  }
  if (task.recurrence === "monthly") return "Monthly";
  return "Every day";
}

async function loadEventGroups(container, writable) {
  const root = container.querySelector("#event-group-list");
  if (!root) return;

  let groups;
  try {
    groups = await api.get(`${HB}/event-groups`);
  } catch {
    root.innerHTML = `<div class="empty-state">Couldn't load event groups</div>`;
    return;
  }
  eventGroupsCache = groups;

  if (groups.length === 0) {
    root.innerHTML = writable
      ? `<div class="empty-state">
           <p style="margin: 0 0 var(--space-3);">No event groups yet</p>
           <button type="button" class="btn btn-primary" id="event-group-empty-cta">${icons.plus}<span>Create your first one</span></button>
         </div>`
      : `<div class="empty-state"><p style="margin:0;">No event groups yet</p></div>`;
    if (writable) {
      root.querySelector("#event-group-empty-cta").addEventListener("click", () => openEventGroupModal(container, writable));
    }
    return;
  }
  root.innerHTML = "";
  groups.forEach((group) => root.appendChild(eventGroupRow(group, container, writable)));
}

function scheduleSummary(group) {
  if (!group.schedule_recurrence) return null;
  const when =
    group.schedule_recurrence === "daily"
      ? "Every day"
      : (group.schedule_weekdays || []).map((d) => WEEKDAY_LABELS[d]).join(" ");
  return `${when} · ${String(group.schedule_hour).padStart(2, "0")}:00 ${timezoneCache}`;
}

function eventGroupRow(group, container, writable) {
  const row = document.createElement("div");
  row.className = "list-row";
  const schedule = scheduleSummary(group);
  row.innerHTML = `
    <div class="list-row-body">
      <div class="list-row-title">${escapeHtml(group.name)}</div>
      <div class="list-row-meta">
        <span>${group.roots.length} task${group.roots.length === 1 ? "" : "s"}</span>
        ${schedule ? `<span class="badge badge-info">${escapeHtml(schedule)}</span>` : ""}
      </div>
    </div>
    ${writable ? `<button type="button" class="btn btn-icon btn-primary" data-action="trigger" aria-label="Create today's tasks for ${escapeAttr(group.name)}" title="Create today's tasks">${icons.send}</button>` : ""}
  `;

  if (writable) {
    row.querySelector('[data-action="trigger"]').addEventListener("click", (e) => {
      e.stopPropagation();
      openTriggerConfirmModal(group);
    });
    row.addEventListener("click", () => openEventGroupModal(container, writable, group));
  } else {
    row.style.cursor = "default";
  }
  return row;
}

function taskRow(task, container, writable) {
  const row = document.createElement("div");
  row.className = "list-row";
  const catLabel = task.categories.map((c) => (c.icon ? `${c.icon} ${c.name}` : c.name)).join(" · ");
  const schedule = scheduleLabel(task);

  row.innerHTML = `
    <div class="list-row-body">
      <div class="list-row-title">${escapeHtml(task.name)} ${!task.active ? `<span class="badge badge-neutral">Inactive</span>` : ""} ${task.is_chain_child ? `<span class="badge badge-neutral">Chained</span>` : ""}</div>
      <div class="list-row-meta">
        ${catLabel ? `<span>${escapeHtml(catLabel)}</span>` : ""}
        <span>${escapeHtml(schedule)}${task.times_per_day > 1 ? ` · ${task.times_per_day}×/day` : ""}</span>
        ${task.ramp_up_enabled ? `<span class="badge badge-info">+${task.ramp_up_bonus_points} bonus</span>` : ""}
      </div>
    </div>
    <div class="list-row-points"><span>${task.points}</span><span class="muted">pts</span></div>
  `;

  if (writable) {
    row.addEventListener("click", () => openTaskModal(container, writable, task));
  } else {
    row.style.cursor = "default";
  }
  return row;
}

function openModalShell(titleText) {
  const overlay = document.createElement("div");
  overlay.className = "modal-overlay";
  overlay.innerHTML = `
    <div class="modal" role="dialog" aria-modal="true">
      <div class="modal-header">
        <h2>${escapeHtml(titleText)}</h2>
        <button class="btn btn-icon btn-ghost" id="modal-close" aria-label="Close">${icons.close}</button>
      </div>
      <div id="modal-body"></div>
    </div>
  `;
  document.body.appendChild(overlay);
  const close = () => overlay.remove();
  overlay.querySelector("#modal-close").addEventListener("click", close);
  overlay.addEventListener("click", (e) => {
    if (e.target === overlay) close();
  });
  return { overlay, body: overlay.querySelector("#modal-body"), close };
}

function openCategoryModal(container, writable, category = null) {
  const { body, close } = openModalShell(category ? "Edit category" : "New category");

  body.innerHTML = `
    <div class="stack">
      <div class="field">
        <label for="c-name">Name</label>
        <input class="input" id="c-name" value="${escapeAttr(category?.name || "")}" required />
      </div>
      <div class="field">
        <label for="c-icon">Icon (emoji, optional)</label>
        <input class="input" id="c-icon" maxlength="4" value="${escapeAttr(category?.icon || "")}" placeholder="🧹" />
      </div>
    </div>
    <div class="modal-footer">
      ${category ? `<button class="btn btn-danger" id="c-delete">${icons.trash}</button>` : ""}
      <button class="btn btn-primary grow" id="c-save">Save</button>
    </div>
  `;

  body.querySelector("#c-save").addEventListener("click", async () => {
    const name = body.querySelector("#c-name").value.trim();
    if (!name) {
      showToast("Name is required", "warning");
      return;
    }
    const payload = { name, icon: body.querySelector("#c-icon").value.trim() || null };
    try {
      if (category) {
        await api.patch(`${HB}/categories/${category.id}`, payload);
      } else {
        await api.post(`${HB}/categories`, payload);
      }
      showToast("Category saved", "success");
      close();
      loadCategories(container, writable);
      loadTasks(container, writable);
    } catch {
      /* api.js already showed a toast */
    }
  });

  if (category) {
    body.querySelector("#c-delete").addEventListener("click", async () => {
      const ok = await showConfirmDialog({
        title: "Delete category",
        message: `Delete "${category.name}"? Tasks keep their other categories.`,
        confirmLabel: "Delete",
        danger: true,
      });
      if (!ok) return;
      try {
        await api.del(`${HB}/categories/${category.id}`);
        showToast("Category deleted", "success");
        close();
        loadCategories(container, writable);
        loadTasks(container, writable);
      } catch {
        /* api.js already showed a toast */
      }
    });
  }
}

// `group` is null for "New event group". Roots are tracked as a plain
// ordered array (not a Set) so position is preserved on save, same as
// the chain-link picker's "pick = add, right away" flow — there's no
// separate confirm step for adding a root either.
async function openEventGroupModal(container, writable, group = null) {
  await ensureTasksCache();
  const timezone = timezoneCache;

  // A saved root can go stale (deactivated, or chained under another
  // task) since the group was last saved — split those out as
  // "flagged" so they're shown but clearly marked for removal, rather
  // than either hiding them silently or letting a save attempt 400
  // against crud._validate_event_group_roots.
  let selectedRoots = [];
  let flaggedRoots = [];
  if (group) {
    for (const r of group.roots) {
      const task = tasksCache.find((t) => t.id === r.task_id);
      if (task && task.active && !task.is_chain_child) {
        selectedRoots.push({ id: r.task_id, name: r.task_name });
      } else {
        flaggedRoots.push({ id: r.task_id, name: r.task_name });
      }
    }
  }
  const excludedIds = new Set(group?.excluded_task_ids || []);
  // Narrows excludedIds to ids the live preview actually confirmed exist
  // right now — populated by every successful refreshPreview() call, and
  // used to drop stale exclusions on save (see the save handler below).
  let lastPreviewTaskIds = new Set();
  let previewSeq = 0;

  const { body, close } = openModalShell(group ? "Edit event group" : "New event group");

  body.innerHTML = `
    <div class="stack">
      <div class="field">
        <label for="eg-name">Name</label>
        <input class="input" id="eg-name" value="${escapeAttr(group?.name || "")}" required />
      </div>
      <div class="field">
        <label>Tasks in this group</label>
        <div class="chip-row" id="eg-roots" style="margin-bottom: var(--space-2);"></div>
        ${
          writable
            ? `<button type="button" class="btn btn-ghost btn-block" id="eg-add-root-btn" style="justify-content: center;">
                 ${icons.plus}<span>Add a task…</span>
               </button>`
            : ""
        }
      </div>
      <div class="field">
        <label>Preview</label>
        <p class="muted" style="font-size: var(--font-size-xs); margin-top: 0;">
          Everything below is created when this group is triggered: each task above, right away,
          plus any task already chained from it. Uncheck a chained task to leave it out of this
          group — it still gets created, just without this group's tag.
        </p>
        <div id="eg-preview-list" class="stack"></div>
      </div>
      <div class="field">
        <label class="row">
          <input type="checkbox" id="eg-schedule-enabled" ${group?.schedule_recurrence ? "checked" : ""} ${writable ? "" : "disabled"} />
          <span>Also trigger this automatically</span>
        </label>
        <div id="eg-schedule-fields" style="margin-top: var(--space-2); ${group?.schedule_recurrence ? "" : "display:none;"}">
          <label for="eg-schedule-recurrence">Repeats</label>
          <select class="select" id="eg-schedule-recurrence" ${writable ? "" : "disabled"}>
            <option value="daily" ${(group?.schedule_recurrence ?? "daily") === "daily" ? "selected" : ""}>Every day</option>
            <option value="weekly" ${group?.schedule_recurrence === "weekly" ? "selected" : ""}>Specific weekdays</option>
          </select>
          <div class="weekday-picker" id="eg-schedule-weekdays" style="margin-top: var(--space-2); ${group?.schedule_recurrence === "weekly" ? "" : "display:none;"}">
            ${WEEKDAY_LABELS.map((label, i) => `<div class="weekday-pill${(group?.schedule_weekdays || []).includes(i) ? " on" : ""}" data-day="${i}">${label}</div>`).join("")}
          </div>
          <label for="eg-schedule-hour" style="margin-top: var(--space-2); display: block;">At (${escapeHtml(timezone)})</label>
          <select class="select" id="eg-schedule-hour" ${writable ? "" : "disabled"}>
            ${Array.from({ length: 24 }, (_, h) => `<option value="${h}" ${(group?.schedule_hour ?? 18) === h ? "selected" : ""}>${String(h).padStart(2, "0")}:00</option>`).join("")}
          </select>
          <p class="muted" style="font-size: var(--font-size-xs); margin-top: var(--space-2);">
            ${escapeHtml(timezone)}, same as the weekly nudge's schedule on the Admin panel — change
            the timezone itself there, not here. Already triggering it by hand today counts, too —
            the automatic trigger skips a day it's already run on, whether that run was manual or
            scheduled.
          </p>
        </div>
      </div>
    </div>
    <div class="modal-footer">
      ${group && writable ? `<button class="btn btn-danger" id="eg-delete">${icons.trash}</button>` : ""}
      ${writable ? `<button class="btn btn-primary grow" id="eg-save">Save</button>` : ""}
    </div>
  `;

  function renderRootChips() {
    const root = body.querySelector("#eg-roots");
    if (selectedRoots.length === 0 && flaggedRoots.length === 0) {
      root.innerHTML = `<span class="muted" style="font-size: var(--font-size-sm);">No tasks yet — add one below</span>`;
      return;
    }
    root.innerHTML = [
      ...selectedRoots.map(
        (r) => `
        <span class="chip chip-active" data-id="${r.id}">
          ${escapeHtml(r.name)}
          ${writable ? `<button type="button" aria-label="Remove ${escapeAttr(r.name)}" data-remove="${r.id}">&times;</button>` : ""}
        </span>`
      ),
      ...flaggedRoots.map(
        (r) => `
        <span class="chip" data-id="${r.id}" title="No longer eligible — will be removed when you save" style="opacity: 0.6;">
          ${escapeHtml(r.name)} ⚠
          ${writable ? `<button type="button" aria-label="Remove ${escapeAttr(r.name)}" data-remove="${r.id}">&times;</button>` : ""}
        </span>`
      ),
    ].join("");
    root.querySelectorAll("button[data-remove]").forEach((btn) => {
      btn.addEventListener("click", (e) => {
        e.stopPropagation();
        const id = Number(btn.dataset.remove);
        selectedRoots = selectedRoots.filter((r) => r.id !== id);
        flaggedRoots = flaggedRoots.filter((r) => r.id !== id);
        renderRootChips();
        refreshPreview();
      });
    });
  }

  function renderPreviewList(items) {
    const previewRoot = body.querySelector("#eg-preview-list");
    if (items.length === 0) {
      previewRoot.innerHTML = `<span class="muted" style="font-size: var(--font-size-sm);">Nothing to preview</span>`;
      return;
    }
    previewRoot.innerHTML = items
      .map((item) => {
        if (item.is_root) {
          return `
          <div class="eg-preview-row">
            <span class="eg-preview-title">${escapeHtml(item.task_name)}</span>
            <span class="badge badge-success">Created now</span>
          </div>`;
        }
        const checked = !excludedIds.has(item.task_id);
        return `
          <div class="eg-preview-row eg-preview-descendant">
            <label class="row" style="gap: var(--space-2); flex: 1; min-width: 0;">
              <input type="checkbox" data-task-id="${item.task_id}" ${checked ? "checked" : ""} ${writable ? "" : "disabled"} />
              <span class="eg-preview-title">${escapeHtml(item.task_name)}</span>
            </label>
            <span class="badge badge-success">Created now</span>
            <span class="badge badge-neutral">Chained from: ${escapeHtml(item.parent_task_name)}</span>
          </div>`;
      })
      .join("");

    if (!writable) return;
    previewRoot.querySelectorAll("input[type=checkbox][data-task-id]").forEach((cb) => {
      cb.addEventListener("change", () => {
        const id = Number(cb.dataset.taskId);
        if (cb.checked) excludedIds.delete(id);
        else excludedIds.add(id);
        // The one-level chain cap still allows the SAME task to be
        // chained from two different roots in this group (A->X, B->X) —
        // both checkboxes are the same EventGroupExclusion row, so they
        // must always agree rather than drifting independently.
        previewRoot.querySelectorAll(`input[data-task-id="${id}"]`).forEach((other) => {
          other.checked = cb.checked;
        });
      });
    });
  }

  async function refreshPreview() {
    const previewRoot = body.querySelector("#eg-preview-list");
    const rootIds = selectedRoots.map((r) => r.id);
    if (rootIds.length === 0) {
      previewRoot.innerHTML = `<span class="muted" style="font-size: var(--font-size-sm);">Add a task above to see what this group creates</span>`;
      lastPreviewTaskIds = new Set();
      return;
    }
    const seq = ++previewSeq;
    previewRoot.innerHTML = `<div class="skeleton" style="height: 40px;"></div>`;
    let items;
    try {
      items = await api.post(`${HB}/event-groups/preview`, {
        root_task_ids: rootIds,
        excluded_task_ids: [...excludedIds],
      });
    } catch {
      if (seq === previewSeq) previewRoot.innerHTML = `<div class="empty-state">Couldn't load preview</div>`;
      return;
    }
    if (seq !== previewSeq) return; // a newer request already landed — this one is stale
    lastPreviewTaskIds = new Set(items.map((i) => i.task_id));
    renderPreviewList(items);
  }

  const selectedScheduleWeekdays = new Set(group?.schedule_weekdays || []);

  if (writable) {
    const scheduleEnabledEl = body.querySelector("#eg-schedule-enabled");
    const scheduleFieldsEl = body.querySelector("#eg-schedule-fields");
    const scheduleRecurrenceEl = body.querySelector("#eg-schedule-recurrence");
    const scheduleWeekdaysEl = body.querySelector("#eg-schedule-weekdays");

    scheduleEnabledEl.addEventListener("change", () => {
      scheduleFieldsEl.style.display = scheduleEnabledEl.checked ? "" : "none";
    });
    scheduleRecurrenceEl.addEventListener("change", () => {
      scheduleWeekdaysEl.style.display = scheduleRecurrenceEl.value === "weekly" ? "" : "none";
    });
    scheduleWeekdaysEl.querySelectorAll(".weekday-pill").forEach((pill) => {
      pill.addEventListener("click", () => {
        const day = Number(pill.dataset.day);
        if (selectedScheduleWeekdays.has(day)) selectedScheduleWeekdays.delete(day);
        else selectedScheduleWeekdays.add(day);
        pill.classList.toggle("on");
      });
    });

    body.querySelector("#eg-add-root-btn").addEventListener("click", async () => {
      await ensureTasksCache();
      const takenIds = new Set([...selectedRoots, ...flaggedRoots].map((r) => r.id));
      const eligible = tasksCache.filter((t) => t.active && !t.is_chain_child && !takenIds.has(t.id));
      openTaskPickerModal({
        tasks: eligible,
        categories: categoriesCache,
        title: "Add a task to this group",
        emptyMessage: "No eligible tasks left to add",
        onSelect: (task) => {
          if (!task) return;
          selectedRoots.push({ id: task.id, name: task.name });
          renderRootChips();
          refreshPreview();
        },
      });
    });
  }

  renderRootChips();
  await refreshPreview();

  if (!writable) return;

  body.querySelector("#eg-save").addEventListener("click", async () => {
    const name = body.querySelector("#eg-name").value.trim();
    if (!name) {
      showToast("Name is required", "warning");
      return;
    }
    if (selectedRoots.length === 0) {
      showToast("Add at least one task to this group", "warning");
      return;
    }
    const scheduleEnabled = body.querySelector("#eg-schedule-enabled").checked;
    const scheduleRecurrence = scheduleEnabled ? body.querySelector("#eg-schedule-recurrence").value : null;
    const scheduleWeekdays = scheduleRecurrence === "weekly" ? [...selectedScheduleWeekdays].sort((a, b) => a - b) : null;
    if (scheduleRecurrence === "weekly" && scheduleWeekdays.length === 0) {
      showToast("Pick at least one weekday for a weekly schedule", "warning");
      return;
    }
    // Drop any exclusion the live preview didn't just confirm still
    // exists (e.g. a chain link that's since been removed) — otherwise
    // it could silently reappear if that task gets chained again later.
    const excludedTaskIds = [...excludedIds].filter((id) => lastPreviewTaskIds.has(id));
    const payload = {
      name,
      root_task_ids: selectedRoots.map((r) => r.id),
      excluded_task_ids: excludedTaskIds,
      schedule_recurrence: scheduleRecurrence,
      schedule_weekdays: scheduleWeekdays,
      schedule_hour: Number(body.querySelector("#eg-schedule-hour").value),
    };
    try {
      if (group) {
        await api.patch(`${HB}/event-groups/${group.id}`, payload);
      } else {
        await api.post(`${HB}/event-groups`, payload);
      }
      showToast("Event group saved", "success");
      close();
      loadEventGroups(container, writable);
    } catch {
      /* api.js already showed a toast */
    }
  });

  if (group) {
    body.querySelector("#eg-delete").addEventListener("click", async () => {
      const ok = await showConfirmDialog({
        title: "Delete event group",
        message: `Delete "${group.name}"? Todos it already created stay on the board, just ungrouped.`,
        confirmLabel: "Delete",
        danger: true,
      });
      if (!ok) return;
      try {
        await api.del(`${HB}/event-groups/${group.id}`);
        showToast("Event group deleted", "success");
        close();
        loadEventGroups(container, writable);
      } catch {
        /* api.js already showed a toast */
      }
    });
  }
}

async function initChainLinksSection(body, task, writable) {
  const listEl = body.querySelector("#chain-link-list");
  const childBtn = body.querySelector("#chain-child-btn");
  const sameUserEl = body.querySelector("#chain-same-user-select");
  let eligibleChildren = [];

  // Picking a task in the popup immediately adds the link — there's no
  // separate "confirm" step. There used to be one (pick, then press a
  // dedicated "Add" button), but that read as "picking already saved
  // it" — a user would pick a task, then press the modal's main Save
  // button (which only persists this TASK's own fields) assuming the
  // chain link had already been attached. It hadn't, so the task stayed
  // unchained with no error shown. Collapsing pick-and-add into one
  // action removes that failure mode entirely rather than just
  // explaining it better.
  async function addChainLink(childTask) {
    if (!childTask) return;
    try {
      await api.post(`${HB}/tasks/${task.id}/chain-links`, {
        child_task_id: childTask.id,
        same_user: sameUserEl.value === "true",
      });
      showToast("Chain task added", "success");
      await refresh();
    } catch {
      /* api.js already showed a toast */
    }
  }

  // A task that's already someone else's chain task can't itself chain
  // further tasks (chaining is capped at one level — see
  // crud.create_chain_link) — shown as an explanation instead of just
  // letting the "add" control fail server-side.
  async function renderCappedNotice() {
    // `.hidden` CSS class, not the native `hidden` attribute — `.btn`'s
    // own `display: inline-flex` otherwise wins the cascade over the
    // browser's built-in `[hidden]` rule at equal specificity, and the
    // button stays visually shown despite the attribute being set (see
    // notifications.js's refreshNotificationBadge for the same fix,
    // caught the same way).
    childBtn.classList.add("hidden");
    sameUserEl.classList.add("hidden");
    // refresh() (and so this) can run more than once — e.g. removing an
    // existing link re-triggers it — so reuse one notice element rather
    // than inserting a new <p> after childBtn every time.
    let notice = body.querySelector("#chain-capped-notice");
    if (!notice) {
      notice = document.createElement("p");
      notice.id = "chain-capped-notice";
      notice.className = "muted";
      notice.style.fontSize = "var(--font-size-xs)";
      childBtn.insertAdjacentElement("afterend", notice);
    }
    let parents = [];
    try {
      parents = await api.get(`${HB}/tasks/${task.id}/chain-parents`);
    } catch {
      /* fall through with an empty list — still correct, just less specific */
    }
    const names = parents.map((p) => p.parent_task_name).join(", ");
    notice.textContent = names
      ? `"${task.name}" is already chained from: ${names}. A chained task can't chain further tasks itself.`
      : `"${task.name}" is already chained from another task and can't chain further tasks itself.`;
  }

  async function refresh() {
    let links;
    try {
      links = await api.get(`${HB}/tasks/${task.id}/chain-links`);
    } catch {
      listEl.innerHTML = `<div class="empty-state">Couldn't load chain tasks</div>`;
      return;
    }

    listEl.innerHTML = links.length
      ? links
          .map(
            (link) => `
        <div class="list-row" data-link-id="${link.id}">
          <div class="list-row-body">
            <div class="list-row-title">${escapeHtml(link.child_task_name)}</div>
            <div class="list-row-meta"><span>${link.same_user ? "Same person" : "Different person"}</span></div>
          </div>
          ${writable ? `<button class="btn btn-icon btn-ghost chain-remove-btn" aria-label="Remove">${icons.trash}</button>` : ""}
        </div>`
          )
          .join("")
      : `<span class="muted" style="font-size: var(--font-size-sm);">No chained tasks yet</span>`;

    if (writable) {
      listEl.querySelectorAll(".chain-remove-btn").forEach((btn) => {
        btn.addEventListener("click", async () => {
          const row = btn.closest("[data-link-id]");
          const linkId = row.dataset.linkId;
          try {
            await api.del(`${HB}/tasks/${task.id}/chain-links/${linkId}`);
            showToast("Chain task removed", "success");
            await refresh();
          } catch {
            /* api.js already showed a toast */
          }
        });
      });
    }

    if (task.is_chain_child) {
      await renderCappedNotice();
      return;
    }

    // Excludes this task itself, any task already chained to it, and any
    // task that's already someone else's chain child — chaining is
    // capped at one level (see crud.create_chain_link), so a task that's
    // already a chain child can't be picked as a child here either.
    const linkedChildIds = new Set(links.map((l) => l.child_task_id));
    eligibleChildren = tasksCache.filter(
      (t) => t.id !== task.id && !linkedChildIds.has(t.id) && !t.is_chain_child
    );
    childBtn.disabled = !writable || eligibleChildren.length === 0;
    childBtn.innerHTML =
      eligibleChildren.length === 0
        ? `<span>No eligible tasks</span>`
        : `${icons.plus}<span>Add a chain task…</span>`;
  }

  if (writable && !task.is_chain_child) {
    childBtn.addEventListener("click", () => {
      openTaskPickerModal({
        tasks: eligibleChildren,
        categories: categoriesCache,
        title: "Choose a chain task",
        emptyMessage: "No eligible tasks match",
        onSelect: addChainLink,
      });
    });
  } else if (!task.is_chain_child) {
    childBtn.disabled = true;
    sameUserEl.disabled = true;
  }

  await refresh();
}

function openTaskModal(container, writable, task = null) {
  const selectedCats = new Set((task?.categories || []).map((c) => c.id));
  const selectedWeekdays = new Set(task?.weekdays || []);
  const recurrence = task?.recurrence || "daily";

  const { body, close } = openModalShell(task ? "Edit task" : "New task");

  body.innerHTML = `
    <div class="stack">
      <div class="field">
        <label for="f-name">Name</label>
        <input class="input" id="f-name" value="${escapeAttr(task?.name || "")}" required />
      </div>
      <div class="field">
        <label for="f-description">Description</label>
        <textarea class="input" id="f-description" rows="2">${escapeHtml(task?.description || "")}</textarea>
      </div>
      <div class="field-row">
        <div class="field">
          <label for="f-points">Points</label>
          <input class="input" type="number" min="0" id="f-points" value="${task?.points ?? 1}" />
        </div>
        <div class="field">
          <label for="f-times">Times per day</label>
          <input class="input" type="number" min="1" id="f-times" value="${task?.times_per_day ?? 1}" />
        </div>
      </div>

      <div class="field">
        <label for="f-recurrence">Repeats</label>
        <select class="select" id="f-recurrence">
          <option value="daily" ${recurrence === "daily" ? "selected" : ""}>Daily — a standing chore, every day</option>
          <option value="weekly" ${recurrence === "weekly" ? "selected" : ""}>Weekly — specific weekdays</option>
          <option value="monthly" ${recurrence === "monthly" ? "selected" : ""}>Monthly</option>
        </select>
        <p class="muted" style="font-size: var(--font-size-xs); margin-top: 4px;">
          Only weekly/monthly tasks are handed out by the balancing tool (Admin panel) — a
          daily task stays a standing chore anyone can log any day.
        </p>
        <div class="weekday-picker" id="f-weekdays" style="margin-top: var(--space-2); ${recurrence === "weekly" ? "" : "display:none;"}">
          ${WEEKDAY_LABELS.map((label, i) => `<div class="weekday-pill${selectedWeekdays.has(i) ? " on" : ""}" data-day="${i}">${label}</div>`).join("")}
        </div>
      </div>

      <div class="field">
        <label>Categories</label>
        <div class="chip-row" id="f-categories">
          ${
            categoriesCache.length
              ? categoriesCache
                  .map(
                    (c) =>
                      `<span class="chip${selectedCats.has(c.id) ? " chip-active" : ""}" data-id="${c.id}">${c.icon ? escapeHtml(c.icon) + " " : ""}${escapeHtml(c.name)}</span>`
                  )
                  .join("")
              : `<span class="muted" style="font-size: var(--font-size-sm);">None yet — add one above</span>`
          }
        </div>
      </div>

      <div class="field">
        <label class="row"><input type="checkbox" id="f-ramp-up" ${task?.ramp_up_enabled ? "checked" : ""} /> <span>Ramp-up bonus for a solo streak</span></label>
        <div class="field" id="f-ramp-up-points" style="margin-top: var(--space-2); ${task?.ramp_up_enabled ? "" : "display:none;"}">
          <label for="f-bonus">Bonus points</label>
          <input class="input" type="number" min="0" id="f-bonus" value="${task?.ramp_up_bonus_points ?? 0}" />
        </div>
      </div>

      <div class="field">
        <label class="row"><input type="checkbox" id="f-active" ${task?.active !== false ? "checked" : ""} /> <span>Active</span></label>
      </div>

      ${
        task
          ? `<div class="field">
        <label>Chain tasks</label>
        <p class="muted" style="font-size: var(--font-size-xs); margin-top: 0;">
          When "${escapeHtml(task.name)}" is completed, each chained task below is spawned onto
          the board as a one-off. "Same person" assigns it directly to whoever just completed this
          one; "different person" hands it to whoever the balancer says is fairest, never the
          completer. Picking a task below adds it right away — there's no separate save step.
        </p>
        <div class="stack" id="chain-link-list" style="margin-top: var(--space-2);"></div>
        <div class="stack" style="margin-top: var(--space-2); gap: var(--space-2);">
          <select class="select" id="chain-same-user-select">
            <option value="false">Different person</option>
            <option value="true">Same person</option>
          </select>
          <button type="button" class="btn btn-ghost btn-block" id="chain-child-btn" style="justify-content: center;">
            ${icons.plus}<span>Add a chain task…</span>
          </button>
        </div>
      </div>`
          : ""
      }
    </div>
    <div class="modal-footer">
      ${task ? `<button class="btn btn-danger" id="f-delete">${icons.trash}</button>` : ""}
      <button class="btn btn-primary grow" id="f-save">Save</button>
    </div>
  `;

  const weekdayPicker = body.querySelector("#f-weekdays");
  body.querySelector("#f-recurrence").addEventListener("change", (e) => {
    weekdayPicker.style.display = e.target.value === "weekly" ? "" : "none";
  });

  body.querySelectorAll(".weekday-pill").forEach((pill) => {
    pill.addEventListener("click", () => {
      const day = Number(pill.dataset.day);
      if (selectedWeekdays.has(day)) selectedWeekdays.delete(day);
      else selectedWeekdays.add(day);
      pill.classList.toggle("on");
    });
  });

  body.querySelectorAll("#f-categories .chip").forEach((chip) => {
    chip.addEventListener("click", () => {
      const id = Number(chip.dataset.id);
      if (selectedCats.has(id)) selectedCats.delete(id);
      else selectedCats.add(id);
      chip.classList.toggle("chip-active");
    });
  });

  const rampCheckbox = body.querySelector("#f-ramp-up");
  const rampPointsField = body.querySelector("#f-ramp-up-points");
  rampCheckbox.addEventListener("change", () => {
    rampPointsField.style.display = rampCheckbox.checked ? "" : "none";
  });

  if (task) {
    initChainLinksSection(body, task, writable);
  }

  body.querySelector("#f-save").addEventListener("click", async () => {
    const name = body.querySelector("#f-name").value.trim();
    if (!name) {
      showToast("Name is required", "warning");
      return;
    }
    const newRecurrence = body.querySelector("#f-recurrence").value;
    const weekdays = newRecurrence === "weekly" ? [...selectedWeekdays].sort((a, b) => a - b) : null;
    if (newRecurrence === "weekly" && weekdays.length === 0) {
      showToast("Pick at least one weekday for a weekly task", "warning");
      return;
    }

    const payload = {
      name,
      description: body.querySelector("#f-description").value.trim() || null,
      points: Number(body.querySelector("#f-points").value || 0),
      active: body.querySelector("#f-active").checked,
      recurrence: newRecurrence,
      times_per_day: Number(body.querySelector("#f-times").value || 1),
      weekdays,
      ramp_up_enabled: rampCheckbox.checked,
      ramp_up_bonus_points: Number(body.querySelector("#f-bonus").value || 0),
      category_ids: [...selectedCats],
    };

    try {
      if (task) {
        await api.patch(`${HB}/tasks/${task.id}`, payload);
      } else {
        await api.post(`${HB}/tasks`, payload);
      }
      showToast("Task saved", "success");
      close();
      loadTasks(container, writable);
    } catch {
      /* api.js already showed a toast */
    }
  });

  if (task) {
    body.querySelector("#f-delete").addEventListener("click", async () => {
      const ok = await showConfirmDialog({
        title: "Delete task",
        message: `Delete "${task.name}"? Past points earned from it are kept.`,
        confirmLabel: "Delete",
        danger: true,
      });
      if (!ok) return;
      try {
        await api.del(`${HB}/tasks/${task.id}`);
        showToast("Task deleted", "success");
        close();
        loadTasks(container, writable);
      } catch {
        /* api.js already showed a toast */
      }
    });
  }
}
