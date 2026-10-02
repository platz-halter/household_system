import { CONFIG } from "./config.js";
import { api } from "./api.js";
import { icons } from "./icons.js";
import { getCurrentUserInfo } from "./auth.js";
import { showToast } from "./toast.js";
import { escapeHtml, escapeAttr, todayWeekday, startOfWeekIso, WEEKDAY_LABELS } from "./util.js";

const HB = CONFIG.HOUSEHOLD_BASE;

function canWrite() {
  const info = getCurrentUserInfo();
  return info && (info.role === "admin" || info.role === "user");
}

// Persists across re-renders within the same page load, resets on reload.
const state = { q: "", categoryId: "" };

let categoriesCache = null;
let allTasksCache = null;
let debounceTimer = null;

function debounce(fn, delay) {
  return (...args) => {
    clearTimeout(debounceTimer);
    debounceTimer = setTimeout(() => fn(...args), delay);
  };
}

export async function renderHome(container) {
  const writable = canWrite();

  container.innerHTML = `
    <div class="page">
      <div class="stat-card-row" id="stat-cards">
        <div class="stat-card"><div class="skeleton" style="height: 36px;"></div></div>
        <div class="stat-card"><div class="skeleton" style="height: 36px;"></div></div>
      </div>
      <div id="goal-progress"></div>

      <div class="section-heading"><h2>Today</h2></div>
      <div id="today-list" class="stack"></div>

      <div class="section-heading"><h2>All tasks</h2></div>
      <div class="row" style="margin-bottom: var(--space-3);">
        <div class="search-bar grow">
          ${icons.search}
          <input type="search" id="search-input" placeholder="Search tasks…" value="${escapeAttr(state.q)}" />
        </div>
        ${writable ? `<button class="btn btn-icon" id="select-toggle" aria-label="Select tasks" title="Select tasks">${icons.checklist}</button>` : ""}
      </div>
      <div class="chip-row" id="category-chips" style="margin-bottom: var(--space-3);"></div>
      <div id="task-list" class="stack"></div>
    </div>
    <div id="bulk-bar-root"></div>
  `;

  const selection = { mode: false, ids: new Set() };

  container.querySelector("#search-input").addEventListener(
    "input",
    debounce((e) => {
      state.q = e.target.value;
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
  await loadToday(container);
  await refreshTaskList(container, selection, writable);
}

async function loadStats(container) {
  const statRoot = container.querySelector("#stat-cards");
  const goalRoot = container.querySelector("#goal-progress");
  if (!statRoot) return;

  try {
    const [me, settings, board] = await Promise.all([
      api.get(`${HB}/me`),
      api.get(`${HB}/settings`),
      api.get(`${HB}/points/leaderboard?since=${encodeURIComponent(startOfWeekIso())}`),
    ]);
    const mine = board.find((row) => row.user.id === me.id);
    const weekPoints = mine ? mine.total_points : 0;

    statRoot.innerHTML = `
      <div class="stat-card">
        <div class="stat-value">${weekPoints}</div>
        <div class="stat-label">Points this week</div>
      </div>
      <div class="stat-card">
        <div class="stat-value">${me.on_break ? "On break" : "Active"}</div>
        <div class="stat-label">${escapeHtml(me.display_name)}</div>
      </div>
    `;

    if (settings.weekly_points_goal) {
      const pct = Math.min(100, Math.round((weekPoints / settings.weekly_points_goal) * 100));
      goalRoot.innerHTML = `
        <div class="muted row-between" style="font-size: var(--font-size-xs); margin: var(--space-3) 0 4px;">
          <span>Weekly goal</span><span>${weekPoints} / ${settings.weekly_points_goal}</span>
        </div>
        <div class="progress-bar"><div class="progress-bar-fill" style="width:${pct}%;"></div></div>
      `;
    } else {
      goalRoot.innerHTML = "";
    }
  } catch {
    statRoot.innerHTML = `<div class="empty-state" style="grid-column: 1/-1;">Couldn't load stats</div>`;
  }
}

async function loadToday(container) {
  const root = container.querySelector("#today-list");
  if (!root) return;
  root.innerHTML = `<div class="skeleton" style="height: 64px;"></div>`;

  try {
    if (!allTasksCache) allTasksCache = await api.get(`${HB}/tasks?active=true`);
    const wd = todayWeekday();
    const todays = allTasksCache.filter((t) => !t.weekdays || t.weekdays.includes(wd));
    renderTaskRows(root, todays, container, null, "Nothing scheduled for today");
  } catch {
    root.innerHTML = `<div class="empty-state">Couldn't load today's tasks</div>`;
  }
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

  const chips = [{ id: "", label: "All" }, ...categoriesCache.map((c) => ({
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
      renderCategoryChips(container, selection, writable);
      refreshTaskList(container, selection, writable);
    });
  });
}

async function refreshTaskList(container, selection, writable) {
  const root = container.querySelector("#task-list");
  if (!root) return;

  if (!allTasksCache) {
    root.innerHTML = `<div class="skeleton" style="height: 64px;"></div>`;
    try {
      allTasksCache = await api.get(`${HB}/tasks?active=true`);
    } catch {
      root.innerHTML = `<div class="empty-state">Couldn't load tasks</div>`;
      return;
    }
  }

  let filtered = allTasksCache;
  if (state.q) {
    const q = state.q.toLowerCase();
    filtered = filtered.filter((t) => t.name.toLowerCase().includes(q));
  }
  if (state.categoryId) {
    filtered = filtered.filter((t) => t.categories.some((c) => String(c.id) === state.categoryId));
  }

  renderTaskRows(root, filtered, container, writable ? selection : null, "No tasks match");
  renderBulkBar(container, selection, writable);
}

function taskRow(task, { selection, onToggleSelect, onComplete, writable }) {
  const row = document.createElement("div");
  row.className = "list-row";

  const inSelectMode = Boolean(selection && selection.mode);
  const isSelected = inSelectMode && selection.ids.has(task.id);
  row.classList.toggle("selected", isSelected);

  const catLabel = task.categories.map((c) => (c.icon ? `${c.icon} ${c.name}` : c.name)).join(" · ");
  const schedule = task.weekdays && task.weekdays.length ? task.weekdays.map((w) => WEEKDAY_LABELS[w]).join(" ") : "Every day";

  row.innerHTML = `
    ${inSelectMode ? `<div class="list-row-select">${icons.check}</div>` : ""}
    <div class="list-row-body">
      <div class="list-row-title">${escapeHtml(task.name)}</div>
      <div class="list-row-meta">
        ${catLabel ? `<span>${escapeHtml(catLabel)}</span>` : ""}
        <span>${escapeHtml(schedule)}${task.times_per_day > 1 ? ` · ${task.times_per_day}×/day` : ""}</span>
        ${task.ramp_up_enabled ? `<span class="badge badge-info">+${task.ramp_up_bonus_points} bonus</span>` : ""}
      </div>
    </div>
    <div class="list-row-points"><span>${task.points}</span><span class="muted">pts</span></div>
    ${writable && !inSelectMode ? `<div class="list-row-actions"><button class="btn btn-icon btn-primary" data-action="complete" aria-label="Complete ${escapeAttr(task.name)}">${icons.check}</button></div>` : ""}
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
        onComplete: async (t) => {
          try {
            await api.post(`${HB}/tasks/${t.id}/complete`);
            showToast(`Logged "${t.name}" (+${t.points} pts)`, "success");
            loadStats(container);
          } catch {
            /* api.js already showed a toast */
          }
        },
      })
    );
  });
}

function renderBulkBar(container, selection, writable) {
  const root = container.querySelector("#bulk-bar-root");
  if (!root) return;
  if (!writable || !selection.mode) {
    root.innerHTML = "";
    return;
  }

  const count = selection.ids.size;
  root.innerHTML = `
    <div class="bulk-bar">
      <span class="count-label">${count} selected</span>
      <button class="btn btn-icon" id="bulk-cancel" aria-label="Cancel selection">${icons.close}</button>
      <button class="btn btn-primary grow" id="bulk-complete-btn" ${count === 0 ? "disabled" : ""}>${icons.check}<span>Complete</span></button>
    </div>
  `;

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
    showToast(
      `Completed ${completed} of ${ids.length} task${ids.length === 1 ? "" : "s"}`,
      completed === ids.length ? "success" : "warning"
    );
    exitSelectMode();
    loadStats(container);
    refreshTaskList(container, selection, writable);
  });
}
