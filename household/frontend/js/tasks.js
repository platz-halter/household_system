import { CONFIG } from "./config.js";
import { api } from "./api.js";
import { icons } from "./icons.js";
import { getCurrentUserInfo } from "./auth.js";
import { showToast } from "./toast.js";
import { showConfirmDialog } from "./confirmDialog.js";
import { openTaskPickerModal } from "./taskPicker.js";
import { openTriggerConfirmModal } from "./eventGroups.js";
import { escapeHtml, escapeAttr, showSkeletonAfterDelay, WEEKDAY_LABELS } from "./util.js";
import { t, getLocale } from "./i18n.js";
import { invalidateAllTasksCache } from "./home.js";

const HB = CONFIG.HOUSEHOLD_BASE;

function canWrite() {
  const info = getCurrentUserInfo();
  return info && (info.role === "admin" || info.role === "user");
}

function isAdmin() {
  const info = getCurrentUserInfo();
  return Boolean(info && info.role === "admin");
}

let categoriesCache = [];
let tasksCache = [];
let usersCache = [];
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
        <h2>${escapeHtml(t("tasks.categories_heading"))}</h2>
        ${writable ? `<button class="btn btn-icon" id="add-category-btn" aria-label="${escapeAttr(t("tasks.new_category_label"))}">${icons.plus}</button>` : ""}
      </div>
      <div class="chip-row" id="category-list" style="margin-bottom: var(--space-2);"></div>

      <div class="section-heading">
        <h2>${escapeHtml(t("tasks.event_groups_heading"))}</h2>
      </div>
      <p class="muted" style="font-size: var(--font-size-xs); margin-top: 0;">
        ${escapeHtml(t("tasks.event_groups_desc"))}
      </p>
      <div id="event-group-list" class="stack" style="margin-bottom: var(--space-2);"></div>

      <div class="section-heading">
        <h2>${escapeHtml(t("tasks.tasks_heading"))}</h2>
        <div class="chip-row" id="task-view-toggle">
          <span class="chip${taskViewState.view === "list" ? " chip-active" : ""}" data-view="list">${escapeHtml(t("tasks.view_list"))}</span>
          <span class="chip${taskViewState.view === "calendar" ? " chip-active" : ""}" data-view="calendar">${escapeHtml(t("tasks.view_calendar"))}</span>
        </div>
      </div>
      <div id="task-view-root"></div>
    </div>
    ${
      writable
        ? `<button class="fab-secondary" id="add-event-group-fab" aria-label="${escapeAttr(t("tasks.new_event_group_label"))}" title="${escapeAttr(t("tasks.new_event_group_label"))}">${icons.calendar}</button>
           <button class="fab" id="add-task-fab" aria-label="${escapeAttr(t("tasks.new_task_label"))}">${icons.plus}</button>`
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

// `force` re-fetches even if cached — called right before opening the
// task modal (same reasoning as board.js's own loadUsers(true) before
// its reassign picker), since on_break/role can change between page
// load and the moment someone opens the "always assign to" picker.
async function loadUsers(force = false) {
  if (!usersCache.length || force) {
    try {
      usersCache = await api.get(`${HB}/users`);
    } catch {
      usersCache = usersCache || [];
    }
  }
  return usersCache;
}

// Who the "always assign to" picker offers — a viewer can never
// complete anything (can_write-gated), same reasoning as every other
// assignment path's own viewer exclusion (see CLAUDE.md's "On-break AND
// viewer exclusion from assignment"). Deliberately NOT filtered by
// on_break, unlike board.js's assignableUsers() — a pin is a standing
// agreement that should stay visible (and keep showing as selected)
// even while its owner is temporarily on break; the backend already
// leaves a pinned task unassigned rather than handing it to someone
// else for exactly that case.
function pinnableUsers(users) {
  return users.filter((u) => u.role !== "viewer");
}

async function renderTaskView(container, writable) {
  const root = container.querySelector("#task-view-root");
  if (!root) return;

  if (taskViewState.view === "calendar") {
    root.innerHTML = `
      <div class="row-between" style="margin-bottom: var(--space-3);">
        <button class="btn btn-icon" id="cal-prev" aria-label="${escapeAttr(t("tasks.prev_month"))}">${icons.chevronLeft}</button>
        <h3 id="cal-month-label" style="margin: 0;"></h3>
        <button class="btn btn-icon" id="cal-next" aria-label="${escapeAttr(t("tasks.next_month"))}">${icons.chevronRight}</button>
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

  labelEl.textContent = new Intl.DateTimeFormat(getLocale(), { month: "long", year: "numeric" }).format(calendarMonth);

  let weekStart = 0;
  try {
    const settings = await api.get(`${HB}/settings`);
    weekStart = settings.week_start_weekday ?? 0;
  } catch {
    weekStart = 0;
  }
  const weekdayLabels = WEEKDAY_LABELS();
  dayLabelsRoot.innerHTML = weekdayLabels
    .slice(weekStart)
    .concat(weekdayLabels.slice(0, weekStart))
    .map((l) => `<span>${escapeHtml(l)}</span>`)
    .join("");

  let tasks;
  try {
    tasks = await api.get(`${HB}/tasks?active=true`);
  } catch {
    gridRoot.innerHTML = `<div class="empty-state">${escapeHtml(t("common.couldnt_load_tasks"))}</div>`;
    return;
  }

  const dailyTasks = tasks.filter((task) => task.recurrence === "daily" && !task.is_chain_child);
  const weeklyTasks = tasks.filter((task) => task.recurrence === "weekly" && !task.is_chain_child);
  const monthlyTasks = tasks.filter((task) => task.recurrence === "monthly" && !task.is_chain_child);

  monthlyRoot.innerHTML = monthlyTasks.length
    ? `<div class="list-row-meta" style="flex-wrap: wrap;">
         <span class="muted" style="font-size: var(--font-size-xs);">${escapeHtml(t("tasks.this_month_label"))}</span>
         ${monthlyTasks.map((task) => `<span class="badge badge-neutral">${escapeHtml(task.name)}</span>`).join("")}
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
      const weeklyDayTasks = weeklyTasks.filter((task) => (task.weekdays || []).includes(weekday));
      return `
        <div class="cal-day${isSameLocalDay(dateObj, today) ? " cal-day-today" : ""}">
          <div class="cal-day-number">${d}</div>
          ${weeklyDayTasks.map((task) => `<div class="cal-day-task" title="${escapeAttr(task.name)} (${task.points} ${escapeAttr(t("common.pts"))})">${escapeHtml(task.name)}</div>`).join("")}
          ${dailyTasks.map((task) => `<div class="cal-day-task cal-day-task-daily" title="${escapeAttr(task.name)} (${task.points} ${escapeAttr(t("common.pts"))}) — ${escapeAttr(t("common.recurrence_daily"))}">${escapeHtml(task.name)}</div>`).join("")}
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
    root.innerHTML = `<span class="muted" style="font-size: var(--font-size-sm);">${escapeHtml(t("tasks.no_categories_yet"))}</span>`;
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
    root.innerHTML = `<div class="empty-state">${escapeHtml(t("common.couldnt_load_tasks"))}</div>`;
    return;
  }
  cancelSkeleton();

  if (tasks.length === 0) {
    root.innerHTML = `<div class="empty-state">${escapeHtml(writable ? t("tasks.no_tasks_yet_add") : t("tasks.no_tasks_yet"))}</div>`;
    return;
  }

  tasksCache = tasks;
  root.innerHTML = "";
  tasks.forEach((task) => root.appendChild(taskRow(task, container, writable)));
}

function scheduleLabel(task) {
  const weekdayLabels = WEEKDAY_LABELS();
  if (task.recurrence === "weekly") {
    return task.weekdays && task.weekdays.length ? task.weekdays.map((w) => weekdayLabels[w]).join(" ") : t("common.recurrence_weekly");
  }
  if (task.recurrence === "monthly") return t("common.recurrence_monthly");
  if (task.recurrence === "manual") return t("tasks.manual_option");
  return t("common.recurrence_daily");
}

async function loadEventGroups(container, writable) {
  const root = container.querySelector("#event-group-list");
  if (!root) return;

  let groups;
  try {
    groups = await api.get(`${HB}/event-groups`);
  } catch {
    root.innerHTML = `<div class="empty-state">${escapeHtml(t("tasks.couldnt_load_event_groups"))}</div>`;
    return;
  }
  eventGroupsCache = groups;

  if (groups.length === 0) {
    root.innerHTML = writable
      ? `<div class="empty-state">
           <p style="margin: 0 0 var(--space-3);">${escapeHtml(t("tasks.no_event_groups_yet"))}</p>
           <button type="button" class="btn btn-primary" id="event-group-empty-cta">${icons.plus}<span>${escapeHtml(t("tasks.create_first_one"))}</span></button>
         </div>`
      : `<div class="empty-state"><p style="margin:0;">${escapeHtml(t("tasks.no_event_groups_yet"))}</p></div>`;
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
  const weekdayLabels = WEEKDAY_LABELS();
  const when =
    group.schedule_recurrence === "daily"
      ? t("common.recurrence_daily")
      : (group.schedule_weekdays || []).map((d) => weekdayLabels[d]).join(" ");
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
        <span>${escapeHtml(t("common.task_count", { n: group.roots.length, count: group.roots.length }))}</span>
        ${schedule ? `<span class="badge badge-info">${escapeHtml(schedule)}</span>` : ""}
      </div>
    </div>
    ${writable ? `<button type="button" class="btn btn-icon btn-primary" data-action="trigger" aria-label="${escapeAttr(t("tasks.create_label", { name: group.name }))}" title="${escapeAttr(t("tasks.create_title"))}">${icons.send}</button>` : ""}
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
      <div class="list-row-title">${escapeHtml(task.name)} ${!task.active ? `<span class="badge badge-neutral">${escapeHtml(t("tasks.inactive_badge"))}</span>` : ""} ${task.is_chain_child ? `<span class="badge badge-neutral">${escapeHtml(t("common.chained_badge"))}</span>` : ""}</div>
      <div class="list-row-meta">
        ${catLabel ? `<span>${escapeHtml(catLabel)}</span>` : ""}
        <span>${escapeHtml(schedule)}${task.times_per_day > 1 ? ` · ${escapeHtml(t("common.times_per_day", { n: task.times_per_day }))}` : ""}</span>
        ${task.ramp_up_enabled ? `<span class="badge badge-info">${escapeHtml(t("common.bonus_badge", { n: task.ramp_up_bonus_points }))}</span>` : ""}
        ${task.pinned_user ? `<span class="badge badge-info">${escapeHtml(t("tasks.pinned_badge", { name: task.pinned_user.display_name }))}</span>` : ""}
      </div>
    </div>
    <div class="list-row-points"><span>${task.points}</span><span class="muted">${escapeHtml(t("common.pts"))}</span></div>
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
        <button class="btn btn-icon btn-ghost" id="modal-close" aria-label="${escapeAttr(t("common.close"))}">${icons.close}</button>
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
  const { body, close } = openModalShell(category ? t("tasks.edit_category_title") : t("tasks.new_category_title"));

  body.innerHTML = `
    <div class="stack">
      <div class="field">
        <label for="c-name">${escapeHtml(t("tasks.name_label"))}</label>
        <input class="input" id="c-name" value="${escapeAttr(category?.name || "")}" required />
      </div>
      <div class="field">
        <label for="c-icon">${escapeHtml(t("tasks.icon_label"))}</label>
        <input class="input" id="c-icon" maxlength="4" value="${escapeAttr(category?.icon || "")}" placeholder="🧹" />
      </div>
    </div>
    <div class="modal-footer">
      ${category ? `<button class="btn btn-danger" id="c-delete">${icons.trash}</button>` : ""}
      <button class="btn btn-primary grow" id="c-save">${escapeHtml(t("common.save"))}</button>
    </div>
  `;

  body.querySelector("#c-save").addEventListener("click", async () => {
    const name = body.querySelector("#c-name").value.trim();
    if (!name) {
      showToast(t("common.name_required"), "warning");
      return;
    }
    const payload = { name, icon: body.querySelector("#c-icon").value.trim() || null };
    try {
      if (category) {
        await api.patch(`${HB}/categories/${category.id}`, payload);
      } else {
        await api.post(`${HB}/categories`, payload);
      }
      showToast(t("tasks.category_saved"), "success");
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
        title: t("tasks.delete_category_title"),
        message: t("tasks.delete_category_message", { name: category.name }),
        confirmLabel: t("common.delete"),
        danger: true,
      });
      if (!ok) return;
      try {
        await api.del(`${HB}/categories/${category.id}`);
        showToast(t("tasks.category_deleted"), "success");
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
  const weekdayLabels = WEEKDAY_LABELS();

  // A saved root can go stale (deactivated, or chained under another
  // task) since the group was last saved — split those out as
  // "flagged" so they're shown but clearly marked for removal, rather
  // than either hiding them silently or letting a save attempt 400
  // against crud._validate_event_group_roots.
  let selectedRoots = [];
  let flaggedRoots = [];
  if (group) {
    for (const r of group.roots) {
      const task = tasksCache.find((task2) => task2.id === r.task_id);
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

  const { body, close } = openModalShell(group ? t("tasks.edit_event_group_title") : t("tasks.new_event_group_title"));

  body.innerHTML = `
    <div class="stack">
      <div class="field">
        <label for="eg-name">${escapeHtml(t("tasks.name_label"))}</label>
        <input class="input" id="eg-name" value="${escapeAttr(group?.name || "")}" required />
      </div>
      <div class="field">
        <label>${escapeHtml(t("tasks.eg_tasks_in_group_label"))}</label>
        <div class="chip-row" id="eg-roots" style="margin-bottom: var(--space-2);"></div>
        ${
          writable
            ? `<button type="button" class="btn btn-ghost btn-block" id="eg-add-root-btn" style="justify-content: center;">
                 ${icons.plus}<span>${escapeHtml(t("tasks.eg_add_task_btn"))}</span>
               </button>`
            : ""
        }
      </div>
      <div class="field">
        <label>${escapeHtml(t("tasks.eg_preview_label"))}</label>
        <p class="muted" style="font-size: var(--font-size-xs); margin-top: 0;">
          ${escapeHtml(t("tasks.eg_preview_desc"))}
        </p>
        <div id="eg-preview-list" class="stack"></div>
      </div>
      <div class="field">
        <label class="row">
          <input type="checkbox" id="eg-schedule-enabled" ${group?.schedule_recurrence ? "checked" : ""} ${writable ? "" : "disabled"} />
          <span>${escapeHtml(t("tasks.eg_auto_trigger_label"))}</span>
        </label>
        <div id="eg-schedule-fields" style="margin-top: var(--space-2); ${group?.schedule_recurrence ? "" : "display:none;"}">
          <label for="eg-schedule-recurrence">${escapeHtml(t("tasks.eg_repeats_label"))}</label>
          <select class="select" id="eg-schedule-recurrence" ${writable ? "" : "disabled"}>
            <option value="daily" ${(group?.schedule_recurrence ?? "daily") === "daily" ? "selected" : ""}>${escapeHtml(t("common.recurrence_daily"))}</option>
            <option value="weekly" ${group?.schedule_recurrence === "weekly" ? "selected" : ""}>${escapeHtml(t("tasks.eg_specific_weekdays"))}</option>
          </select>
          <div class="weekday-picker" id="eg-schedule-weekdays" style="margin-top: var(--space-2); ${group?.schedule_recurrence === "weekly" ? "" : "display:none;"}">
            ${weekdayLabels.map((label, i) => `<div class="weekday-pill${(group?.schedule_weekdays || []).includes(i) ? " on" : ""}" data-day="${i}">${escapeHtml(label)}</div>`).join("")}
          </div>
          <label for="eg-schedule-hour" style="margin-top: var(--space-2); display: block;">${escapeHtml(t("common.at_tz_label", { tz: timezone }))}</label>
          <select class="select" id="eg-schedule-hour" ${writable ? "" : "disabled"}>
            ${Array.from({ length: 24 }, (_, h) => `<option value="${h}" ${(group?.schedule_hour ?? 18) === h ? "selected" : ""}>${String(h).padStart(2, "0")}:00</option>`).join("")}
          </select>
          <p class="muted" style="font-size: var(--font-size-xs); margin-top: var(--space-2);">
            ${escapeHtml(t("tasks.eg_schedule_note", { tz: timezone }))}
          </p>
        </div>
      </div>
    </div>
    <div class="modal-footer">
      ${group && writable ? `<button class="btn btn-danger" id="eg-delete">${icons.trash}</button>` : ""}
      ${writable ? `<button class="btn btn-primary grow" id="eg-save">${escapeHtml(t("common.save"))}</button>` : ""}
    </div>
  `;

  function renderRootChips() {
    const root = body.querySelector("#eg-roots");
    if (selectedRoots.length === 0 && flaggedRoots.length === 0) {
      root.innerHTML = `<span class="muted" style="font-size: var(--font-size-sm);">${escapeHtml(t("tasks.no_tasks_yet_add"))}</span>`;
      return;
    }
    root.innerHTML = [
      ...selectedRoots.map(
        (r) => `
        <span class="chip chip-active" data-id="${r.id}">
          ${escapeHtml(r.name)}
          ${writable ? `<button type="button" aria-label="${escapeAttr(t("tasks.remove_aria", { name: r.name }))}" data-remove="${r.id}">&times;</button>` : ""}
        </span>`
      ),
      ...flaggedRoots.map(
        (r) => `
        <span class="chip" data-id="${r.id}" title="${escapeAttr(t("tasks.not_eligible_title"))}" style="opacity: 0.6;">
          ${escapeHtml(r.name)} ⚠
          ${writable ? `<button type="button" aria-label="${escapeAttr(t("tasks.remove_aria", { name: r.name }))}" data-remove="${r.id}">&times;</button>` : ""}
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
      previewRoot.innerHTML = `<span class="muted" style="font-size: var(--font-size-sm);">${escapeHtml(t("tasks.nothing_to_preview"))}</span>`;
      return;
    }
    previewRoot.innerHTML = items
      .map((item) => {
        if (item.is_root) {
          return `
          <div class="eg-preview-row">
            <span class="eg-preview-title">${escapeHtml(item.task_name)}</span>
            <span class="badge badge-success">${escapeHtml(t("common.created_now_badge"))}</span>
          </div>`;
        }
        const checked = !excludedIds.has(item.task_id);
        return `
          <div class="eg-preview-row eg-preview-descendant">
            <label class="row" style="gap: var(--space-2); flex: 1; min-width: 0;">
              <input type="checkbox" data-task-id="${item.task_id}" ${checked ? "checked" : ""} ${writable ? "" : "disabled"} />
              <span class="eg-preview-title">${escapeHtml(item.task_name)}</span>
            </label>
            <span class="badge badge-success">${escapeHtml(t("common.created_now_badge"))}</span>
            <span class="badge badge-neutral">${escapeHtml(t("common.chained_from", { name: item.parent_task_name }))}</span>
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
      previewRoot.innerHTML = `<span class="muted" style="font-size: var(--font-size-sm);">${escapeHtml(t("tasks.add_task_above"))}</span>`;
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
      if (seq === previewSeq) previewRoot.innerHTML = `<div class="empty-state">${escapeHtml(t("tasks.couldnt_load_preview"))}</div>`;
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
      const eligible = tasksCache.filter((task) => task.active && !task.is_chain_child && !takenIds.has(task.id));
      openTaskPickerModal({
        tasks: eligible,
        categories: categoriesCache,
        title: t("tasks.add_task_to_group_title"),
        emptyMessage: t("tasks.no_eligible_tasks_left"),
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
      showToast(t("common.name_required"), "warning");
      return;
    }
    if (selectedRoots.length === 0) {
      showToast(t("tasks.add_at_least_one_task"), "warning");
      return;
    }
    const scheduleEnabled = body.querySelector("#eg-schedule-enabled").checked;
    const scheduleRecurrence = scheduleEnabled ? body.querySelector("#eg-schedule-recurrence").value : null;
    const scheduleWeekdays = scheduleRecurrence === "weekly" ? [...selectedScheduleWeekdays].sort((a, b) => a - b) : null;
    if (scheduleRecurrence === "weekly" && scheduleWeekdays.length === 0) {
      showToast(t("tasks.pick_weekday_weekly"), "warning");
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
      showToast(t("tasks.event_group_saved"), "success");
      close();
      loadEventGroups(container, writable);
    } catch {
      /* api.js already showed a toast */
    }
  });

  if (group) {
    body.querySelector("#eg-delete").addEventListener("click", async () => {
      const ok = await showConfirmDialog({
        title: t("tasks.delete_event_group_title"),
        message: t("tasks.delete_event_group_message", { name: group.name }),
        confirmLabel: t("common.delete"),
        danger: true,
      });
      if (!ok) return;
      try {
        await api.del(`${HB}/event-groups/${group.id}`);
        showToast(t("tasks.event_group_deleted"), "success");
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
      showToast(t("tasks.chain_task_added"), "success");
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
      ? t("tasks.already_chained_from", { name: task.name, parents: names })
      : t("tasks.already_chained_from_other", { name: task.name });
  }

  async function refresh() {
    let links;
    try {
      links = await api.get(`${HB}/tasks/${task.id}/chain-links`);
    } catch {
      listEl.innerHTML = `<div class="empty-state">${escapeHtml(t("tasks.couldnt_load_preview"))}</div>`;
      return;
    }

    listEl.innerHTML = links.length
      ? links
          .map(
            (link) => `
        <div class="list-row" data-link-id="${link.id}">
          <div class="list-row-body">
            <div class="list-row-title">${escapeHtml(link.child_task_name)}</div>
            <div class="list-row-meta"><span>${link.same_user ? escapeHtml(t("tasks.same_person")) : escapeHtml(t("tasks.different_person"))}</span></div>
          </div>
          ${writable ? `<button class="btn btn-icon btn-ghost chain-remove-btn" aria-label="${escapeAttr(t("tasks.remove_label"))}">${icons.trash}</button>` : ""}
        </div>`
          )
          .join("")
      : `<span class="muted" style="font-size: var(--font-size-sm);">${escapeHtml(t("tasks.no_chained_tasks_yet"))}</span>`;

    if (writable) {
      listEl.querySelectorAll(".chain-remove-btn").forEach((btn) => {
        btn.addEventListener("click", async () => {
          const row = btn.closest("[data-link-id]");
          const linkId = row.dataset.linkId;
          try {
            await api.del(`${HB}/tasks/${task.id}/chain-links/${linkId}`);
            showToast(t("tasks.chain_task_removed"), "success");
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
      (task2) => task2.id !== task.id && !linkedChildIds.has(task2.id) && !task2.is_chain_child
    );
    childBtn.disabled = !writable || eligibleChildren.length === 0;
    childBtn.innerHTML =
      eligibleChildren.length === 0
        ? `<span>${escapeHtml(t("tasks.no_eligible_tasks"))}</span>`
        : `${icons.plus}<span>${escapeHtml(t("tasks.add_chain_task_btn"))}</span>`;
  }

  if (writable && !task.is_chain_child) {
    childBtn.addEventListener("click", () => {
      openTaskPickerModal({
        tasks: eligibleChildren,
        categories: categoriesCache,
        title: t("tasks.choose_chain_task_title"),
        emptyMessage: t("tasks.no_eligible_tasks_match"),
        onSelect: addChainLink,
      });
    });
  } else if (!task.is_chain_child) {
    childBtn.disabled = true;
    sameUserEl.disabled = true;
  }

  await refresh();
}

async function openTaskModal(container, writable, task = null) {
  const selectedCats = new Set((task?.categories || []).map((c) => c.id));
  const selectedWeekdays = new Set(task?.weekdays || []);
  // Manual is the default for a brand-new task (task is null here) — most
  // new tasks created lately are event-group roots/chain links, which
  // need manual specifically (see Recurrence.manual's own docstring);
  // picking daily/weekly/monthly is still one tap away, same as before.
  const recurrence = task?.recurrence || "manual";
  const weekdayLabels = WEEKDAY_LABELS();
  const pinnable = pinnableUsers(await loadUsers(true));
  const canEditPin = isAdmin();
  // Meaningful for every recurrence except a chain-child task — even
  // daily/manual get a pin now (an informational badge, plus routing
  // any todo actually created from the task to the pinned person; see
  // Task.pinned_user_id's own docstring for the full "what a pin does
  // per recurrence" breakdown). Chain-child status alone stays hidden,
  // since such a task's only instances come from its own chain spawn,
  // which already goes to whoever completed the parent (same_user) or
  // the balancer's own pick (different_user) — a pin on the CHILD task
  // itself would have nothing to attach to.
  const pinEligible = !task?.is_chain_child;

  const { body, close } = openModalShell(task ? t("tasks.edit_task_title") : t("tasks.new_task_title"));

  body.innerHTML = `
    <div class="stack">
      <div class="field">
        <label for="f-name">${escapeHtml(t("tasks.name_label"))}</label>
        <input class="input" id="f-name" value="${escapeAttr(task?.name || "")}" required />
      </div>
      <div class="field">
        <label for="f-description">${escapeHtml(t("common.description_label"))}</label>
        <textarea class="input" id="f-description" rows="2">${escapeHtml(task?.description || "")}</textarea>
      </div>
      <div class="field-row">
        <div class="field">
          <label for="f-points">${escapeHtml(t("common.points_label"))}</label>
          <input class="input" type="number" min="0" id="f-points" value="${task?.points ?? 1}" />
        </div>
        <div class="field">
          <label for="f-times">${escapeHtml(t("tasks.times_per_day_label"))}</label>
          <input class="input" type="number" min="1" id="f-times" value="${task?.times_per_day ?? 1}" />
        </div>
      </div>

      <div class="field">
        <label for="f-recurrence">${escapeHtml(t("tasks.eg_repeats_label"))}</label>
        <select class="select" id="f-recurrence">
          <option value="daily" ${recurrence === "daily" ? "selected" : ""}>${escapeHtml(t("tasks.daily_option"))}</option>
          <option value="weekly" ${recurrence === "weekly" ? "selected" : ""}>${escapeHtml(t("tasks.weekly_option"))}</option>
          <option value="monthly" ${recurrence === "monthly" ? "selected" : ""}>${escapeHtml(t("common.recurrence_monthly"))}</option>
          <option value="manual" ${recurrence === "manual" ? "selected" : ""}>${escapeHtml(t("tasks.manual_option"))}</option>
        </select>
        <div class="weekday-picker" id="f-weekdays" style="margin-top: var(--space-2); ${recurrence === "weekly" ? "" : "display:none;"}">
          ${weekdayLabels.map((label, i) => `<div class="weekday-pill${selectedWeekdays.has(i) ? " on" : ""}" data-day="${i}">${escapeHtml(label)}</div>`).join("")}
        </div>
      </div>

      <div class="field" id="f-pinned-field" style="${pinEligible ? "" : "display:none;"}">
        <label for="f-pinned-user">${escapeHtml(t("tasks.pinned_label"))}</label>
        <select class="select" id="f-pinned-user" ${canEditPin ? "" : "disabled"}>
          <option value="">${escapeHtml(t("tasks.pinned_none"))}</option>
          ${pinnable
            .map(
              (u) =>
                `<option value="${u.id}" ${task?.pinned_user_id === u.id ? "selected" : ""}>${escapeAttr(u.display_name)}</option>`
            )
            .join("")}
        </select>
        <p class="muted" style="font-size: var(--font-size-xs); margin-top: 4px;">
          ${escapeHtml(t("tasks.pinned_desc"))}${!canEditPin ? ` ${escapeHtml(t("tasks.pinned_admin_only_note"))}` : ""}
        </p>
      </div>

      <div class="field">
        <label>${escapeHtml(t("tasks.categories_label"))}</label>
        <div class="chip-row" id="f-categories">
          ${
            categoriesCache.length
              ? categoriesCache
                  .map(
                    (c) =>
                      `<span class="chip${selectedCats.has(c.id) ? " chip-active" : ""}" data-id="${c.id}">${c.icon ? escapeHtml(c.icon) + " " : ""}${escapeHtml(c.name)}</span>`
                  )
                  .join("")
              : `<span class="muted" style="font-size: var(--font-size-sm);">${escapeHtml(t("tasks.none_yet_add_above"))}</span>`
          }
        </div>
      </div>

      <div class="field">
        <label class="row"><input type="checkbox" id="f-ramp-up" ${task?.ramp_up_enabled ? "checked" : ""} /> <span>${escapeHtml(t("tasks.ramp_up_label"))}</span></label>
        <div class="field" id="f-ramp-up-points" style="margin-top: var(--space-2); ${task?.ramp_up_enabled ? "" : "display:none;"}">
          <label for="f-bonus">${escapeHtml(t("tasks.bonus_points_label"))}</label>
          <input class="input" type="number" min="0" id="f-bonus" value="${task?.ramp_up_bonus_points ?? 0}" />
        </div>
      </div>

      <div class="field">
        <label class="row"><input type="checkbox" id="f-active" ${task?.active !== false ? "checked" : ""} /> <span>${escapeHtml(t("tasks.active_label"))}</span></label>
      </div>

      ${
        task
          ? `<div class="field">
        <label>${escapeHtml(t("tasks.chain_tasks_label"))}</label>
        <p class="muted" style="font-size: var(--font-size-xs); margin-top: 0;">
          ${escapeHtml(t("tasks.chain_tasks_desc", { name: task.name }))}
        </p>
        <div class="stack" id="chain-link-list" style="margin-top: var(--space-2);"></div>
        <div class="stack" style="margin-top: var(--space-2); gap: var(--space-2);">
          <select class="select" id="chain-same-user-select">
            <option value="false">${escapeHtml(t("tasks.different_person"))}</option>
            <option value="true">${escapeHtml(t("tasks.same_person"))}</option>
          </select>
          <button type="button" class="btn btn-ghost btn-block" id="chain-child-btn" style="justify-content: center;">
            ${icons.plus}<span>${escapeHtml(t("tasks.add_chain_task_btn"))}</span>
          </button>
        </div>
      </div>`
          : ""
      }
    </div>
    <div class="modal-footer">
      ${task ? `<button class="btn btn-danger" id="f-delete">${icons.trash}</button>` : ""}
      <button class="btn btn-primary grow" id="f-save">${escapeHtml(t("common.save"))}</button>
    </div>
  `;

  const weekdayPicker = body.querySelector("#f-weekdays");
  body.querySelector("#f-recurrence").addEventListener("change", (e) => {
    weekdayPicker.style.display = e.target.value === "weekly" ? "" : "none";
    // The pinned-owner field (#f-pinned-field) deliberately does NOT
    // toggle here — unlike weekdays, a pin now applies to every
    // recurrence (see Task.pinned_user_id's own docstring), so it
    // never needs hiding on a recurrence change.
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
      showToast(t("common.name_required"), "warning");
      return;
    }
    const newRecurrence = body.querySelector("#f-recurrence").value;
    const weekdays = newRecurrence === "weekly" ? [...selectedWeekdays].sort((a, b) => a - b) : null;
    if (newRecurrence === "weekly" && weekdays.length === 0) {
      showToast(t("tasks.pick_weekday_weekly_task"), "warning");
      return;
    }

    const pinnedRaw = body.querySelector("#f-pinned-user").value;

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
      // Always included, explicit null when "No one" is picked — the
      // PATCH route's own clearing logic depends on this field being
      // PRESENT in the request (see TaskUpdate's own docstring), not
      // just non-null; omitting it here would make un-pinning
      // impossible.
      pinned_user_id: pinnedRaw ? Number(pinnedRaw) : null,
    };

    try {
      if (task) {
        await api.patch(`${HB}/tasks/${task.id}`, payload);
      } else {
        await api.post(`${HB}/tasks`, payload);
      }
      showToast(t("tasks.task_saved"), "success");
      invalidateAllTasksCache();
      close();
      loadTasks(container, writable);
    } catch {
      /* api.js already showed a toast */
    }
  });

  if (task) {
    body.querySelector("#f-delete").addEventListener("click", async () => {
      const ok = await showConfirmDialog({
        title: t("tasks.delete_task_title"),
        message: t("tasks.delete_task_message", { name: task.name }),
        confirmLabel: t("common.delete"),
        danger: true,
      });
      if (!ok) return;
      try {
        await api.del(`${HB}/tasks/${task.id}`);
        showToast(t("tasks.task_deleted"), "success");
        invalidateAllTasksCache();
        close();
        loadTasks(container, writable);
      } catch {
        /* api.js already showed a toast */
      }
    });
  }
}
