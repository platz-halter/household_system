import { CONFIG } from "./config.js";
import { api } from "./api.js";
import { icons } from "./icons.js";
import { showToast } from "./toast.js";
import { escapeHtml, escapeAttr, showSkeletonAfterDelay } from "./util.js";
import { showConfirmDialog } from "./confirmDialog.js";

const HB = CONFIG.HOUSEHOLD_BASE;
const AUTH_BASE = CONFIG.AUTH_BASE;

// This page is the one place in the app where "admin" means something
// different from "user" (see PROJECT_SPEC.md). The router already redirects
// non-admins away from /admin before this ever renders; this check is just
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
        <h3>Week start</h3>
        <p class="muted" style="font-size: var(--font-size-xs); margin-top: -4px;">
          Which day "this week" starts on — everywhere points/goals/reports
          are tracked by week (Home, Stats, the balancer, weekly reports).
        </p>
        <div id="week-start-root"></div>
      </div>

      <div class="settings-section">
        <h3>Weekly points goal</h3>
        <div id="goal-root"></div>
      </div>

      <div class="settings-section">
        <h3>Points &rarr; money conversion</h3>
        <p class="muted" style="font-size: var(--font-size-xs); margin-top: -4px;">
          Reference only — shown next to points, no real payout is connected.
        </p>
        <div id="money-root"></div>
      </div>

      <div class="settings-section">
        <h3>Reminders</h3>
        <p class="muted" style="font-size: var(--font-size-xs); margin-top: -4px;">
          Pushes anyone subscribed (Settings &rarr; Notifications) who's below
          the weekly goal, or everyone if no goal is set — so it won't send
          you anything once you've already hit it this week. To check push
          delivery itself works regardless of points, use "Send test
          notification" in Settings &rarr; Notifications instead.
        </p>
        <button class="btn btn-block" id="nudge-btn" style="margin-bottom: var(--space-3);">${icons.checklist}<span>Send weekly reminder now</span></button>
        <div id="schedule-root"></div>
      </div>

      <div class="settings-section">
        <h3>Task balancing</h3>
        <p class="muted" style="font-size: var(--font-size-xs); margin-top: -4px;">
          Hands out unclaimed weekly/monthly tasks and unclaimed board todos to
          whoever's currently carrying the least load, then pulls an unfinished
          task away from anyone who's pulled well ahead and hands it to whoever's
          behind — favoring anyone short of the weekly goal, never overloading
          one person, and never touching a task someone's already started. Runs
          automatically once a day; use this to run it right now instead of
          waiting.
        </p>
        <button class="btn btn-block" id="balance-btn">${icons.scale}<span>Run balancer now</span></button>
        <div id="balance-result-root" style="margin-top: var(--space-3);"></div>
      </div>

      <div class="settings-section">
        <div class="row-between">
          <h3 style="margin-bottom: 0;">Reports</h3>
          <button class="btn btn-icon" id="new-report-btn" aria-label="Generate report">${icons.plus}</button>
        </div>
        <div id="auto-report-root" style="margin-bottom: var(--space-3);"></div>
        <div id="reports-root"></div>
      </div>

      <div class="settings-section">
        <h3>Authentik connection</h3>
        <p class="muted" style="font-size: var(--font-size-xs); margin-top: -4px;">
          Change the Authentik OIDC settings here instead of hand-editing
          <code>.env</code> on the server — every service picks up a
          change within about a minute, no restart needed. Changing the
          issuer, JWKS URL, or client ID will sign out anyone currently
          logged in through Authentik (local accounts are unaffected).
          Saving or resetting always requires your LOCAL admin password
          below, even if you're signed in through Authentik right now —
          whoever can repoint these values controls who every service
          trusts as an admin, so a currently-valid session alone isn't
          enough.
        </p>
        <div id="authentik-config-root"></div>
      </div>
    </div>
  `;

  container.querySelector("#nudge-btn").addEventListener("click", async () => {
    const btn = container.querySelector("#nudge-btn");
    btn.disabled = true;
    try {
      const result = await api.post(`${HB}/push/nudge`);
      showToast(
        `Notified ${result.notified} · ${result.skipped_already_met_goal} already at goal · ${result.skipped_no_subscription} not subscribed/unreachable`,
        "success"
      );
    } catch {
      /* api.js already showed a toast */
    } finally {
      btn.disabled = false;
    }
  });

  container.querySelector("#new-report-btn").addEventListener("click", () => openReportModal(container));

  container.querySelector("#balance-btn").addEventListener("click", async () => {
    const btn = container.querySelector("#balance-btn");
    btn.disabled = true;
    try {
      const result = await api.post(`${HB}/balancing/run`);
      renderBalanceResult(container, result);
      showToast("Balancing run complete", "success");
    } catch {
      /* api.js already showed a toast */
    } finally {
      btn.disabled = false;
    }
  });

  await loadWeekStart(container);
  await loadGoal(container);
  await loadMoneyRate(container);
  await loadSchedule(container);
  await loadAutoReport(container);
  await loadReports(container);
  await loadAuthentikConfig(container);
}

async function loadWeekStart(container) {
  const root = container.querySelector("#week-start-root");
  if (!root) return;
  const cancelSkeleton = showSkeletonAfterDelay(root, `<div class="skeleton" style="height: 56px;"></div>`);
  try {
    const settings = await api.get(`${HB}/settings`);
    cancelSkeleton();
    root.innerHTML = `
      <div class="row">
        <select class="select grow" id="week-start-select">
          ${WEEKDAY_NAMES.map((name, i) => `<option value="${i}" ${settings.week_start_weekday === i ? "selected" : ""}>${name}</option>`).join("")}
        </select>
        <button class="btn btn-primary" id="week-start-save">Save</button>
      </div>
    `;
    root.querySelector("#week-start-save").addEventListener("click", async () => {
      try {
        await patchSettings({ week_start_weekday: Number(root.querySelector("#week-start-select").value) });
        showToast('Saved — "this week" now starts on that day everywhere', "success");
      } catch {
        /* api.js already showed a toast */
      }
    });
  } catch {
    cancelSkeleton();
    root.innerHTML = `<div class="empty-state">Couldn't load settings</div>`;
  }
}

async function loadGoal(container) {
  const root = container.querySelector("#goal-root");
  if (!root) return;
  const cancelSkeleton = showSkeletonAfterDelay(root, `<div class="skeleton" style="height: 56px;"></div>`);
  try {
    const settings = await api.get(`${HB}/settings`);
    cancelSkeleton();
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
    cancelSkeleton();
    root.innerHTML = `<div class="empty-state">Couldn't load settings</div>`;
  }
}

// Common currencies for the dropdown — not an exhaustive ISO 4217 list,
// just enough for a homelab household. The backend accepts any 3-letter
// code; this just keeps the picker sane.
const CURRENCIES = ["EUR", "USD", "GBP", "CHF", "SEK", "NOK", "DKK", "PLN", "CZK", "JPY", "CAD", "AUD"];

async function loadMoneyRate(container) {
  const root = container.querySelector("#money-root");
  if (!root) return;
  const cancelSkeleton = showSkeletonAfterDelay(root, `<div class="skeleton" style="height: 56px;"></div>`);
  try {
    const settings = await api.get(`${HB}/settings`);
    cancelSkeleton();
    root.innerHTML = `
      <div class="field-row">
        <div class="field">
          <label for="currency-select">Currency</label>
          <select class="select" id="currency-select">
            ${CURRENCIES.map((c) => `<option value="${c}" ${settings.currency === c ? "selected" : ""}>${c}</option>`).join("")}
          </select>
        </div>
        <div class="field">
          <label for="rate-input">Per point</label>
          <input class="input" type="number" min="0" step="0.01" id="rate-input" value="${settings.points_to_money_rate ?? ""}" placeholder="No rate set" />
        </div>
      </div>
      <button class="btn btn-primary btn-block" id="money-save" style="margin-top: var(--space-2);">Save</button>
    `;
    root.querySelector("#money-save").addEventListener("click", async () => {
      const raw = root.querySelector("#rate-input").value;
      try {
        await patchSettings({
          points_to_money_rate: raw === "" ? null : Number(raw),
          currency: root.querySelector("#currency-select").value,
        });
        showToast("Saved", "success");
      } catch {
        /* api.js already showed a toast */
      }
    });
  } catch {
    cancelSkeleton();
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
    points_to_money_rate: current.points_to_money_rate,
    currency: current.currency,
    nudge_weekday: current.nudge_weekday,
    nudge_hour: current.nudge_hour,
    week_start_weekday: current.week_start_weekday,
    auto_report_enabled: current.auto_report_enabled,
    ...partial,
  });
}

async function loadSchedule(container) {
  const root = container.querySelector("#schedule-root");
  if (!root) return;
  const cancelSkeleton = showSkeletonAfterDelay(root, `<div class="skeleton" style="height: 56px;"></div>`);
  try {
    const settings = await api.get(`${HB}/settings`);
    cancelSkeleton();
    const lastSent = settings.last_nudge_sent_week
      ? `Last sent automatically: week of ${settings.last_nudge_sent_week}`
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
    cancelSkeleton();
    root.innerHTML = `<div class="empty-state">Couldn't load the reminder schedule</div>`;
  }
}

function renderBalanceResult(container, result) {
  const root = container.querySelector("#balance-result-root");
  if (!root) return;

  if (result.by_user.length === 0 && result.reassignments.length === 0) {
    root.innerHTML = `<div class="empty-state">Nothing to assign or rebalance — everything's already claimed or caught up</div>`;
    return;
  }

  const rows = result.by_user
    .map((u) => {
      const bits = [`${u.new_task_count} task${u.new_task_count === 1 ? "" : "s"}`, `${u.new_todo_count} todo${u.new_todo_count === 1 ? "" : "s"}`];
      if (u.reassigned_in_count) bits.push(`+${u.reassigned_in_count} moved to them`);
      if (u.reassigned_out_count) bits.push(`-${u.reassigned_out_count} moved away`);
      const netPoints = u.new_expected_points + u.reassigned_net_points;
      return `
      <div class="list-row" style="cursor:default;">
        <div class="list-row-body">
          <div class="list-row-title">${escapeHtml(u.household_user.display_name)}</div>
          <div class="list-row-meta"><span>${bits.join(" · ")}</span></div>
        </div>
        <div class="list-row-points"><span>${netPoints >= 0 ? "+" : ""}${netPoints}</span><span class="muted">pts</span></div>
      </div>`;
    })
    .join("");

  const reassignmentRows = result.reassignments
    .map(
      (r) => `
      <div class="list-row" style="cursor:default;">
        <div class="list-row-body">
          <div class="list-row-title">${escapeHtml(r.task_name)}</div>
          <div class="list-row-meta"><span>${escapeHtml(r.from_user.display_name)} &rarr; ${escapeHtml(r.to_user.display_name)} — pulled away unfinished to even out the week</span></div>
        </div>
        <div class="list-row-points"><span>${r.points}</span><span class="muted">pts</span></div>
      </div>`
    )
    .join("");

  const leftover =
    result.unassigned_task_count || result.unassigned_todo_count
      ? `<p class="muted" style="font-size: var(--font-size-xs); margin-top: var(--space-2);">
           ${result.unassigned_task_count} task(s) and ${result.unassigned_todo_count} todo(s) left unassigned this
           run — everyone eligible is already at the per-run cap.
         </p>`
      : "";

  root.innerHTML = `
    ${rows ? `<div class="stack">${rows}</div>` : ""}
    ${
      reassignmentRows
        ? `<p class="muted" style="font-size: var(--font-size-xs); margin: var(--space-3) 0 4px;">Mid-week rebalancing</p><div class="stack">${reassignmentRows}</div>`
        : ""
    }
    ${leftover}
  `;
}

async function loadAutoReport(container) {
  const root = container.querySelector("#auto-report-root");
  if (!root) return;
  const cancelSkeleton = showSkeletonAfterDelay(root, `<div class="skeleton" style="height: 56px;"></div>`);
  try {
    const settings = await api.get(`${HB}/settings`);
    cancelSkeleton();
    const lastAuto = settings.last_auto_report_period
      ? `Last auto-generated: week of ${settings.last_auto_report_period}`
      : "Hasn't run automatically yet";
    root.innerHTML = `
      <div class="field">
        <label class="row">
          <input type="checkbox" id="auto-report-enabled" ${settings.auto_report_enabled ? "checked" : ""} />
          <span>Auto-generate a report for each week once it ends</span>
        </label>
      </div>
      <div class="row" style="margin-top: var(--space-2);">
        <span class="muted" style="font-size: var(--font-size-xs); flex: 1;">${lastAuto}</span>
        <button class="btn btn-primary" id="auto-report-save">Save</button>
      </div>
    `;
    root.querySelector("#auto-report-save").addEventListener("click", async () => {
      try {
        await patchSettings({ auto_report_enabled: root.querySelector("#auto-report-enabled").checked });
        showToast("Saved", "success");
      } catch {
        /* api.js already showed a toast */
      }
    });
  } catch {
    cancelSkeleton();
    root.innerHTML = `<div class="empty-state">Couldn't load settings</div>`;
  }
}

async function loadReports(container) {
  const root = container.querySelector("#reports-root");
  if (!root) return;
  const cancelSkeleton = showSkeletonAfterDelay(root, `<div class="skeleton" style="height: 100px;"></div>`);
  try {
    const reports = await api.get(`${HB}/reports`);
    cancelSkeleton();
    if (reports.length === 0) {
      root.innerHTML = `<div class="empty-state">No reports generated yet</div>`;
      return;
    }
    // A plain div, not a <button> — it now holds two separate actions
    // (download, toggle-paid), and a <button> can't contain another
    // interactive element.
    root.innerHTML = reports
      .map((r) => {
        const paid = Boolean(r.paid_at);
        return `
        <div class="list-row" data-report-id="${r.id}" data-period="${r.period_start}" data-paid="${paid}" style="${paid ? "opacity: 0.6;" : ""}">
          <div class="list-row-body">
            <div class="list-row-title">
              ${r.period_type === "week" ? "Weekly" : "Monthly"} report
              ${r.is_last_week ? `<span class="badge badge-info">Last week</span>` : ""}
              <span class="badge badge-${paid ? "success" : "neutral"}">${paid ? "Paid" : "Unpaid"}</span>
            </div>
            <div class="list-row-meta">
              <span>${r.period_start} – ${r.period_end}</span>
              ${r.generated_by ? "" : `<span class="muted">· auto</span>`}
            </div>
          </div>
          <div class="list-row-actions">
            <button class="btn btn-icon" data-action="toggle-paid" aria-label="${paid ? "Mark unpaid" : "Mark paid"}" title="${paid ? "Mark unpaid" : "Mark paid"}">${icons.check}</button>
            <button class="btn btn-icon" data-action="download" aria-label="Download report">${icons.chevronRight}</button>
          </div>
        </div>`;
      })
      .join("");

    root.querySelectorAll("[data-report-id]").forEach((row) => {
      const id = row.dataset.reportId;
      row.querySelector('[data-action="download"]').addEventListener("click", () => {
        downloadReport(id, row.dataset.period);
      });
      row.querySelector('[data-action="toggle-paid"]').addEventListener("click", async () => {
        const nowPaid = row.dataset.paid !== "true";
        try {
          await api.patch(`${HB}/reports/${id}`, { paid: nowPaid });
          loadReports(container);
        } catch {
          /* api.js already showed a toast */
        }
      });
    });
  } catch {
    cancelSkeleton();
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

const AUTHENTIK_FIELDS = [
  ["issuer", "Issuer"],
  ["jwks_url", "JWKS URL"],
  ["client_id", "Client ID"],
  ["authorize_url", "Authorize URL"],
  ["token_url", "Token URL"],
  ["end_session_url", "End-session URL"],
  ["scope", "Scope"],
];

async function loadAuthentikConfig(container) {
  const root = container.querySelector("#authentik-config-root");
  if (!root) return;
  const cancelSkeleton = showSkeletonAfterDelay(root, `<div class="skeleton" style="height: 320px;"></div>`);
  let config;
  try {
    config = await api.get(`${AUTH_BASE}/authentik-config`);
  } catch {
    cancelSkeleton();
    root.innerHTML = `<div class="empty-state">Couldn't load the Authentik configuration</div>`;
    return;
  }
  cancelSkeleton();

  root.innerHTML = `
    ${AUTHENTIK_FIELDS.map(
      ([key, label]) => `
      <div class="field">
        <label for="ak-${key}">${label}</label>
        <input class="input" id="ak-${key}" value="${escapeAttr(config[key])}" />
      </div>`
    ).join("")}
    <div
      class="field"
      style="margin-top: var(--space-3); padding-top: var(--space-3); border-top: 1px solid var(--border-color);"
    >
      <label for="ak-reauth-username">Confirm with your local admin username</label>
      <input class="input" id="ak-reauth-username" autocomplete="username" />
    </div>
    <div class="field">
      <label for="ak-reauth-password">...and password</label>
      <input class="input" type="password" id="ak-reauth-password" autocomplete="current-password" />
    </div>
    <div class="row" style="margin-top: var(--space-2);">
      <button class="btn" id="ak-reset">Reset to .env defaults</button>
      <button class="btn btn-primary grow" id="ak-save">Save</button>
    </div>
  `;

  function reauthBody() {
    return {
      reauth_username: root.querySelector("#ak-reauth-username").value,
      reauth_password: root.querySelector("#ak-reauth-password").value,
    };
  }

  root.querySelector("#ak-save").addEventListener("click", async () => {
    const body = {
      ...Object.fromEntries(AUTHENTIK_FIELDS.map(([key]) => [key, root.querySelector(`#ak-${key}`).value.trim()])),
      ...reauthBody(),
    };
    const btn = root.querySelector("#ak-save");
    btn.disabled = true;
    try {
      // silent: true — the generic "(403) you don't have permission" toast
      // api.js would otherwise show is wrong here: a 403 from THIS route
      // means the reauth password didn't check out, not that the caller
      // lacks the admin role (they already do, or require_role() itself
      // would have 403'd before this even ran). Show the real detail
      // message instead ("Re-authentication failed", or the issuer
      // validation failure) so the admin knows what actually went wrong.
      await api.put(`${AUTH_BASE}/authentik-config`, body, { silent: true });
      showToast("Saved — can take up to a minute to reach every service", "success");
      loadAuthentikConfig(container);
    } catch (err) {
      showToast(err.message || "Couldn't save", "danger");
    } finally {
      btn.disabled = false;
    }
  });

  root.querySelector("#ak-reset").addEventListener("click", async () => {
    const ok = await showConfirmDialog({
      title: "Reset Authentik settings?",
      message: "This reverts every service to the .env defaults. Anyone currently logged in through Authentik will be signed out.",
      confirmLabel: "Reset",
      danger: true,
    });
    if (!ok) return;
    const btn = root.querySelector("#ak-reset");
    btn.disabled = true;
    try {
      await api.post(`${AUTH_BASE}/authentik-config/reset`, reauthBody(), { silent: true });
      showToast("Reset to .env defaults", "success");
      loadAuthentikConfig(container);
    } catch (err) {
      showToast(err.message || "Couldn't reset", "danger");
    } finally {
      btn.disabled = false;
    }
  });
}
