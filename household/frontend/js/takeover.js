// Shared "takeover request" UI — the consent-based way to hand off
// something you currently hold (see PROJECT_SPEC.md's "Handing off an
// assigned task"). Used by both home.js ("Assigned to you") and
// board.js (so admins aren't limited to the instant, no-consent
// reassign there — see CLAUDE.md's "Admin reassign vs. takeover
// requests"). Kept deliberately distinct from reassign, icon- and
// wording-wise: `icons.send` + "ask"/"request" here, `icons.swap` +
// "reassign" there — the two are easy to conflate from an icon alone.
import { api } from "./api.js";
import { CONFIG } from "./config.js";
import { icons } from "./icons.js";
import { showToast } from "./toast.js";
import { escapeHtml, escapeAttr } from "./util.js";

const HB = CONFIG.HOUSEHOLD_BASE;

export function outgoingRequestFor(requests, kind, id) {
  const field = kind === "todo" ? "todo_item_id" : "task_assignment_id";
  return (requests || []).find((r) => r[field] === id);
}

// Builds either a "pending: asked X [cancel]" control or an "ask to
// take over" button, depending on whether `requests` already has a
// pending outgoing request for this item. `onChange` is called after a
// successful ask/cancel so the caller can refresh its own state (the
// request's own result isn't handed back — callers are expected to
// just refetch, same as every other mutation in this app).
export function takeoverControl({ requests, kind, id, label, onChange }) {
  const pending = outgoingRequestFor(requests, kind, id);
  if (pending) {
    const wrap = document.createElement("div");
    wrap.className = "row";
    wrap.style.gap = "4px";
    wrap.innerHTML = `
      <span class="badge badge-neutral">Asked ${escapeHtml(pending.target.display_name)}</span>
      <button type="button" class="btn btn-icon btn-ghost" aria-label="Cancel request" title="Cancel the takeover request">${icons.close}</button>
    `;
    wrap.querySelector("button").addEventListener("click", async () => {
      try {
        await api.post(`${HB}/takeover-requests/${pending.id}/cancel`);
        showToast("Request cancelled", "success");
        onChange();
      } catch {
        /* api.js already showed a toast */
      }
    });
    return wrap;
  }

  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = "btn btn-icon";
  btn.setAttribute("aria-label", "Ask someone to take over");
  btn.title = "Ask someone to take over — they'll need to accept before it moves";
  btn.innerHTML = icons.send;
  btn.addEventListener("click", () => openTakeoverRequestModal({ kind, id, label, onChange }));
  return btn;
}

async function openTakeoverRequestModal({ kind, id, label, onChange }) {
  let me, allUsers;
  try {
    [me, allUsers] = await Promise.all([api.get(`${HB}/me`), api.get(`${HB}/users`)]);
  } catch {
    return; // api.js already showed a toast
  }
  const users = allUsers.filter((u) => !u.on_break && u.id !== me.id);

  const overlay = document.createElement("div");
  overlay.className = "modal-overlay";
  overlay.innerHTML = `
    <div class="modal" role="dialog" aria-modal="true">
      <div class="modal-header">
        <h2>Ask someone to take over</h2>
        <button class="btn btn-icon btn-ghost" id="tko-close" aria-label="Close">${icons.close}</button>
      </div>
      <div class="stack">
        <div class="field">
          <label for="tko-target">"${escapeHtml(label)}" — who should take it?</label>
          <p class="muted" style="font-size: var(--font-size-xs); margin-top: 0;">
            They'll get a notification and have to accept before it actually moves — this just asks.
          </p>
          <select class="select" id="tko-target" ${users.length === 0 ? "disabled" : ""}>
            ${
              users.length === 0
                ? `<option value="">No one else is available right now</option>`
                : users.map((u) => `<option value="${u.id}">${escapeAttr(u.display_name)}</option>`).join("")
            }
          </select>
        </div>
      </div>
      <div class="modal-footer">
        <button class="btn btn-primary grow" id="tko-save" ${users.length === 0 ? "disabled" : ""}>Ask</button>
      </div>
    </div>
  `;
  document.body.appendChild(overlay);
  const close = () => overlay.remove();
  overlay.querySelector("#tko-close").addEventListener("click", close);
  overlay.addEventListener("click", (e) => {
    if (e.target === overlay) close();
  });

  overlay.querySelector("#tko-save").addEventListener("click", async () => {
    const targetId = Number(overlay.querySelector("#tko-target").value);
    const path = kind === "todo" ? `todos/${id}/takeover-requests` : `assignments/${id}/takeover-requests`;
    try {
      await api.post(`${HB}/${path}`, { target_id: targetId });
      showToast("Takeover requested", "success");
      close();
      onChange();
    } catch {
      /* api.js already showed a toast */
    }
  });
}
