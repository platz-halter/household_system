import { CONFIG } from "./config.js";
import { api } from "./api.js";
import { icons } from "./icons.js";
import { getCurrentUserInfo } from "./auth.js";
import { showToast } from "./toast.js";
import { showConfirmDialog } from "./confirmDialog.js";
import { openTaskPickerModal } from "./taskPicker.js";
import { escapeHtml, escapeAttr, showSkeletonAfterDelay, WEEKDAY_LABELS } from "./util.js";

const HB = CONFIG.HOUSEHOLD_BASE;

function canWrite() {
  const info = getCurrentUserInfo();
  return info && (info.role === "admin" || info.role === "user");
}

let categoriesCache = [];
let tasksCache = [];

// Persists across re-renders within the same page load (same pattern as
// board.js's status filter / home.js's search state) — switching to
// Calendar, visiting another page via the bottom nav, then coming back
// shouldn't reset either the chosen view or which month was showing.
const taskViewState = { view: "list" };
let calendarMonth = new Date(new Date().getFullYear(), new Date().getMonth(), 1);

export async function renderTasks(container) {
  const writable = canWrite();

  container.innerHTML = `
    <div class="page">
      <div class="section-heading">
        <h2>Categories</h2>
        ${writable ? `<button class="btn btn-icon" id="add-category-btn" aria-label="New category">${icons.plus}</button>` : ""}
      </div>
      <div class="chip-row" id="category-list" style="margin-bottom: var(--space-2);"></div>

      <div class="section-heading">
        <h2>Tasks</h2>
        <div class="chip-row" id="task-view-toggle">
          <span class="chip${taskViewState.view === "list" ? " chip-active" : ""}" data-view="list">List</span>
          <span class="chip${taskViewState.view === "calendar" ? " chip-active" : ""}" data-view="calendar">Calendar</span>
        </div>
      </div>
      <div id="task-view-root"></div>
    </div>
    ${writable ? `<button class="fab" id="add-task-fab" aria-label="New task">${icons.plus}</button>` : ""}
  `;

  if (writable) {
    container.querySelector("#add-category-btn").addEventListener("click", () => openCategoryModal(container, writable));
    container.querySelector("#add-task-fab").addEventListener("click", () => openTaskModal(container, writable));
  }

  container.querySelectorAll("#task-view-toggle .chip").forEach((chip) => {
    chip.addEventListener("click", () => {
      taskViewState.view = chip.dataset.view;
      container.querySelectorAll("#task-view-toggle .chip").forEach((c) => c.classList.toggle("chip-active", c === chip));
      renderTaskView(container, writable);
    });
  });

  await loadCategories(container, writable);
  await renderTaskView(container, writable);
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
// month to place them on — just "sometime this month"). Deliberately
// leaves out daily tasks: they're on every day by definition (a
// "standing chore," not scheduled the way this app uses the word
// elsewhere — see Recurrence's own docstring), so a calendar full of
// the same entries on every cell wouldn't tell anyone anything a plain
// list doesn't already. Also leaves out chain-child tasks — they have
// no independent schedule of their own (see TaskChainLink).
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
      const dayTasks = weeklyTasks.filter((t) => (t.weekdays || []).includes(weekday));
      return `
        <div class="cal-day${isSameLocalDay(dateObj, today) ? " cal-day-today" : ""}">
          <div class="cal-day-number">${d}</div>
          ${dayTasks.map((t) => `<div class="cal-day-task" title="${escapeAttr(t.name)} (${t.points} pts)">${escapeHtml(t.name)}</div>`).join("")}
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
