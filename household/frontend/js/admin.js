import { CONFIG } from "./config.js";
import { api } from "./api.js";
import { icons } from "./icons.js";
import { showToast } from "./toast.js";

const HB = CONFIG.HOUSEHOLD_BASE;

// This page is the one place in the app where "admin" means something
// different from "user" (see PROJECT_SPEC.md). The router already redirects
// non-admins away from #/admin before this ever renders; this check is just
// defense in depth, not the real enforcement (the backend rejects a non-admin
// PUT /settings / POST /reports / POST /push/nudge regardless of the UI).
export async function renderAdmin(container) {
  container.innerHTML = `
    <div class="page">
      <div class="section-heading"><h2>Admin panel</h2></div>
      <p class="muted" style="font-size: var(--font-size-sm);">
        Settings only admins can change.
      </p>

      <div class="settings-section">
        <h3>Weekly points goal</h3>
        <div id="goal-root"><div class="skeleton" style="height: 56px;"></div></div>
      </div>

      <div class="settings-section">
        <h3>Points &rarr; EUR conversion</h3>
        <p class="muted" style="font-size: var(--font-size-xs); margin-top: -4px;">
          Reference only — shown next to points, no real payout is connected.
        </p>
        <div id="eur-root"><div class="skeleton" style="height: 56px;"></div></div>
      </div>

      <div class="settings-section">
        <h3>Reminders</h3>
        <p class="muted" style="font-size: var(--font-size-xs); margin-top: -4px;">
          Pushes anyone subscribed (Settings &rarr; Notifications) who's below
          the weekly goal, or everyone if no goal is set.
        </p>
        <button class="btn btn-block" id="nudge-btn" style="margin-bottom: var(--space-3);">${icons.checklist}<span>Send weekly reminder now</span></button>
        <div id="schedule-root"><div class="skeleton" style="height: 56px;"></div></div>
      </div>

      <div class="settings-section">
        <div class="row-between">
          <h3 style="margin-bottom: 0;">Reports</h3>
          <button class="btn btn-icon" id="new-report-btn" aria-label="Generate report">${icons.plus}</button>
        </div>
        <div id="reports-root"><div class="skeleton" style="height: 100px;"></div></div>
      </div>
    </div>
  `;

  container.querySelector("#nudge-btn").addEventListener("click", async () => {
    const btn = container.querySelector("#nudge-btn");
    btn.disabled = true;
    try {
      const result = await api.post(`${HB}/push/nudge`);
      showToast(
        `Notified ${result.notified}, skipped ${result.skipped_no_subscription} (no goal left, or not subscribed)`,
        "success"
      );
    } catch {
      /* api.js already showed a toast */
    } finally {
      btn.disabled = false;
    }
  });

  container.querySelector("#new-report-btn").addEventListener("click", () => openReportModal(container));

  await loadGoal(container);
  await loadEurRate(container);
  await loadSchedule(container);
  await loadReports(container);
}

async function loadGoal(container) {
  const root = container.querySelector("#goal-root");
  if (!root) return;
  try {
    const settings = await api.get(`${HB}/settings`);
    root.innerHTML = `
      <div class="field">
        <label for="goal-input">Points per week</label>
        <div class="row">
          <input class="input" type="number" min="0" id="goal-input" value="${settings.weekly_points_goal ?? ""}" placeholder="No goal set" />
          <button class="btn btn-primary" id="goal-save">Save</button>
        </div>
      </div>
    `;
    root.querySelector("#goal-save").addEventListener("click", async () => {
      const raw = root.querySelector("#goal-input").value;
      try {
        await patchSettings({ weekly_points_goal: raw === "" ? null : Number(raw) });
        showToast("Saved", "success");
      } catch {
        /* api.js already showed a toast */
      }
    });
  } catch {
    root.innerHTML = `<div class="empty-state">Couldn't load settings</div>`;
  }
}

async function loadEurRate(container) {
  const root = container.querySelector("#eur-root");
  if (!root) return;
  try {
    const settings = await api.get(`${HB}/settings`);
    root.innerHTML = `
      <div class="field">
        <label for="eur-input">EUR per point</label>
        <div class="row">
          <input class="input" type="number" min="0" step="0.01" id="eur-input" value="${settings.points_to_eur_rate ?? ""}" placeholder="No rate set" />
          <button class="btn btn-primary" id="eur-save">Save</button>
        </div>
      </div>
    `;
    root.querySelector("#eur-save").addEventListener("click", async () => {
      const raw = root.querySelector("#eur-input").value;
      try {
        await patchSettings({ points_to_eur_rate: raw === "" ? null : Number(raw) });
        showToast("Saved", "success");
      } catch {
        /* api.js already showed a toast */
      }
    });
  } catch {
    root.innerHTML = `<div class="empty-state">Couldn't load settings</div>`;
  }
}

const WEEKDAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];

// PUT /settings replaces the whole row, so merge with the current value of
// every field this page isn't editing right now.
async function patchSettings(partial) {
  const current = await api.get(`${HB}/settings`);
  await api.put(`${HB}/settings`, {
    weekly_points_goal: current.weekly_points_goal,
    points_to_eur_rate: current.points_to_eur_rate,
    nudge_weekday: current.nudge_weekday,
    nudge_hour: current.nudge_hour,
    ...partial,
  });
}

async function loadSchedule(container) {
  const root = container.querySelector("#schedule-root");
  if (!root) return;
  try {
    const settings = await api.get(`${HB}/settings`);
    const lastSent = settings.last_nudge_sent_week
      ? `Last sent automatically: week ${settings.last_nudge_sent_week}`
      : "Hasn't run automatically yet";

    root.innerHTML = `
      <div class="field">
        <label class="row"><input type="checkbox" id="schedule-enabled" ${settings.nudge_weekday !== null ? "checked" : ""} /> <span>Also send this automatically, every week</span></label>
      </div>
      <div class="field-row" id="schedule-fields" style="margin-top: var(--space-2); ${settings.nudge_weekday !== null ? "" : "display:none;"}">
        <div class="field">
          <label for="schedule-weekday">On</label>
          <select class="select" id="schedule-weekday">
            ${WEEKDAY_NAMES.map((name, i) => `<option value="${i}" ${settings.nudge_weekday === i ? "selected" : ""}>${name}</option>`).join("")}
          </select>
        </div>
        <div class="field">
          <label for="schedule-hour">At (UTC)</label>
          <select class="select" id="schedule-hour">
            ${Array.from({ length: 24 }, (_, h) => `<option value="${h}" ${settings.nudge_hour === h ? "selected" : ""}>${String(h).padStart(2, "0")}:00</option>`).join("")}
          </select>
        </div>
      </div>
      <div class="row" style="margin-top: var(--space-2);">
        <span class="muted" style="font-size: var(--font-size-xs); flex: 1;">${lastSent}</span>
        <button class="btn btn-primary" id="schedule-save">Save</button>
      </div>
    `;

    const enabledCheckbox = root.querySelector("#schedule-enabled");
    const fields = root.querySelector("#schedule-fields");
    enabledCheckbox.addEventListener("change", () => {
      fields.style.display = enabledCheckbox.checked ? "" : "none";
    });

    root.querySelector("#schedule-save").addEventListener("click", async () => {
      const enabled = enabledCheckbox.checked;
      try {
        await patchSettings({
          nudge_weekday: enabled ? Number(root.querySelector("#schedule-weekday").value) : null,
          nudge_hour: enabled ? Number(root.querySelector("#schedule-hour").value) : settings.nudge_hour,
        });
        showToast("Saved", "success");
      } catch {
        /* api.js already showed a toast */
      }
    });
  } catch {
    root.innerHTML = `<div class="empty-state">Couldn't load the reminder schedule</div>`;
  }
}

async function loadReports(container) {
  const root = container.querySelector("#reports-root");
  if (!root) return;
  try {
    const reports = await api.get(`${HB}/reports`);
    if (reports.length === 0) {
      root.innerHTML = `<div class="empty-state">No reports generated yet</div>`;
      return;
    }
    root.innerHTML = reports
      .map(
        (r) => `
        <button type="button" class="list-row" data-report-id="${r.id}" data-period="${r.period_start}">
          <div class="list-row-body">
            <div class="list-row-title">${r.period_type === "week" ? "Weekly" : "Monthly"} report</div>
            <div class="list-row-meta"><span>${r.period_start} – ${r.period_end}</span></div>
          </div>
          ${icons.chevronRight}
        </button>`
      )
      .join("");

    root.querySelectorAll("[data-report-id]").forEach((row) => {
      row.addEventListener("click", () => downloadReport(row.dataset.reportId, row.dataset.period));
    });
  } catch {
    root.innerHTML = `<div class="empty-state">Couldn't load reports</div>`;
  }
}

// A plain <a href> can't carry the Authorization header, so the backend
// would see no credentials at all and reject it ("Not authenticated") —
// same reason storage's item photos go through an authenticated fetch
// instead of a bare <img src>. Fetch the PDF ourselves and hand the
// browser a blob: URL to save instead.
async function downloadReport(reportId, periodStart) {
  let blob;
  try {
    blob = await api.get(`${HB}/reports/${reportId}/download`);
  } catch {
    return; // api.js already showed a toast
  }
  const objectUrl = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = objectUrl;
  link.download = `household-report-${periodStart}.pdf`;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(objectUrl);
}

function openReportModal(container) {
  const overlay = document.createElement("div");
  overlay.className = "modal-overlay";
  overlay.innerHTML = `
    <div class="modal" role="dialog" aria-modal="true">
      <div class="modal-header">
        <h2>Generate report</h2>
        <button class="btn btn-icon btn-ghost" id="modal-close" aria-label="Close">${icons.close}</button>
      </div>
      <div class="stack">
        <div class="field">
          <label for="r-period-type">Period</label>
          <select class="select" id="r-period-type">
            <option value="week">Week</option>
            <option value="month">Month</option>
          </select>
        </div>
        <div class="field">
          <label for="r-period-date">Any date within that period</label>
          <input class="input" type="date" id="r-period-date" value="${new Date().toISOString().slice(0, 10)}" />
        </div>
      </div>
      <div class="modal-footer">
        <button class="btn btn-primary grow" id="r-generate">Generate</button>
      </div>
    </div>
  `;
  document.body.appendChild(overlay);
  const close = () => overlay.remove();
  overlay.querySelector("#modal-close").addEventListener("click", close);
  overlay.addEventListener("click", (e) => {
    if (e.target === overlay) close();
  });

  overlay.querySelector("#r-generate").addEventListener("click", async () => {
    const payload = {
      period_type: overlay.querySelector("#r-period-type").value,
      period_date: overlay.querySelector("#r-period-date").value,
    };
    try {
      await api.post(`${HB}/reports`, payload);
      showToast("Report generated", "success");
      close();
      loadReports(container);
    } catch {
      /* api.js already showed a toast */
    }
  });
}
