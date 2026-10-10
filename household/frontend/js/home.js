import { CONFIG } from "./config.js";
import { api } from "./api.js";
import { icons } from "./icons.js";
import { getCurrentUserInfo } from "./auth.js";
import { showToast } from "./toast.js";
import { takeoverControl } from "./takeover.js";
import { refreshNotificationBadge } from "./notifications.js";
import { showConfirmDialog } from "./confirmDialog.js";
import { escapeHtml, escapeAttr, dueBadge, showSkeletonAfterDelay, WEEKDAY_LABELS } from "./util.js";
import { t } from "./i18n.js";

const HB = CONFIG.HOUSEHOLD_BASE;
const PAGE_SIZE = 20;

function canWrite() {
  const info = getCurrentUserInfo();
  return info && (info.role === "admin" || info.role === "user");
}

// Persists across re-renders within the same page load, resets on reload.
const state = { q: "", categoryId: "", offset: 0, total: 0 };

let categoriesCache = null;
let allTasksCache = null;
let assignmentsCache = null;
// Open Board todos assigned to the current user — the "sync" between
// the Board and Home's "Assigned to you" section (see loadAssignments).
let myTodosCache = [];
let completionsTodayCache = {};
let meCache = null;
let pageSelection = null;
let debounceTimer = null;
// Pending takeover requests: incoming (asking YOU to take something
// over) and outgoing (things you've asked someone else to take). Both
// drive "Assigned to you"'s per-row state (see renderAssignedToYou) —
// outgoing swaps the "ask to take over" button for a pending/cancel
// state, incoming gets its own section above it.
let incomingRequestsCache = [];
let outgoingRequestsCache = [];

function debounce(fn, delay) {
  return (...args) => {
    clearTimeout(debounceTimer);
    debounceTimer = setTimeout(() => fn(...args), delay);
  };
}

// Called by tasks.js after a task is created, edited, or deleted — Home's
// "All tasks" list is its own separate fetch (allTasksCache above), fully
// decoupled from the Tasks page's own cache, so without this a newly
// created task wouldn't show up here until a hard reload dropped the
// stale cache. Only clears the cached data, not any of Home's own
// state (search/category filter, scroll position) — refreshTaskList()
// re-fetches and re-applies those on its own next call, same as it
// already does on first load.
export function invalidateAllTasksCache() {
  allTasksCache = null;
}

export async function renderHome(container) {
  const writable = canWrite();

  container.innerHTML = `
    <div class="page">
      <div class="stat-card-row" id="stat-cards"></div>
      <div id="goal-progress"></div>

      <div id="incoming-requests-section" style="display:none;">
        <div class="section-heading"><h2>${escapeHtml(t("home.section_takeover_requests"))}</h2></div>
        <div id="incoming-requests-list" class="stack" style="margin-bottom: var(--space-3);"></div>
      </div>

      <div class="section-heading"><h2>${escapeHtml(t("home.section_assigned_to_you"))}</h2></div>
      <div id="assigned-list" class="stack"></div>

      <div class="section-heading"><h2>${escapeHtml(t("home.section_all_tasks"))}</h2></div>
      <div class="row" style="margin-bottom: var(--space-3);">
        <div class="search-bar grow">
          ${icons.search}
          <input type="search" id="search-input" placeholder="${escapeAttr(t("common.search_tasks_placeholder"))}" value="${escapeAttr(state.q)}" />
        </div>
        ${writable ? `<button class="btn btn-icon" id="select-toggle" aria-label="${escapeAttr(t("home.select_tasks_label"))}" title="${escapeAttr(t("home.select_tasks_label"))}">${icons.checklist}</button>` : ""}
      </div>
      <div class="chip-row" id="category-chips" style="margin-bottom: var(--space-3);"></div>
      <div id="task-list" class="stack"></div>
      <div id="pagination-root"></div>
    </div>
    <div id="bulk-bar-root"></div>
  `;

  const selection = { mode: false, ids: new Set() };
  pageSelection = selection; // so a completion triggered from "Assigned to you" (which has no selection of its own) can still refresh the All-tasks list below it

  container.querySelector("#search-input").addEventListener(
    "input",
    debounce((e) => {
      state.q = e.target.value;
      state.offset = 0;
      refreshTaskList(container, selection, writable);
    }, 250)
  );

  if (writable) {
    const selectToggle = container.querySelector("#select-toggle");
    selectToggle.addEventListener("click", () => {
      selection.mode = !selection.mode;
      selection.ids.clear();
      selectToggle.classList.toggle("btn-primary", selection.mode);
      refreshTaskList(container, selection, writable);
    });
  }

  await Promise.all([loadStats(container), loadCategories(container, selection, writable)]);
  await loadAssignments(container);
  await loadTakeoverRequests(container);
  await refreshCompletionsToday();
  await refreshTaskList(container, selection, writable);
}

// How many times each task's already been completed today (by anyone) —
// feeds the "Done today" badge/disabled complete button in the full
// task list below.
async function refreshCompletionsToday() {
  try {
    completionsTodayCache = await api.get(`${HB}/tasks/completions-today`);
  } catch {
    completionsTodayCache = {};
  }
}

function doneForToday(task) {
  return (completionsTodayCache[task.id] || 0) >= task.times_per_day;
}

// Shared refresh after a task completion, wherever it was tapped from
// (All tasks or the bulk-complete bar) — a task can gain a "Done today"
// badge the moment it hits its times_per_day for the day.
async function afterTaskCompletion(container) {
  await refreshCompletionsToday();
  loadStats(container);
  // A same-user chain spawn assigns the new todo straight to whoever just
  // completed this task — refresh "Assigned to you" so it shows up right
  // away instead of only after the next unrelated reload (see
  // TaskChainLink / crud._spawn_chain_children).
  await refreshMyTodos();
  renderAssignedToYou(container);
  if (pageSelection) refreshTaskList(container, pageSelection, canWrite());
}

// A chain-child task normally only gets completed via the todo it's
// spawned as (see TaskChainLink) — completing it directly here is still
// allowed, but only after an explicit confirm naming whichever parent
// task(s) chain it, since the backend otherwise rejects it outright
// (crud.complete_task's `force` override exists specifically for this
// confirmed-anyway path).
async function confirmDirectChainCompletion(task) {
  let parents;
  try {
    parents = await api.get(`${HB}/tasks/${task.id}/chain-parents`);
  } catch {
    return false; // api.js already showed a toast
  }
  const names = parents.map((p) => p.parent_task_name).join(", ");
  return showConfirmDialog({
    title: t("home.already_chained_title"),
    message: t("home.already_chained_message", { task: task.name, parents: names }),
    confirmLabel: t("home.complete_anyway"),
  });
}

// Logging past times_per_day is an explicit, confirmed override (crud.
// complete_task's `force_daily_cap`) — same "informed override, not a
// silent bypass" shape as confirmDirectChainCompletion above, just for
// a different check. completionsTodayCache is already kept fresh by
// afterTaskCompletion, so this needs no extra fetch of its own.
function confirmDailyCapOverride(task) {
  const count = completionsTodayCache[task.id] || 0;
  return showConfirmDialog({
    title: t("home.already_done_today_title"),
    message: t("home.already_done_today_message", { task: task.name, count, n: task.times_per_day }),
    confirmLabel: t("home.complete_anyway"),
  });
}

async function completeTask(container, task) {
  const body = {};
  if (task.is_chain_child) {
    const ok = await confirmDirectChainCompletion(task);
    if (!ok) return;
    body.force = true;
  }
  if (doneForToday(task)) {
    const ok = await confirmDailyCapOverride(task);
    if (!ok) return;
    body.force_daily_cap = true;
  }
  try {
    await api.post(`${HB}/tasks/${task.id}/complete`, Object.keys(body).length ? body : undefined);
    showToast(t("home.logged_toast", { title: task.name, points: task.points }), "success");
    afterTaskCompletion(container);
  } catch {
    /* api.js already showed a toast (e.g. 409 if someone else just hit
       times_per_day for today between this tap and the request landing) */
  }
}

// Open Board todos assigned to the current user — fetched alongside the
// recurring-task assignments above so "Assigned to you" reflects a
// Board request the moment it's assigned/claimed, not just recurring
// Task assignments from the balancer.
async function refreshMyTodos() {
  if (!meCache) {
    myTodosCache = [];
    return;
  }
  try {
    myTodosCache = await api.get(`${HB}/todos?status=open&assigned_to_id=${meCache.id}`);
  } catch {
    myTodosCache = [];
  }
}

async function afterTodoCompletion(container) {
  await refreshMyTodos();
  loadStats(container);
  renderAssignedToYou(container);
}

// A Board todo assigned to you, rendered in the "Assigned to you"
// section — a one-off request, not a recurring Task, so it gets its own
// row shape (a due-date badge instead of a weekday schedule, no
// times-per-day/ramp-up/category concepts).
function boardTodoRow(todo, container) {
  const row = document.createElement("div");
  row.className = "list-row";
  row.style.cursor = "default";
  const badge = dueBadge(todo.due_date);
  const writable = canWrite();
  const sourceLabel = todo.chain_parent_task_name
    ? t("home.chain_from", { parent: todo.chain_parent_task_name })
    : t("home.from_board");

  row.innerHTML = `
    <div class="list-row-body">
      <div class="list-row-title">${escapeHtml(todo.title)}</div>
      <div class="list-row-meta">
        <span class="badge badge-neutral">${escapeHtml(sourceLabel)}</span>
        ${badge ? `<span class="badge badge-${badge.tone}">${escapeHtml(badge.label)}</span>` : ""}
      </div>
    </div>
    <div class="list-row-points"><span>${todo.points}</span><span class="muted">${escapeHtml(t("common.pts"))}</span></div>
    ${writable ? `<div class="list-row-actions"><button class="btn btn-icon btn-primary" data-action="complete" aria-label="${escapeAttr(t("home.complete_aria", { title: todo.title }))}">${icons.check}</button></div>` : ""}
  `;

  if (writable) {
    row.querySelector('[data-action="complete"]').addEventListener("click", async () => {
      try {
        await api.post(`${HB}/todos/${todo.id}/complete`);
        showToast(t("home.logged_toast", { title: todo.title, points: todo.points }), "success");
        afterTodoCompletion(container);
      } catch {
        /* api.js already showed a toast */
      }
    });
    row.querySelector(".list-row-actions").prepend(takeoverControl({ requests: outgoingRequestsCache, kind: "todo", id: todo.id, label: todo.title, onChange: () => afterTakeoverAction(container) }));
  }

  return row;
}

async function loadStats(container) {
  const statRoot = container.querySelector("#stat-cards");
  const goalRoot = container.querySelector("#goal-progress");
  if (!statRoot) return;

  const cancelSkeleton = showSkeletonAfterDelay(
    statRoot,
    `<div class="stat-card"><div class="skeleton" style="height: 36px;"></div></div>
     <div class="stat-card"><div class="skeleton" style="height: 36px;"></div></div>`
  );
  try {
    const [me, settings, board] = await Promise.all([
      api.get(`${HB}/me`),
      api.get(`${HB}/settings`),
      // period=this_week resolves server-side against the admin's
      // configured week start, in UTC (crud.resolve_leaderboard_bounds)
      // — this card doesn't need to know that setting itself. include_me:
      // this card shows YOUR OWN points this week, not a comparison
      // ranking — it should keep counting even while on break (break only
      // hides you from everyone else's leaderboard/assignments, see
      // crud.leaderboard), not silently read 0 just because the
      // household-wide ranking excludes you.
      api.get(`${HB}/points/leaderboard?period=this_week&include_me=true`),
    ]);
    cancelSkeleton();
    meCache = me;
    const mine = board.find((row) => row.user.id === me.id);
    const weekPoints = mine ? mine.total_points : 0;

    statRoot.innerHTML = `
      <div class="stat-card">
        <div class="stat-value">${weekPoints}</div>
        <div class="stat-label">${escapeHtml(t("home.points_this_week"))}</div>
      </div>
      <div class="stat-card">
        <div class="stat-value">${me.on_break ? escapeHtml(t("home.on_break")) : escapeHtml(t("home.active"))}</div>
        <div class="stat-label">${escapeHtml(me.display_name)}</div>
      </div>
    `;

    if (settings.weekly_points_goal) {
      const pct = Math.min(100, Math.round((weekPoints / settings.weekly_points_goal) * 100));
      goalRoot.innerHTML = `
        <div class="muted row-between" style="font-size: var(--font-size-xs); margin: var(--space-3) 0 4px;">
          <span>${escapeHtml(t("home.weekly_goal"))}</span><span>${weekPoints} / ${settings.weekly_points_goal}</span>
        </div>
        <div class="progress-bar"><div class="progress-bar-fill" style="width:${pct}%;"></div></div>
      `;
    } else {
      goalRoot.innerHTML = "";
    }
  } catch {
    cancelSkeleton();
    statRoot.innerHTML = `<div class="empty-state" style="grid-column: 1/-1;">${escapeHtml(t("home.couldnt_load_stats"))}</div>`;
  }
}

async function loadAssignments(container) {
  const root = container.querySelector("#assigned-list");
  if (!root) return;
  const cancelSkeleton = showSkeletonAfterDelay(root, `<div class="skeleton" style="height: 64px;"></div>`);
  try {
    assignmentsCache = await api.get(`${HB}/assignments`);
  } catch {
    assignmentsCache = [];
  }
  cancelSkeleton();
  await refreshMyTodos();
  renderAssignedToYou(container);
}

async function loadTakeoverRequests(container) {
  try {
    const [incoming, outgoing] = await Promise.all([
      api.get(`${HB}/takeover-requests?direction=incoming`),
      api.get(`${HB}/takeover-requests?direction=outgoing`),
    ]);
    incomingRequestsCache = incoming;
    outgoingRequestsCache = outgoing;
  } catch {
    incomingRequestsCache = [];
    outgoingRequestsCache = [];
  }
  renderIncomingRequests(container);
  renderAssignedToYou(container);
}

async function afterTakeoverAction(container) {
  await Promise.all([loadAssignments(container), loadTakeoverRequests(container)]);
  loadStats(container);
  refreshNotificationBadge();
}

function renderIncomingRequests(container) {
  const section = container.querySelector("#incoming-requests-section");
  const root = container.querySelector("#incoming-requests-list");
  if (!section || !root) return;

  if (incomingRequestsCache.length === 0) {
    section.style.display = "none";
    root.innerHTML = "";
    return;
  }
  section.style.display = "";
  root.innerHTML = "";
  incomingRequestsCache.forEach((req) => {
    const label = req.todo_title || req.task_name;
    const row = document.createElement("div");
    row.className = "list-row";
    row.style.cursor = "default";
    row.innerHTML = `
      <div class="list-row-body">
        <div class="list-row-title">${escapeHtml(label)}</div>
        <div class="list-row-meta"><span>${escapeHtml(t("takeover.asked_you", { name: req.requester.display_name }))}</span></div>
      </div>
      <div class="list-row-actions">
        <button class="btn btn-icon btn-danger" data-action="decline" aria-label="${escapeAttr(t("notif.decline_label"))}">${icons.close}</button>
        <button class="btn btn-icon btn-primary" data-action="accept" aria-label="${escapeAttr(t("notif.accept_label"))}">${icons.check}</button>
      </div>
    `;
    row.querySelector('[data-action="accept"]').addEventListener("click", async () => {
      try {
        await api.post(`${HB}/takeover-requests/${req.id}/accept`);
        showToast(t("takeover.took_over", { title: label }), "success");
        afterTakeoverAction(container);
      } catch {
        /* api.js already showed a toast (e.g. 409 if it changed hands first) */
        afterTakeoverAction(container);
      }
    });
    row.querySelector('[data-action="decline"]').addEventListener("click", async () => {
      try {
        await api.post(`${HB}/takeover-requests/${req.id}/decline`);
        showToast(t("takeover.declined"), "success");
        afterTakeoverAction(container);
      } catch {
        /* api.js already showed a toast */
      }
    });
    root.appendChild(row);
  });
}


function renderAssignedToYou(container) {
  const root = container.querySelector("#assigned-list");
  if (!root) return;
  const myAssignments = meCache ? (assignmentsCache || []).filter((a) => a.household_user.id === meCache.id) : [];
  const myTodos = myTodosCache || [];

  if (myAssignments.length === 0 && myTodos.length === 0) {
    root.innerHTML = `<div class="empty-state">${escapeHtml(t("home.nothing_assigned"))}</div>`;
    return;
  }
  root.innerHTML = "";
  myAssignments.forEach((a) => {
    const row = document.createElement("div");
    row.className = "list-row";
    row.style.cursor = "default";
    row.innerHTML = `
      <div class="list-row-body">
        <div class="list-row-title">${escapeHtml(a.task_name)}</div>
        <div class="list-row-meta"><span>${escapeHtml(a.period_start)} – ${escapeHtml(a.period_end)}</span></div>
      </div>
      <div class="list-row-points"><span>${a.task_points}</span><span class="muted">${escapeHtml(t("common.pts"))}</span></div>
    `;
    if (canWrite()) {
      const actions = document.createElement("div");
      actions.className = "list-row-actions";
      actions.appendChild(takeoverControl({ requests: outgoingRequestsCache, kind: "assignment", id: a.id, label: a.task_name, onChange: () => afterTakeoverAction(container) }));
      row.appendChild(actions);
    }
    root.appendChild(row);
  });
  myTodos.forEach((todo) => root.appendChild(boardTodoRow(todo, container)));
}

// Who (if anyone) currently holds this task, for a badge on its row in
// the All-tasks list — looked up from the same /assignments the
// "Assigned to you" section above uses, not refetched per task.
function assignmentBadge(task) {
  const a = (assignmentsCache || []).find((x) => x.task_id === task.id);
  if (!a) return "";
  const isMe = meCache && a.household_user.id === meCache.id;
  return `<span class="badge badge-${isMe ? "success" : "neutral"}">${
    isMe ? escapeHtml(t("home.assigned_to_you_badge")) : escapeHtml(t("home.assigned_to_other_badge", { name: a.household_user.display_name }))
  }</span>`;
}

async function loadCategories(container, selection, writable) {
  const root = container.querySelector("#category-chips");
  if (!root) return;
  try {
    categoriesCache = await api.get(`${HB}/categories`);
  } catch {
    categoriesCache = [];
  }
  renderCategoryChips(container, selection, writable);
}

function renderCategoryChips(container, selection, writable) {
  const root = container.querySelector("#category-chips");
  if (!root || !categoriesCache) return;

  const chips = [{ id: "", label: t("common.all") }, ...categoriesCache.map((c) => ({
    id: String(c.id),
    label: c.icon ? `${c.icon} ${c.name}` : c.name,
  }))];

  root.innerHTML = chips
    .map(
      (c) =>
        `<span class="chip${String(state.categoryId) === c.id ? " chip-active" : ""}" data-cat="${escapeAttr(c.id)}">${escapeHtml(c.label)}</span>`
    )
    .join("");

  root.querySelectorAll(".chip").forEach((chip) => {
    chip.addEventListener("click", () => {
      state.categoryId = chip.dataset.cat;
      state.offset = 0;
      renderCategoryChips(container, selection, writable);
      refreshTaskList(container, selection, writable);
    });
  });
}

async function refreshTaskList(container, selection, writable) {
  const root = container.querySelector("#task-list");
  if (!root) return;

  if (!allTasksCache) {
    const cancelSkeleton = showSkeletonAfterDelay(root, `<div class="skeleton" style="height: 64px;"></div>`);
    try {
      // A `manual` task has no automatic occurrence of its own at all
      // — it only ever exists as a todo someone deliberately posted/
      // triggered (an Event Group root, a chain link, the Board's
      // "From task" picker) — so unlike every other recurrence, it has
      // no business sitting in this ad-hoc "tap to complete anytime"
      // list. Filtered client-side, not server-side: the Board's "From
      // task" picker, the Event Group root picker, and the chain-link
      // picker all reuse this exact same GET /tasks endpoint and still
      // need manual tasks included.
      allTasksCache = (await api.get(`${HB}/tasks?active=true`)).filter(
        (task) => task.recurrence !== "manual"
      );
    } catch {
      cancelSkeleton();
      root.innerHTML = `<div class="empty-state">${escapeHtml(t("common.couldnt_load_tasks"))}</div>`;
      return;
    }
    cancelSkeleton();
  }

  let filtered = allTasksCache;
  if (state.q) {
    const q = state.q.toLowerCase();
    filtered = filtered.filter((task) => task.name.toLowerCase().includes(q));
  }
  if (state.categoryId) {
    filtered = filtered.filter((task) => task.categories.some((c) => String(c.id) === state.categoryId));
  }

  // All tasks are already fetched in one shot (fine at this app's scale
  // — a household's task list, unlike storage's inventory, isn't likely
  // to reach the point a server round-trip per page would pay for
  // itself) — pagination here just slices what's already in memory, so
  // paging doesn't re-fetch anything.
  state.total = filtered.length;
  if (state.offset >= state.total) state.offset = 0;
  const pageItems = filtered.slice(state.offset, state.offset + PAGE_SIZE);

  renderTaskRows(root, pageItems, container, writable ? selection : null, t("common.no_tasks_match"));
  renderPagination(container.querySelector("#pagination-root"), container, selection, writable);
  renderBulkBar(container, selection, writable);
}

function renderPagination(root, container, selection, writable) {
  if (!root) return;
  root.innerHTML = "";
  if (state.total <= PAGE_SIZE) return;

  const totalPages = Math.max(1, Math.ceil(state.total / PAGE_SIZE));
  const currentPage = Math.floor(state.offset / PAGE_SIZE) + 1;

  const wrap = document.createElement("div");
  wrap.className = "pagination";

  const prev = document.createElement("button");
  prev.className = "btn btn-icon";
  prev.innerHTML = icons.chevronLeft;
  prev.disabled = currentPage <= 1;
  prev.addEventListener("click", () => {
    state.offset = Math.max(0, state.offset - PAGE_SIZE);
    refreshTaskList(container, selection, writable);
  });

  const label = document.createElement("span");
  label.className = "page-label";
  label.textContent = t("home.page_label", { current: currentPage, total: totalPages });

  const next = document.createElement("button");
  next.className = "btn btn-icon";
  next.innerHTML = icons.chevronRight;
  next.disabled = currentPage >= totalPages;
  next.addEventListener("click", () => {
    state.offset += PAGE_SIZE;
    refreshTaskList(container, selection, writable);
  });

  wrap.append(prev, label, next);
  root.appendChild(wrap);
}

function taskRow(task, { selection, onToggleSelect, onComplete, writable }) {
  const row = document.createElement("div");
  row.className = "list-row";

  const inSelectMode = Boolean(selection && selection.mode);
  const isSelected = inSelectMode && selection.ids.has(task.id);
  row.classList.toggle("selected", isSelected);

  const catLabel = task.categories.map((c) => (c.icon ? `${c.icon} ${c.name}` : c.name)).join(" · ");
  const weekdayLabels = WEEKDAY_LABELS();
  const schedule =
    task.recurrence === "weekly"
      ? task.weekdays && task.weekdays.length
        ? task.weekdays.map((w) => weekdayLabels[w]).join(" ")
        : t("common.recurrence_weekly")
      : task.recurrence === "monthly"
        ? t("common.recurrence_monthly")
        : t("common.recurrence_daily");
  const doneToday = doneForToday(task);

  row.innerHTML = `
    ${inSelectMode ? `<div class="list-row-select">${icons.check}</div>` : ""}
    <div class="list-row-body">
      <div class="list-row-title">${escapeHtml(task.name)}</div>
      <div class="list-row-meta">
        ${catLabel ? `<span>${escapeHtml(catLabel)}</span>` : ""}
        <span>${escapeHtml(schedule)}${task.times_per_day > 1 ? ` · ${escapeHtml(t("common.times_per_day", { n: task.times_per_day }))}` : ""}</span>
        ${task.ramp_up_enabled ? `<span class="badge badge-info">${escapeHtml(t("common.bonus_badge", { n: task.ramp_up_bonus_points }))}</span>` : ""}
        ${task.is_chain_child ? `<span class="badge badge-neutral">${escapeHtml(t("common.chained_badge"))}</span>` : ""}
        ${assignmentBadge(task)}
        ${doneToday ? `<span class="badge badge-success">${escapeHtml(t("home.done_today_badge"))}</span>` : ""}
      </div>
    </div>
    <div class="list-row-points"><span>${task.points}</span><span class="muted">${escapeHtml(t("common.pts"))}</span></div>
    ${
      writable && !inSelectMode
        ? `<div class="list-row-actions"><button class="btn btn-icon${doneToday ? "" : " btn-primary"}" data-action="complete" aria-label="${escapeAttr(t(doneToday ? "home.complete_again_aria" : "home.complete_aria", { title: task.name }))}">${icons.check}</button></div>`
        : ""
    }
  `;

  row.addEventListener("click", (e) => {
    if (inSelectMode) {
      onToggleSelect(task.id);
      return;
    }
    if (e.target.closest('[data-action="complete"]')) {
      onComplete(task);
    }
  });

  return row;
}

function renderTaskRows(root, tasks, container, selection, emptyMessage) {
  root.innerHTML = "";
  if (tasks.length === 0) {
    root.innerHTML = `<div class="empty-state">${escapeHtml(emptyMessage)}</div>`;
    return;
  }
  const writable = canWrite();
  tasks.forEach((task) => {
    root.appendChild(
      taskRow(task, {
        selection,
        writable,
        onToggleSelect: (id) => {
          if (selection.ids.has(id)) selection.ids.delete(id);
          else selection.ids.add(id);
          refreshTaskList(container, selection, writable);
        },
        onComplete: (task) => completeTask(container, task),
      })
    );
  });
}

function renderBulkBar(container, selection, writable) {
  const root = container.querySelector("#bulk-bar-root");
  if (!root) return;
  const page = container.querySelector(".page");
  if (!writable || !selection.mode) {
    root.innerHTML = "";
    if (page) page.style.paddingBottom = "";
    return;
  }

  const count = selection.ids.size;
  root.innerHTML = `
    <div class="bulk-bar">
      <span class="count-label">${escapeHtml(t("home.selected_count", { n: count }))}</span>
      <button class="btn btn-icon" id="bulk-cancel" aria-label="${escapeAttr(t("home.cancel_selection_label"))}">${icons.close}</button>
      <button class="btn btn-primary grow" id="bulk-complete-btn" ${count === 0 ? "disabled" : ""}>${icons.check}<span>${escapeHtml(t("home.bulk_complete"))}</span></button>
    </div>
  `;

  // The bulk bar floats fixed above the bottom nav, so without this the
  // last row (and the pagination controls below it) sit underneath it,
  // only partly visible — the exact "can't see which task you're
  // selecting" bug this is fixing. Measured rather than a guessed
  // constant, since the bar's real height depends on font size/viewport.
  if (page) {
    requestAnimationFrame(() => {
      const bar = root.querySelector(".bulk-bar");
      const barHeight = bar ? bar.getBoundingClientRect().height : 0;
      page.style.paddingBottom = `${Math.max(barHeight, 64) + 24}px`;
    });
  }

  const exitSelectMode = () => {
    selection.mode = false;
    selection.ids.clear();
    const toggle = container.querySelector("#select-toggle");
    if (toggle) toggle.classList.remove("btn-primary");
  };

  root.querySelector("#bulk-cancel").addEventListener("click", () => {
    exitSelectMode();
    refreshTaskList(container, selection, writable);
  });

  root.querySelector("#bulk-complete-btn").addEventListener("click", async () => {
    const ids = [...selection.ids];
    let completed = 0;
    for (const id of ids) {
      try {
        await api.post(`${HB}/tasks/${id}/complete`);
        completed++;
      } catch {
        /* api.js already showed a toast for this one; keep going */
      }
    }
    showToast(t("home.bulk_completed_toast", { completed, total: ids.length, count: ids.length }), completed === ids.length ? "success" : "warning");
    exitSelectMode();
    afterTaskCompletion(container);
  });
}
