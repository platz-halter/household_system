import { icons } from "./icons.js";

/**
 * Shows a styled confirmation modal (replaces window.confirm()). Resolves
 * true if the user confirms, false if they cancel, dismiss via backdrop
 * click, or press Escape.
 *
 * @param {{title?: string, message: string, confirmLabel?: string, cancelLabel?: string, danger?: boolean}} opts
 */
export function showConfirmDialog({
  title = "Are you sure?",
  message,
  confirmLabel = "Confirm",
  cancelLabel = "Cancel",
  danger = false,
} = {}) {
  return new Promise((resolve) => {
    const overlay = document.createElement("div");
    overlay.className = "modal-overlay";
    overlay.innerHTML = `
      <div class="modal confirm-modal" role="alertdialog" aria-modal="true" aria-labelledby="confirm-title">
        <div class="modal-header">
          <h2 id="confirm-title">${escapeHtml(title)}</h2>
          <button class="btn btn-icon btn-ghost" id="confirm-close" aria-label="Close">${icons.close}</button>
        </div>
        <p class="muted">${escapeHtml(message)}</p>
        <div class="modal-footer">
          <button class="btn grow" id="confirm-cancel">${escapeHtml(cancelLabel)}</button>
          <button class="btn ${danger ? "btn-danger" : "btn-primary"} grow" id="confirm-ok">${escapeHtml(confirmLabel)}</button>
        </div>
      </div>
    `;
    document.body.appendChild(overlay);

    let settled = false;
    const finish = (result) => {
      if (settled) return;
      settled = true;
      document.removeEventListener("keydown", onKeydown);
      overlay.remove();
      resolve(result);
    };

    const onKeydown = (e) => {
      if (e.key === "Escape") finish(false);
    };
    document.addEventListener("keydown", onKeydown);

    overlay.addEventListener("click", (e) => {
      if (e.target === overlay) finish(false);
    });
    overlay.querySelector("#confirm-close").addEventListener("click", () => finish(false));
    overlay.querySelector("#confirm-cancel").addEventListener("click", () => finish(false));
    overlay.querySelector("#confirm-ok").addEventListener("click", () => finish(true));
    overlay.querySelector("#confirm-ok").focus();
  });
}

function escapeHtml(str) {
  return String(str ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
}
