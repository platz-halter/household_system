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
import { escapeHtml } from "./util.js";

const HB = CONFIG.HOUSEHOLD_BASE;

function openOverlay(titleText) {
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

// A simple pick-one list of saved event groups — no search/category
// filter like taskPicker.js, since a household realistically has a
// handful of these, not dozens of tasks. `onSelect` gets the full
// EventGroupOut; the picker closes itself either way (picking, or the
// empty/error state's "close" works the normal way via the X/backdrop).
export function openEventGroupPickerModal({ onSelect }) {
  const { body, close } = openOverlay("Trigger an event group");
  body.innerHTML = `<div id="egp-list" class="stack"><div class="skeleton" style="height: 56px;"></div></div>`;

  (async () => {
    let groups;
    try {
      groups = await api.get(`${HB}/event-groups`);
    } catch {
      body.querySelector("#egp-list").innerHTML = `<div class="empty-state">Couldn't load event groups</div>`;
      return;
    }
    const listRoot = body.querySelector("#egp-list");
    if (groups.length === 0) {
      listRoot.innerHTML = `
        <div class="empty-state">
          <p style="margin: 0 0 var(--space-3);">No event groups yet</p>
          <button type="button" class="btn btn-primary" id="egp-go-to-tasks">Create one on the Tasks page</button>
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
          <div class="list-row-meta"><span>${group.roots.length} task${group.roots.length === 1 ? "" : "s"}</span></div>
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
export function openTriggerConfirmModal(group, { onTriggered } = {}) {
  const { body, close } = openOverlay(`Trigger "${group.name}"`);
  body.innerHTML = `
    <p class="muted" style="font-size: var(--font-size-sm); margin-top: 0;">This creates:</p>
    <div id="eg-trigger-preview" class="stack"><div class="skeleton" style="height: 40px;"></div></div>
    <div class="modal-footer">
      <button class="btn btn-primary grow" id="eg-trigger-confirm" disabled>Create tasks</button>
    </div>
  `;

  (async () => {
    let items = [];
    try {
      items = await api.post(`${HB}/event-groups/preview`, {
        root_task_ids: group.roots.map((r) => r.task_id),
        excluded_task_ids: group.excluded_task_ids,
      });
    } catch {
      body.querySelector("#eg-trigger-preview").innerHTML = `<div class="empty-state">Couldn't load preview</div>`;
      return;
    }

    // Roots and their chain descendants are now ALL created in this
    // one trigger (chain tasks spawn alongside their parent, not after
    // it's completed — see crud._spawn_chain_children_on_creation), so
    // every row gets the same "Created now"; "Chained from" is just
    // lineage, not a timing claim the way "After: X" used to read.
    body.querySelector("#eg-trigger-preview").innerHTML = items.length
      ? items
          .map(
            (item) => `
        <div class="eg-preview-row${item.is_root ? "" : " eg-preview-descendant"}">
          <span class="eg-preview-title">${escapeHtml(item.task_name)}</span>
          <span class="badge badge-success">Created now</span>
          ${
            item.is_root
              ? ""
              : `<span class="badge badge-neutral">Chained from: ${escapeHtml(item.parent_task_name)}</span>
                 <span class="badge ${item.excluded ? "badge-neutral" : "badge-info"}">${item.excluded ? "Not grouped" : "Grouped"}</span>`
          }
        </div>`
          )
          .join("")
      : `<span class="muted" style="font-size: var(--font-size-sm);">Nothing to create</span>`;

    const confirmBtn = body.querySelector("#eg-trigger-confirm");
    confirmBtn.disabled = items.filter((i) => i.is_root).length === 0;

    confirmBtn.addEventListener("click", async () => {
      confirmBtn.disabled = true;
      try {
        const result = await api.post(`${HB}/event-groups/${group.id}/trigger`);
        const count = result.todos.length;
        showToast(`Created ${count} task${count === 1 ? "" : "s"} for "${group.name}"`, "success");
        close();
        onTriggered?.(result);
      } catch {
        // api.js already showed a toast — e.g. a root went inactive since
        // this group was saved (re-validated server-side at trigger time).
        confirmBtn.disabled = false;
      }
    });
  })();
}
