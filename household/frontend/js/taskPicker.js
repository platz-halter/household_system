import { icons } from "./icons.js";
import { escapeHtml, escapeAttr } from "./util.js";
import { t } from "./i18n.js";

// A full-screen popup for picking a task, stacked on top of whatever
// modal opened it (same nested-overlay pattern confirmDialog.js already
// uses) — search + category chips keep it usable with a list of any
// size, unlike a native <select> on mobile. Shared between board.js
// ("From task" on a new todo, with a "Custom (one-off)" escape hatch)
// and tasks.js (picking a chain task's child, no custom option — a
// chain child always has to be a real task).
export function openTaskPickerModal({
  tasks,
  categories,
  onSelect,
  title = t("taskPicker.default_title"),
  customOption = null, // { label } to show an extra "none of these" row, or null to omit it
  emptyMessage = t("common.no_tasks_match"),
}) {
  const overlay = document.createElement("div");
  overlay.className = "modal-overlay";
  overlay.innerHTML = `
    <div class="modal" role="dialog" aria-modal="true">
      <div class="modal-header">
        <h2>${escapeHtml(title)}</h2>
        <button class="btn btn-icon btn-ghost" id="tp-close" aria-label="${escapeHtml(t("common.close"))}">${icons.close}</button>
      </div>
      <div class="search-bar" style="margin-bottom: var(--space-3);">
        ${icons.search}
        <input type="search" id="tp-search" placeholder="${escapeAttr(t("common.search_tasks_placeholder"))}" />
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
    { id: "", label: t("common.all") },
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
    if (pickerState.q) filtered = filtered.filter((task) => task.name.toLowerCase().includes(pickerState.q));
    if (pickerState.categoryId) {
      filtered = filtered.filter((task) => task.categories.some((c) => String(c.id) === pickerState.categoryId));
    }

    listRoot.innerHTML = "";

    if (customOption) {
      const customRow = document.createElement("button");
      customRow.type = "button";
      customRow.className = "list-row";
      customRow.innerHTML = `<div class="list-row-body"><div class="list-row-title">${escapeHtml(customOption.label)}</div></div>`;
      customRow.addEventListener("click", () => {
        onSelect(null);
        close();
      });
      listRoot.appendChild(customRow);
    }

    if (filtered.length === 0) {
      const empty = document.createElement("div");
      empty.className = "empty-state";
      empty.textContent = emptyMessage;
      listRoot.appendChild(empty);
      return;
    }

    // Captured before the forEach below shadows the module-level `t`
    // (translate) import with its own per-row task variable of the same
    // name — a pre-existing naming collision this file already had with
    // "task," just newly relevant now that `t` also means something.
    const ptsLabel = t("common.pts");
    filtered.forEach((task) => {
      const row = document.createElement("button");
      row.type = "button";
      row.className = "list-row";
      const catLabel = task.categories.map((c) => (c.icon ? `${c.icon} ${c.name}` : c.name)).join(" · ");
      row.innerHTML = `
        <div class="list-row-body">
          <div class="list-row-title">${escapeHtml(task.name)}</div>
          ${catLabel ? `<div class="list-row-meta"><span>${escapeHtml(catLabel)}</span></div>` : ""}
        </div>
        <div class="list-row-points"><span>${task.points}</span><span class="muted">${escapeHtml(ptsLabel)}</span></div>
      `;
      row.addEventListener("click", () => {
        onSelect(task);
        close();
      });
      listRoot.appendChild(row);
    });
  }

  renderList();
}
