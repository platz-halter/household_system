import { CONFIG } from "./config.js";
import { api } from "./api.js";
import { icons } from "./icons.js";
import { showToast } from "./toast.js";
import { escapeHtml, escapeAttr, showSkeletonAfterDelay, WEEKDAY_NAMES } from "./util.js";
import { showConfirmDialog } from "./confirmDialog.js";
import { t } from "./i18n.js";

const HB = CONFIG.HOUSEHOLD_BASE;
const AUTH_BASE = CONFIG.AUTH_BASE;

// Native self-name for each supported language, shown regardless of the
// current UI language — same reasoning as settings.js's own language
// switcher (an English-speaking admin picking a default for a German
// household should see "Deutsch," not a translated "German"). NOT run
// through t() for that reason.
const LANGUAGE_NATIVE_NAMES = { en: "English", de: "Deutsch" };

// This page is the one place in the app where "admin" means something
// different from "user" (see PROJECT_SPEC.md). The router already redirects
// non-admins away from /admin before this ever renders; this check is just
// defense in depth, not the real enforcement (the backend rejects a non-admin
// PUT /settings / POST /reports / POST /push/nudge regardless of the UI).
export async function renderAdmin(container) {
  container.innerHTML = `
    <div class="page">
      <div class="section-heading"><h2>${escapeHtml(t("admin.heading"))}</h2></div>
      <p class="muted" style="font-size: var(--font-size-sm);">
        ${escapeHtml(t("admin.subtitle"))}
      </p>

      <div class="settings-section">
        <h3>${escapeHtml(t("admin.week_start_heading"))}</h3>
        <p class="muted" style="font-size: var(--font-size-xs); margin-top: -4px;">
          ${escapeHtml(t("admin.week_start_desc"))}
        </p>
        <div id="week-start-root"></div>
      </div>

      <div class="settings-section">
        <h3>${escapeHtml(t("admin.weekly_goal_heading"))}</h3>
        <div id="goal-root"></div>
      </div>

      <div class="settings-section">
        <h3>${escapeHtml(t("admin.money_heading"))}</h3>
        <p class="muted" style="font-size: var(--font-size-xs); margin-top: -4px;">
          ${escapeHtml(t("admin.money_desc"))}
        </p>
        <div id="money-root"></div>
      </div>

      <div class="settings-section">
        <h3>${escapeHtml(t("admin.timezone_heading"))}</h3>
        <div id="timezone-root"></div>
      </div>

      <div class="settings-section">
        <h3>${escapeHtml(t("admin.default_language_heading"))}</h3>
        <div id="default-language-root"></div>
      </div>

      <div class="settings-section">
        <h3>${escapeHtml(t("admin.reminders_heading"))}</h3>
        <p class="muted" style="font-size: var(--font-size-xs); margin-top: -4px;">
          ${escapeHtml(t("admin.reminders_desc"))}
        </p>
        <button class="btn btn-block" id="nudge-btn" style="margin-bottom: var(--space-3);">${icons.checklist}<span>${escapeHtml(t("admin.send_nudge_btn"))}</span></button>
        <div id="schedule-root"></div>
      </div>

      <div class="settings-section">
        <h3>${escapeHtml(t("admin.balancing_heading"))}</h3>
        <p class="muted" style="font-size: var(--font-size-xs); margin-top: -4px;">
          ${escapeHtml(t("admin.balancing_desc"))}
        </p>
        <button class="btn btn-block" id="balance-btn">${icons.scale}<span>${escapeHtml(t("admin.run_balancer_btn"))}</span></button>
        <div id="balance-result-root" style="margin-top: var(--space-3);"></div>
      </div>

      <div class="settings-section">
        <div class="row-between">
          <h3 style="margin-bottom: 0;">${escapeHtml(t("admin.reports_heading"))}</h3>
          <button class="btn btn-icon" id="new-report-btn" aria-label="${escapeAttr(t("admin.generate_report_label"))}">${icons.plus}</button>
        </div>
        <div id="auto-report-root" style="margin-bottom: var(--space-3);"></div>
        <div id="reports-root"></div>
      </div>

      <div class="settings-section">
        <h3>${escapeHtml(t("admin.overdue_heading"))}</h3>
        <p class="muted" style="font-size: var(--font-size-xs); margin-top: -4px;">
          ${escapeHtml(t("admin.overdue_desc"))}
        </p>
        <div id="overdue-cleanup-root"></div>
      </div>

      <div class="settings-section">
        <h3>${escapeHtml(t("admin.authentik_heading"))}</h3>
        <p class="muted" style="font-size: var(--font-size-xs); margin-top: -4px;">
          ${escapeHtml(t("admin.authentik_desc"))}
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
        t("admin.notified_summary", {
          notified: result.notified,
          skippedGoal: result.skipped_already_met_goal,
          skippedSub: result.skipped_no_subscription,
        }),
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
      showToast(t("admin.balancing_complete_toast"), "success");
    } catch {
      /* api.js already showed a toast */
    } finally {
      btn.disabled = false;
    }
  });

  await loadWeekStart(container);
  await loadTimezone(container);
  await loadDefaultLanguage(container);
  await loadGoal(container);
  await loadMoneyRate(container);
  await loadSchedule(container);
  await loadOverdueCleanup(container);
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
    const weekdayNames = WEEKDAY_NAMES();
    root.innerHTML = `
      <div class="row">
        <select class="select grow" id="week-start-select">
          ${weekdayNames.map((name, i) => `<option value="${i}" ${settings.week_start_weekday === i ? "selected" : ""}>${escapeHtml(name)}</option>`).join("")}
        </select>
        <button class="btn btn-primary" id="week-start-save">${escapeHtml(t("common.save"))}</button>
      </div>
    `;
    root.querySelector("#week-start-save").addEventListener("click", async () => {
      try {
        await patchSettings({ week_start_weekday: Number(root.querySelector("#week-start-select").value) });
        showToast(t("admin.week_start_save_toast"), "success");
      } catch {
        /* api.js already showed a toast */
      }
    });
  } catch {
    cancelSkeleton();
    root.innerHTML = `<div class="empty-state">${escapeHtml(t("common.couldnt_load_settings"))}</div>`;
  }
}

// Intl.supportedValuesOf isn't in every browser yet — falls back to a
// plain text input (server-side validated against the real IANA
// database either way, via ZoneInfo) rather than hand-maintaining a
// parallel list of timezone names here.
function listTimezones() {
  if (typeof Intl.supportedValuesOf !== "function") return null;
  try {
    const zones = Intl.supportedValuesOf("timeZone");
    // Chrome's own list doesn't include the plain "UTC" alias — without
    // this, selecting a fresh household's actual default value has
    // nothing to show, and re-saving the form would silently pick
    // whatever the list's first real entry happens to be instead.
    return zones.includes("UTC") ? zones : ["UTC", ...zones];
  } catch {
    return null;
  }
}

async function loadTimezone(container) {
  const root = container.querySelector("#timezone-root");
  if (!root) return;
  const cancelSkeleton = showSkeletonAfterDelay(root, `<div class="skeleton" style="height: 56px;"></div>`);
  try {
    const settings = await api.get(`${HB}/settings`);
    cancelSkeleton();
    const zones = listTimezones();
    root.innerHTML = `
      <div class="row">
        ${
          zones
            ? `<select class="select grow" id="timezone-select">
                 ${zones.map((z) => `<option value="${escapeAttr(z)}" ${settings.timezone === z ? "selected" : ""}>${escapeHtml(z)}</option>`).join("")}
               </select>`
            : `<input class="input grow" id="timezone-select" value="${escapeAttr(settings.timezone)}" placeholder="${escapeAttr(t("admin.timezone_placeholder"))}" />`
        }
        <button class="btn btn-primary" id="timezone-save">${escapeHtml(t("common.save"))}</button>
      </div>
    `;
    root.querySelector("#timezone-save").addEventListener("click", async () => {
      try {
        await patchSettings({ timezone: root.querySelector("#timezone-select").value.trim() });
        showToast(t("common.saved_toast"), "success");
      } catch {
        /* api.js already showed a toast (e.g. an unrecognized name typed into the fallback input) */
      }
    });
  } catch {
    cancelSkeleton();
    root.innerHTML = `<div class="empty-state">${escapeHtml(t("common.couldnt_load_settings"))}</div>`;
  }
}

// What a BRAND NEW HouseholdUser starts with (crud.get_or_create_
// household_user copies this onto the new row at creation time) — not
// retroactive, same as every other per-user default this page doesn't
// otherwise touch. See HouseholdSettings.default_language's own model
// docstring.
async function loadDefaultLanguage(container) {
  const root = container.querySelector("#default-language-root");
  if (!root) return;
  const cancelSkeleton = showSkeletonAfterDelay(root, `<div class="skeleton" style="height: 56px;"></div>`);
  try {
    const settings = await api.get(`${HB}/settings`);
    cancelSkeleton();
    root.innerHTML = `
      <div class="row">
        <select class="select grow" id="default-language-select">
          ${Object.entries(LANGUAGE_NATIVE_NAMES)
            .map(([id, name]) => `<option value="${id}" ${settings.default_language === id ? "selected" : ""}>${escapeHtml(name)}</option>`)
            .join("")}
        </select>
        <button class="btn btn-primary" id="default-language-save">${escapeHtml(t("common.save"))}</button>
      </div>
    `;
    root.querySelector("#default-language-save").addEventListener("click", async () => {
      try {
        await patchSettings({ default_language: root.querySelector("#default-language-select").value });
        showToast(t("common.saved_toast"), "success");
      } catch {
        /* api.js already showed a toast */
      }
    });
  } catch {
    cancelSkeleton();
    root.innerHTML = `<div class="empty-state">${escapeHtml(t("common.couldnt_load_settings"))}</div>`;
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
        <label for="goal-input">${escapeHtml(t("admin.goal_label"))}</label>
        <div class="row">
          <input class="input" type="number" min="0" id="goal-input" value="${settings.weekly_points_goal ?? ""}" placeholder="${escapeAttr(t("admin.goal_placeholder"))}" />
          <button class="btn btn-primary" id="goal-save">${escapeHtml(t("common.save"))}</button>
        </div>
      </div>
    `;
    root.querySelector("#goal-save").addEventListener("click", async () => {
      const raw = root.querySelector("#goal-input").value;
      try {
        await patchSettings({ weekly_points_goal: raw === "" ? null : Number(raw) });
        showToast(t("common.saved_toast"), "success");
      } catch {
        /* api.js already showed a toast */
      }
    });
  } catch {
    cancelSkeleton();
    root.innerHTML = `<div class="empty-state">${escapeHtml(t("common.couldnt_load_settings"))}</div>`;
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
          <label for="currency-select">${escapeHtml(t("admin.currency_label"))}</label>
          <select class="select" id="currency-select">
            ${CURRENCIES.map((c) => `<option value="${c}" ${settings.currency === c ? "selected" : ""}>${c}</option>`).join("")}
          </select>
        </div>
        <div class="field">
          <label for="rate-input">${escapeHtml(t("admin.per_point_label"))}</label>
          <input class="input" type="number" min="0" step="0.01" id="rate-input" value="${settings.points_to_money_rate ?? ""}" placeholder="${escapeAttr(t("admin.no_rate_set"))}" />
        </div>
      </div>
      <button class="btn btn-primary btn-block" id="money-save" style="margin-top: var(--space-2);">${escapeHtml(t("common.save"))}</button>
    `;
    root.querySelector("#money-save").addEventListener("click", async () => {
      const raw = root.querySelector("#rate-input").value;
      try {
        await patchSettings({
          points_to_money_rate: raw === "" ? null : Number(raw),
          currency: root.querySelector("#currency-select").value,
        });
        showToast(t("common.saved_toast"), "success");
      } catch {
        /* api.js already showed a toast */
      }
    });
  } catch {
    cancelSkeleton();
    root.innerHTML = `<div class="empty-state">${escapeHtml(t("common.couldnt_load_settings"))}</div>`;
  }
}

// PUT /settings replaces the whole row, so merge with the current value of
// every field this page isn't editing right now. default_language had to
// join this list the same way overdue_delete_after_days/timezone did
// before it — forgetting a field here means every OTHER unrelated Save
// (goal, nudge, overdue, ...) silently resets it to the schema's own
// default the next time anyone saves anything on this page.
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
    overdue_delete_after_days: current.overdue_delete_after_days,
    timezone: current.timezone,
    default_language: current.default_language,
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
    const weekdayNames = WEEKDAY_NAMES();
    const lastSent = settings.last_nudge_sent_week
      ? t("admin.last_sent_auto", { date: settings.last_nudge_sent_week })
      : t("admin.hasnt_run_yet");

    root.innerHTML = `
      <div class="field">
        <label class="row"><input type="checkbox" id="schedule-enabled" ${settings.nudge_weekday !== null ? "checked" : ""} /> <span>${escapeHtml(t("admin.also_send_automatically"))}</span></label>
      </div>
      <div class="field-row" id="schedule-fields" style="margin-top: var(--space-2); ${settings.nudge_weekday !== null ? "" : "display:none;"}">
        <div class="field">
          <label for="schedule-weekday">${escapeHtml(t("admin.on_label"))}</label>
          <select class="select" id="schedule-weekday">
            ${weekdayNames.map((name, i) => `<option value="${i}" ${settings.nudge_weekday === i ? "selected" : ""}>${escapeHtml(name)}</option>`).join("")}
          </select>
        </div>
        <div class="field">
          <label for="schedule-hour">${escapeHtml(t("common.at_tz_label", { tz: settings.timezone }))}</label>
          <select class="select" id="schedule-hour">
            ${Array.from({ length: 24 }, (_, h) => `<option value="${h}" ${settings.nudge_hour === h ? "selected" : ""}>${String(h).padStart(2, "0")}:00</option>`).join("")}
          </select>
        </div>
      </div>
      <div class="row" style="margin-top: var(--space-2);">
        <span class="muted" style="font-size: var(--font-size-xs); flex: 1;">${escapeHtml(lastSent)}</span>
        <button class="btn btn-primary" id="schedule-save">${escapeHtml(t("common.save"))}</button>
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
        showToast(t("common.saved_toast"), "success");
      } catch {
        /* api.js already showed a toast */
      }
    });
  } catch {
    cancelSkeleton();
    root.innerHTML = `<div class="empty-state">${escapeHtml(t("common.couldnt_load_schedule"))}</div>`;
  }
}

async function loadOverdueCleanup(container) {
  const root = container.querySelector("#overdue-cleanup-root");
  if (!root) return;
  const cancelSkeleton = showSkeletonAfterDelay(root, `<div class="skeleton" style="height: 56px;"></div>`);
  try {
    const settings = await api.get(`${HB}/settings`);
    cancelSkeleton();
    const enabled = settings.overdue_delete_after_days !== null;

    root.innerHTML = `
      <div class="field">
        <label class="row"><input type="checkbox" id="overdue-enabled" ${enabled ? "checked" : ""} /> <span>${escapeHtml(t("admin.automatically_delete_overdue"))}</span></label>
      </div>
      <div class="field" id="overdue-fields" style="margin-top: var(--space-2); ${enabled ? "" : "display:none;"}">
        <label for="overdue-days">${escapeHtml(t("admin.after_days_label"))}</label>
        <input class="input" type="number" min="1" id="overdue-days" value="${enabled ? settings.overdue_delete_after_days : 7}" />
      </div>
      <div class="row" style="margin-top: var(--space-2);">
        <span class="muted" style="font-size: var(--font-size-xs); flex: 1;"></span>
        <button class="btn btn-primary" id="overdue-save">${escapeHtml(t("common.save"))}</button>
      </div>
    `;

    const enabledCheckbox = root.querySelector("#overdue-enabled");
    const fields = root.querySelector("#overdue-fields");
    enabledCheckbox.addEventListener("change", () => {
      fields.style.display = enabledCheckbox.checked ? "" : "none";
    });

    root.querySelector("#overdue-save").addEventListener("click", async () => {
      const on = enabledCheckbox.checked;
      const days = Number(root.querySelector("#overdue-days").value || 0);
      if (on && days < 1) {
        showToast(t("admin.enter_at_least_1_day"), "warning");
        return;
      }
      try {
        await patchSettings({
          overdue_delete_after_days: on ? days : null,
        });
        showToast(t("common.saved_toast"), "success");
      } catch {
        /* api.js already showed a toast */
      }
    });
  } catch {
    cancelSkeleton();
    root.innerHTML = `<div class="empty-state">${escapeHtml(t("common.couldnt_load_settings"))}</div>`;
  }
}

function renderBalanceResult(container, result) {
  const root = container.querySelector("#balance-result-root");
  if (!root) return;

  if (result.by_user.length === 0 && result.reassignments.length === 0) {
    root.innerHTML = `<div class="empty-state">${escapeHtml(t("admin.nothing_to_assign"))}</div>`;
    return;
  }

  const rows = result.by_user
    .map((u) => {
      const bits = [
        t("common.task_count", { n: u.new_task_count, count: u.new_task_count }),
        t("common.todo_count", { n: u.new_todo_count, count: u.new_todo_count }),
      ];
      if (u.reassigned_in_count) bits.push(t("admin.moved_to_them", { n: u.reassigned_in_count }));
      if (u.reassigned_out_count) bits.push(t("admin.moved_away", { n: u.reassigned_out_count }));
      const netPoints = u.new_expected_points + u.reassigned_net_points;
      return `
      <div class="list-row" style="cursor:default;">
        <div class="list-row-body">
          <div class="list-row-title">${escapeHtml(u.household_user.display_name)}</div>
          <div class="list-row-meta"><span>${bits.join(" · ")}</span></div>
        </div>
        <div class="list-row-points"><span>${netPoints >= 0 ? "+" : ""}${netPoints}</span><span class="muted">${escapeHtml(t("common.pts"))}</span></div>
      </div>`;
    })
    .join("");

  const reassignmentRows = result.reassignments
    .map(
      (r) => `
      <div class="list-row" style="cursor:default;">
        <div class="list-row-body">
          <div class="list-row-title">${escapeHtml(r.task_name)}</div>
          <div class="list-row-meta"><span>${escapeHtml(t("admin.pulled_away_note", { from: r.from_user.display_name, to: r.to_user.display_name }))}</span></div>
        </div>
        <div class="list-row-points"><span>${r.points}</span><span class="muted">${escapeHtml(t("common.pts"))}</span></div>
      </div>`
    )
    .join("");

  const leftover =
    result.unassigned_task_count || result.unassigned_todo_count
      ? `<p class="muted" style="font-size: var(--font-size-xs); margin-top: var(--space-2);">
           ${escapeHtml(t("admin.leftover_note", { taskCount: result.unassigned_task_count, todoCount: result.unassigned_todo_count }))}
         </p>`
      : "";

  root.innerHTML = `
    ${rows ? `<div class="stack">${rows}</div>` : ""}
    ${
      reassignmentRows
        ? `<p class="muted" style="font-size: var(--font-size-xs); margin: var(--space-3) 0 4px;">${escapeHtml(t("admin.mid_week_rebalancing"))}</p><div class="stack">${reassignmentRows}</div>`
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
      ? t("admin.last_auto_generated", { date: settings.last_auto_report_period })
      : t("admin.hasnt_run_yet");
    root.innerHTML = `
      <div class="field">
        <label class="row">
          <input type="checkbox" id="auto-report-enabled" ${settings.auto_report_enabled ? "checked" : ""} />
          <span>${escapeHtml(t("admin.auto_generate_label"))}</span>
        </label>
      </div>
      <div class="row" style="margin-top: var(--space-2);">
        <span class="muted" style="font-size: var(--font-size-xs); flex: 1;">${escapeHtml(lastAuto)}</span>
        <button class="btn btn-primary" id="auto-report-save">${escapeHtml(t("common.save"))}</button>
      </div>
    `;
    root.querySelector("#auto-report-save").addEventListener("click", async () => {
      try {
        await patchSettings({ auto_report_enabled: root.querySelector("#auto-report-enabled").checked });
        showToast(t("common.saved_toast"), "success");
      } catch {
        /* api.js already showed a toast */
      }
    });
  } catch {
    cancelSkeleton();
    root.innerHTML = `<div class="empty-state">${escapeHtml(t("common.couldnt_load_settings"))}</div>`;
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
      root.innerHTML = `<div class="empty-state">${escapeHtml(t("admin.no_reports_yet"))}</div>`;
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
              ${r.period_type === "week" ? escapeHtml(t("admin.report_title_week")) : escapeHtml(t("admin.report_title_month"))}
              ${r.is_last_week ? `<span class="badge badge-info">${escapeHtml(t("admin.last_week_badge"))}</span>` : ""}
              <span class="badge badge-${paid ? "success" : "neutral"}">${paid ? escapeHtml(t("admin.paid_badge")) : escapeHtml(t("admin.unpaid_badge"))}</span>
            </div>
            <div class="list-row-meta">
              <span>${r.period_start} – ${r.period_end}</span>
              ${r.generated_by ? "" : `<span class="muted">${escapeHtml(t("admin.auto_suffix"))}</span>`}
            </div>
          </div>
          <div class="list-row-actions">
            <button class="btn btn-icon" data-action="toggle-paid" aria-label="${paid ? escapeAttr(t("admin.mark_unpaid")) : escapeAttr(t("admin.mark_paid"))}" title="${paid ? escapeAttr(t("admin.mark_unpaid")) : escapeAttr(t("admin.mark_paid"))}">${icons.check}</button>
            <button class="btn btn-icon" data-action="download" aria-label="${escapeAttr(t("admin.download_report_aria"))}">${icons.chevronRight}</button>
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
    root.innerHTML = `<div class="empty-state">${escapeHtml(t("common.couldnt_load_reports"))}</div>`;
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
        <h2>${escapeHtml(t("admin.generate_report_title"))}</h2>
        <button class="btn btn-icon btn-ghost" id="modal-close" aria-label="${escapeAttr(t("common.close"))}">${icons.close}</button>
      </div>
      <div class="stack">
        <div class="field">
          <label for="r-period-type">${escapeHtml(t("admin.period_label"))}</label>
          <select class="select" id="r-period-type">
            <option value="week">${escapeHtml(t("admin.period_week_option"))}</option>
            <option value="month">${escapeHtml(t("admin.period_month_option"))}</option>
          </select>
        </div>
        <div class="field">
          <label for="r-period-date">${escapeHtml(t("admin.any_date_label"))}</label>
          <input class="input" type="date" id="r-period-date" value="${new Date().toISOString().slice(0, 10)}" />
        </div>
      </div>
      <div class="modal-footer">
        <button class="btn btn-primary grow" id="r-generate">${escapeHtml(t("admin.generate_btn"))}</button>
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
      showToast(t("admin.report_generated_toast"), "success");
      close();
      loadReports(container);
    } catch {
      /* api.js already showed a toast */
    }
  });
}

const AUTHENTIK_FIELDS = [
  ["issuer", () => t("admin.issuer_label")],
  ["jwks_url", () => t("admin.jwks_label")],
  ["client_id", () => t("admin.client_id_label")],
  ["authorize_url", () => t("admin.authorize_url_label")],
  ["token_url", () => t("admin.token_url_label")],
  ["end_session_url", () => t("admin.end_session_url_label")],
  ["scope", () => t("admin.scope_label")],
];

// Separate from AUTHENTIK_FIELDS only so the render can put a divider/
// heading between the two groups — saved together, same request, same
// reauth.
const GROUP_ROLE_FIELDS = [
  ["admin_group", () => t("admin.admin_group_label")],
  ["user_group", () => t("admin.user_group_label")],
  ["viewer_group", () => t("admin.viewer_group_label")],
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
    root.innerHTML = `<div class="empty-state">${escapeHtml(t("admin.couldnt_load_authentik"))}</div>`;
    return;
  }
  cancelSkeleton();

  root.innerHTML = `
    ${AUTHENTIK_FIELDS.map(
      ([key, label]) => `
      <div class="field">
        <label for="ak-${key}">${escapeHtml(label())}</label>
        <input class="input" id="ak-${key}" value="${escapeAttr(config[key])}" />
      </div>`
    ).join("")}
    <p class="muted" style="font-size: var(--font-size-xs); margin: var(--space-3) 0 4px;">
      ${escapeHtml(t("admin.group_role_note"))}
    </p>
    ${GROUP_ROLE_FIELDS.map(
      ([key, label]) => `
      <div class="field">
        <label for="ak-${key}">${escapeHtml(label())}</label>
        <input class="input" id="ak-${key}" value="${escapeAttr(config[key])}" />
      </div>`
    ).join("")}
    <div
      class="field"
      style="margin-top: var(--space-3); padding-top: var(--space-3); border-top: 1px solid var(--border-color);"
    >
      <label for="ak-reauth-username">${escapeHtml(t("admin.reauth_username_label"))}</label>
      <input class="input" id="ak-reauth-username" autocomplete="username" />
    </div>
    <div class="field">
      <label for="ak-reauth-password">${escapeHtml(t("admin.reauth_password_label"))}</label>
      <input class="input" type="password" id="ak-reauth-password" autocomplete="current-password" />
    </div>
    <div class="row" style="margin-top: var(--space-2);">
      <button class="btn" id="ak-reset">${escapeHtml(t("admin.reset_defaults_btn"))}</button>
      <button class="btn btn-primary grow" id="ak-save">${escapeHtml(t("common.save"))}</button>
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
      ...Object.fromEntries(
        [...AUTHENTIK_FIELDS, ...GROUP_ROLE_FIELDS].map(([key]) => [key, root.querySelector(`#ak-${key}`).value.trim()])
      ),
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
      showToast(t("admin.authentik_save_toast"), "success");
      loadAuthentikConfig(container);
    } catch (err) {
      showToast(err.message || t("admin.couldnt_save"), "danger");
    } finally {
      btn.disabled = false;
    }
  });

  root.querySelector("#ak-reset").addEventListener("click", async () => {
    const ok = await showConfirmDialog({
      title: t("admin.reset_confirm_title"),
      message: t("admin.reset_confirm_message"),
      confirmLabel: t("admin.reset_btn"),
      danger: true,
    });
    if (!ok) return;
    const btn = root.querySelector("#ak-reset");
    btn.disabled = true;
    try {
      await api.post(`${AUTH_BASE}/authentik-config/reset`, reauthBody(), { silent: true });
      showToast(t("admin.reset_toast"), "success");
      loadAuthentikConfig(container);
    } catch (err) {
      showToast(err.message || t("admin.couldnt_reset"), "danger");
    } finally {
      btn.disabled = false;
    }
  });
}
