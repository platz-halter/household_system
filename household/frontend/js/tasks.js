import { CONFIG } from "./config.js";
import { api } from "./api.js";
import { icons } from "./icons.js";
import { getCurrentUserInfo } from "./auth.js";
import { showToast } from "./toast.js";
import { showConfirmDialog } from "./confirmDialog.js";
import { escapeHtml, escapeAttr, WEEKDAY_LABELS } from "./util.js";

const HB = CONFIG.HOUSEHOLD_BASE;

function canWrite() {
  const info = getCurrentUserInfo();
  return info && (info.role === "admin" || info.role === "user");
}

let categoriesCache = [];

export async function renderTasks(container) {
  const writable = canWrite();

  container.innerHTML = `
    <div class="page">
      <div class="section-heading">
        <h2>Categories</h2>
        ${writable ? `<button class="btn btn-icon" id="add-category-btn" aria-label="New category">${icons.plus}</button>` : ""}
      </div>
      <div class="chip-row" id="category-list" style="margin-bottom: var(--space-2);"></div>

      <div class="section-heading"><h2>Tasks</h2></div>
      <div id="task-list" class="stack"></div>
    </div>
    ${writable ? `<button class="fab" id="add-task-fab" aria-label="New task">${icons.plus}</button>` : ""}
  `;

  if (writable) {
    container.querySelector("#add-category-btn").addEventListener("click", () => openCategoryModal(container, writable));
    container.querySelector("#add-task-fab").addEventListener("click", () => openTaskModal(container, writable));
  }

  await loadCategories(container, writable);
  await loadTasks(container, writable);
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
  root.innerHTML = `<div class="skeleton" style="height: 64px;"></div>`;

  let tasks;
  try {
    tasks = await api.get(`${HB}/tasks`);
  } catch {
    root.innerHTML = `<div class="empty-state">Couldn't load tasks</div>`;
    return;
  }

  if (tasks.length === 0) {
    root.innerHTML = `<div class="empty-state">No tasks yet${writable ? " — add one below" : ""}</div>`;
    return;
  }

  root.innerHTML = "";
  tasks.forEach((task) => root.appendChild(taskRow(task, container, writable)));
}

function taskRow(task, container, writable) {
  const row = document.createElement("div");
  row.className = "list-row";
  const catLabel = task.categories.map((c) => (c.icon ? `${c.icon} ${c.name}` : c.name)).join(" · ");
  const schedule =
    task.weekdays && task.weekdays.length ? task.weekdays.map((w) => WEEKDAY_LABELS[w]).join(" ") : "Every day";

  row.innerHTML = `
    <div class="list-row-body">
      <div class="list-row-title">${escapeHtml(task.name)} ${!task.active ? `<span class="badge badge-neutral">Inactive</span>` : ""}</div>
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

function openTaskModal(container, writable, task = null) {
  const selectedCats = new Set((task?.categories || []).map((c) => c.id));
  const selectedWeekdays = new Set(task?.weekdays || []);
  const hasSchedule = Boolean(task?.weekdays && task.weekdays.length);

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
        <label class="row"><input type="checkbox" id="f-has-schedule" ${hasSchedule ? "checked" : ""} /> <span>Only on specific weekdays</span></label>
        <div class="weekday-picker" id="f-weekdays" style="margin-top: var(--space-2);">
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
    </div>
    <div class="modal-footer">
      ${task ? `<button class="btn btn-danger" id="f-delete">${icons.trash}</button>` : ""}
      <button class="btn btn-primary grow" id="f-save">Save</button>
    </div>
  `;

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

  body.querySelector("#f-save").addEventListener("click", async () => {
    const name = body.querySelector("#f-name").value.trim();
    if (!name) {
      showToast("Name is required", "warning");
      return;
    }
    const scheduled = body.querySelector("#f-has-schedule").checked;
    const weekdays = scheduled ? [...selectedWeekdays].sort((a, b) => a - b) : null;
    if (scheduled && weekdays.length === 0) {
      showToast('Pick at least one weekday, or turn off "specific weekdays"', "warning");
      return;
    }

    const payload = {
      name,
      description: body.querySelector("#f-description").value.trim() || null,
      points: Number(body.querySelector("#f-points").value || 0),
      active: body.querySelector("#f-active").checked,
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
