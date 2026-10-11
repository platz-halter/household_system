// Shared between tasks.js (the Event Groups management section) and
// board.js (a manual "trigger an event group" shortcut right from the
// board, instead of needing to go to the Tasks page) — see each
// export's own docstring. Kept here rather than duplicated because
// both call sites need the exact same trigger-confirmation behavior:
// re-fetching the preview fresh and showing every row's timing/
// grouping before anything is actually created.
import { CONFIG } from "./config.js";
import { api } from "./api.js";
import { icons } from "./icons.js";
import { showToast } from "./toast.js";
import { navigate } from "./router.js";
import { escapeHtml, escapeAttr } from "./util.js";
import { openTaskPickerModal } from "./taskPicker.js";
import { t } from "./i18n.js";

const HB = CONFIG.HOUSEHOLD_BASE;

function openOverlay(titleText) {
  const overlay = document.createElement("div");
  overlay.className = "modal-overlay";
  overlay.innerHTML = `
    <div class="modal" role="dialog" aria-modal="true">
      <div class="modal-header">
        <h2>${escapeHtml(titleText)}</h2>
        <button class="btn btn-icon btn-ghost" id="modal-close" aria-label="${escapeHtml(t("common.close"))}">${icons.close}</button>
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

// A simple pick-one list of saved event groups — no search/category
// filter like taskPicker.js, since a household realistically has a
// handful of these, not dozens of tasks. `onSelect` gets the full
// EventGroupOut; the picker closes itself either way (picking, or the
// empty/error state's "close" works the normal way via the X/backdrop).
export function openEventGroupPickerModal({ onSelect }) {
  const { body, close } = openOverlay(t("eg.trigger_modal_title"));
  body.innerHTML = `<div id="egp-list" class="stack"><div class="skeleton" style="height: 56px;"></div></div>`;

  (async () => {
    let groups;
    try {
      groups = await api.get(`${HB}/event-groups`);
    } catch {
      body.querySelector("#egp-list").innerHTML = `<div class="empty-state">${escapeHtml(t("eg.couldnt_load"))}</div>`;
      return;
    }
    const listRoot = body.querySelector("#egp-list");
    if (groups.length === 0) {
      listRoot.innerHTML = `
        <div class="empty-state">
          <p style="margin: 0 0 var(--space-3);">${escapeHtml(t("eg.no_groups_yet"))}</p>
          <button type="button" class="btn btn-primary" id="egp-go-to-tasks">${escapeHtml(t("eg.create_on_tasks_page"))}</button>
        </div>`;
      listRoot.querySelector("#egp-go-to-tasks").addEventListener("click", () => {
        close();
        navigate("/tasks");
      });
      return;
    }
    listRoot.innerHTML = "";
    groups.forEach((group) => {
      const row = document.createElement("button");
      row.type = "button";
      row.className = "list-row";
      row.innerHTML = `
        <div class="list-row-body">
          <div class="list-row-title">${escapeHtml(group.name)}</div>
          <div class="list-row-meta"><span>${escapeHtml(t("common.task_count", { n: group.roots.length, count: group.roots.length }))}</span></div>
        </div>
      `;
      row.addEventListener("click", () => {
        close();
        onSelect(group);
      });
      listRoot.appendChild(row);
    });
  })();
}

// Shows exactly what triggering will create RIGHT NOW — re-fetches the
// preview fresh (not the group's last-saved shape) since a chain link
// could have been added, or a root could have gone inactive, since
// this group was last saved. Every row shows "Created now" — roots and
// their chain descendants are all created in this one trigger, not
// just the roots — plus, for a descendant, which root it's chained
// from and whether it's tagged into the group or excluded. The user
// explicitly asked to see everything a trigger will create before it
// happens.
// `onTriggered(result)` fires after a successful trigger, right before
// the modal closes — board.js uses it to refresh the todo list; the
// Tasks page's own event-group list doesn't change on a trigger, so it
// has nothing to pass here.
//
// `rootTaskIds` is a LOCAL, mutable working copy of the group's own
// saved roots — swapping one (user request: "ability to swap out one
// task before creation[, which] doesn't modify the event group on next
// creation") only ever changes this in-memory array and what gets sent
// to the trigger call (EventGroupTriggerIn.root_task_ids), never the
// saved EventGroup/EventGroupTask rows — closing this modal (confirm OR
// cancel) discards it either way, so the group's normal roots are
// exactly what the NEXT trigger (manual or scheduled) uses again.
export function openTriggerConfirmModal(group, { onTriggered } = {}) {
  const { body, close } = openOverlay(t("eg.trigger_title", { name: group.name }));
  body.innerHTML = `
    <p class="muted" style="font-size: var(--font-size-sm); margin-top: 0;">${escapeHtml(t("eg.this_creates"))}</p>
    <div id="eg-trigger-preview" class="stack"><div class="skeleton" style="height: 40px;"></div></div>
    <div class="modal-footer">
      <button class="btn btn-primary grow" id="eg-trigger-confirm" disabled>${escapeHtml(t("eg.create_tasks_btn"))}</button>
    </div>
  `;

  let rootTaskIds = group.roots.map((r) => r.task_id);
  let swapPickerData = null; // lazy-fetched — only needed once a swap is actually attempted

  async function loadSwapPickerData() {
    if (swapPickerData) return swapPickerData;
    try {
      const [tasks, categories] = await Promise.all([
        api.get(`${HB}/tasks?active=true`),
        api.get(`${HB}/categories`),
      ]);
      swapPickerData = { tasks, categories };
    } catch {
      swapPickerData = { tasks: [], categories: [] };
    }
    return swapPickerData;
  }

  async function renderPreview() {
    const previewRoot = body.querySelector("#eg-trigger-preview");
    let items = [];
    try {
      items = await api.post(`${HB}/event-groups/preview`, {
        root_task_ids: rootTaskIds,
        excluded_task_ids: group.excluded_task_ids,
      });
    } catch {
      previewRoot.innerHTML = `<div class="empty-state">${escapeHtml(t("tasks.couldnt_load_preview"))}</div>`;
      return;
    }

    // Roots and their chain descendants are now ALL created in this
    // one trigger (chain tasks spawn alongside their parent, not after
    // it's completed — see crud._spawn_chain_children_on_creation), so
    // every row gets the same "Created now"; "Chained from" is just
    // lineage, not a timing claim the way "After: X" used to read.
    previewRoot.innerHTML = items.length
      ? items
          .map(
            (item) => `
        <div class="eg-preview-row${item.is_root ? "" : " eg-preview-descendant"}">
          <span class="eg-preview-title">${escapeHtml(item.task_name)}</span>
          <span class="badge badge-success">${escapeHtml(t("common.created_now_badge"))}</span>
          ${
            item.is_root
              ? `<button class="btn btn-icon" data-swap-root="${item.task_id}" aria-label="${escapeAttr(t("eg.swap_task_aria", { name: item.task_name }))}" title="${escapeAttr(t("eg.swap_task_title"))}">${icons.swap}</button>`
              : `<span class="badge badge-neutral">${escapeHtml(t("common.chained_from", { name: item.parent_task_name }))}</span>
                 <span class="badge ${item.excluded ? "badge-neutral" : "badge-info"}">${item.excluded ? escapeHtml(t("eg.not_grouped")) : escapeHtml(t("eg.grouped"))}</span>`
          }
        </div>`
          )
          .join("")
      : `<span class="muted" style="font-size: var(--font-size-sm);">${escapeHtml(t("eg.nothing_to_create"))}</span>`;

    previewRoot.querySelectorAll("[data-swap-root]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const currentTaskId = Number(btn.dataset.swapRoot);
        const { tasks, categories } = await loadSwapPickerData();
        const candidates = tasks.filter(
          (candidate) =>
            !candidate.is_chain_child &&
            (candidate.id === currentTaskId || !rootTaskIds.includes(candidate.id))
        );
        openTaskPickerModal({
          tasks: candidates,
          categories,
          title: t("eg.swap_task_title"),
          onSelect: (picked) => {
            const index = rootTaskIds.indexOf(currentTaskId);
            if (index !== -1) rootTaskIds[index] = picked.id;
            renderPreview();
          },
        });
      });
    });

    const confirmBtn = body.querySelector("#eg-trigger-confirm");
    confirmBtn.disabled = items.filter((i) => i.is_root).length === 0;
  }

  renderPreview();

  body.querySelector("#eg-trigger-confirm").addEventListener("click", async () => {
    const confirmBtn = body.querySelector("#eg-trigger-confirm");
    confirmBtn.disabled = true;
    try {
      const result = await api.post(`${HB}/event-groups/${group.id}/trigger`, {
        root_task_ids: rootTaskIds,
      });
      const count = result.todos.length;
      showToast(t("eg.created_toast", { n: count, count, name: group.name }), "success");
      close();
      onTriggered?.(result);
    } catch {
      // api.js already showed a toast — e.g. a root went inactive since
      // this group was saved (re-validated server-side at trigger time).
      confirmBtn.disabled = false;
    }
  });
}
