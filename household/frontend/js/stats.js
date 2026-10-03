import { CONFIG } from "./config.js";
import { api, fetchImageUrl } from "./api.js";
import { escapeHtml, initials, timeAgo, showSkeletonAfterDelay, WEEKDAY_LABELS } from "./util.js";

const HB = CONFIG.HOUSEHOLD_BASE;

const state = { period: "week", scope: "me" };
let meCache = null;
let settingsCache = null;

async function getSettings() {
  if (!settingsCache) {
    try {
      settingsCache = await api.get(`${HB}/settings`);
    } catch {
      settingsCache = {};
    }
  }
  return settingsCache;
}

function formatMoney(points, rate, currency) {
  return (points * rate).toLocaleString(undefined, { style: "currency", currency });
}

export async function renderStats(container) {
  container.innerHTML = `
    <div class="page">
      <div class="section-heading">
        <h2>Leaderboard</h2>
        <div class="segmented" id="period-segmented">
          <button data-period="all">All time</button>
          <button data-period="week" class="active">This week</button>
          <button data-period="lastweek">Last week</button>
          <button data-period="month">Month</button>
        </div>
      </div>
      <div id="leaderboard-list"></div>

      <div class="section-heading">
        <h2>Activity</h2>
        <div class="segmented" id="scope-segmented">
          <button data-scope="household">Household</button>
          <button data-scope="me" class="active">Just me</button>
        </div>
      </div>
      <div class="heatmap-wrap">
        <div class="heatmap-daylabels-col">
          <div class="heatmap-months-spacer"></div>
          <div class="heatmap-daylabels" id="heatmap-daylabels"></div>
        </div>
        <div class="heatmap-scroll" id="heatmap-scroll">
          <div class="heatmap-months" id="heatmap-months"></div>
          <div class="heatmap-grid" id="heatmap-grid"></div>
        </div>
      </div>
      <div class="heatmap-legend">
        <span>Less</span>
        <span class="heatmap-cell"></span>
        <span class="heatmap-cell heat-1"></span>
        <span class="heatmap-cell heat-2"></span>
        <span class="heatmap-cell heat-3"></span>
        <span class="heatmap-cell heat-4"></span>
        <span>More</span>
      </div>

      <div class="section-heading"><h2>Recent activity</h2></div>
      <div id="recent-list" class="stack"></div>
    </div>
  `;

  wireSegmented(container, "#period-segmented", "data-period", (val) => {
    state.period = val;
    loadLeaderboard(container);
  });
  wireSegmented(container, "#scope-segmented", "data-scope", (val) => {
    state.scope = val;
    loadHeatmap(container);
  });

  await Promise.all([loadLeaderboard(container), loadHeatmap(container), loadRecent(container)]);
}

function wireSegmented(container, rootSel, attr, onChange) {
  const root = container.querySelector(rootSel);
  root.querySelectorAll("button").forEach((btn) => {
    btn.addEventListener("click", () => {
      root.querySelectorAll("button").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      onChange(btn.getAttribute(attr));
    });
  });
}

// Maps this page's own period ids to the backend's `period` values —
// resolved server-side (against the admin's configured week start, in
// UTC) rather than computed here, so this page never has to know that
// setting or juggle the local-vs-UTC day-boundary gap plain client-side
// date math had (see crud.resolve_leaderboard_bounds).
const PERIOD_PARAM = { all: "all", week: "this_week", lastweek: "last_week", month: "this_month" };

async function loadLeaderboard(container) {
  const root = container.querySelector("#leaderboard-list");
  if (!root) return;
  const cancelSkeleton = showSkeletonAfterDelay(root, `<div class="skeleton" style="height: 48px;"></div>`);
  try {
    const rows = await api.get(`${HB}/points/leaderboard?period=${PERIOD_PARAM[state.period]}`);
    cancelSkeleton();
    if (rows.length === 0) {
      root.innerHTML = `<div class="empty-state">No one on the leaderboard yet</div>`;
      return;
    }
    const { points_to_money_rate, currency } = await getSettings();
    root.innerHTML = rows
      .map(
        (row, i) => `
        <div class="leaderboard-row">
          <span class="leaderboard-rank">${i + 1}</span>
          <div class="user-avatar"${row.user.image_path ? ` data-avatar-user-id="${row.user.id}"` : ""}>${escapeHtml(initials(row.user.display_name))}</div>
          <span class="leaderboard-name">${escapeHtml(row.user.display_name)}</span>
          <span class="leaderboard-points">${row.total_points} pts${points_to_money_rate ? ` <span class="muted" style="font-weight: 500;">(${formatMoney(row.total_points, points_to_money_rate, currency)})</span>` : ""}</span>
        </div>`
      )
      .join("");
    hydrateAvatars(root);
  } catch {
    cancelSkeleton();
    root.innerHTML = `<div class="empty-state">Couldn't load the leaderboard</div>`;
  }
}

// Photos load in after the initial render rather than blocking it — same
// "initials now, swap in the real photo when it arrives" pattern as the
// Settings page avatar, just applied to however many rows are on screen.
async function hydrateAvatars(root) {
  const els = root.querySelectorAll("[data-avatar-user-id]");
  await Promise.all(
    [...els].map(async (el) => {
      const objectUrl = await fetchImageUrl(`${HB}/users/${el.dataset.avatarUserId}/photo`);
      if (objectUrl) {
        el.innerHTML = `<img src="${objectUrl}" alt="" style="width:100%; height:100%; object-fit:cover; border-radius:inherit;" />`;
      }
    })
  );
}

async function loadRecent(container) {
  const root = container.querySelector("#recent-list");
  if (!root) return;
  const cancelSkeleton = showSkeletonAfterDelay(root, `<div class="skeleton" style="height: 40px;"></div>`);
  try {
    const entries = await api.get(`${HB}/points/recent?limit=20`);
    cancelSkeleton();
    if (entries.length === 0) {
      root.innerHTML = `<div class="empty-state">No activity yet</div>`;
      return;
    }
    root.innerHTML = entries
      .map((e) => {
        const label = e.task_name || e.todo_title || (e.source === "task" ? "a deleted task" : "a deleted todo");
        return `
          <div class="list-row" style="cursor: default;">
            <div class="avatar-sm"${e.household_user.image_path ? ` data-avatar-user-id="${e.household_user.id}"` : ""}>${escapeHtml(initials(e.household_user.display_name))}</div>
            <div class="list-row-body">
              <div class="list-row-title">${escapeHtml(e.household_user.display_name)} completed ${escapeHtml(label)}</div>
              <div class="list-row-meta"><span>${timeAgo(e.earned_at)}</span></div>
            </div>
            <div class="list-row-points"><span>+${e.points}</span><span class="muted">pts</span></div>
          </div>`;
      })
      .join("");
    hydrateAvatars(root);
  } catch {
    cancelSkeleton();
    root.innerHTML = `<div class="empty-state">Couldn't load recent activity</div>`;
  }
}

async function getMe() {
  if (!meCache) {
    try {
      meCache = await api.get(`${HB}/me`);
    } catch {
      meCache = null;
    }
  }
  return meCache;
}

/** Lays flat [{date, points}, ...] (ascending, contiguous) into weeks of 7,
 * starting on the household's configured week-start weekday (0=Mon..6=Sun,
 * same convention as the backend's `crud.week_bounds` — see
 * PROJECT_STATE.md), padding both ends with nulls so every week column has
 * exactly 7 slots. */
function buildWeeks(days, weekStart) {
  if (days.length === 0) return [];
  const first = new Date(`${days[0].date}T00:00:00`);
  const mondayFirst = (first.getDay() + 6) % 7; // JS getDay(): 0=Sun..6=Sat -> 0=Mon..6=Sun
  const firstWeekday = (mondayFirst - weekStart + 7) % 7;
  const padded = Array(firstWeekday).fill(null).concat(days);
  while (padded.length % 7 !== 0) padded.push(null);
  const weeks = [];
  for (let i = 0; i < padded.length; i += 7) weeks.push(padded.slice(i, i + 7));
  return weeks;
}

/** Same Mon..Sun labels as elsewhere in this app (`util.js`'s
 * WEEKDAY_LABELS, trimmed to 2 letters), rotated so the configured
 * week-start weekday comes first — keeps the label row above the grid
 * in sync with how buildWeeks() above actually lays out columns. */
function dayLabels(weekStart) {
  const monFirst = WEEKDAY_LABELS.map((l) => l.slice(0, 2));
  return monFirst.slice(weekStart).concat(monFirst.slice(0, weekStart));
}

/** Buckets a day's points into 5 shades (0-4) relative to the busiest day
 * in range — same idea as GitHub's contribution graph, just monochrome. */
function heatBucket(points, max) {
  if (!points || max <= 0) return 0;
  const ratio = points / max;
  if (ratio <= 0.25) return 1;
  if (ratio <= 0.5) return 2;
  if (ratio <= 0.75) return 3;
  return 4;
}

async function loadHeatmap(container) {
  const gridRoot = container.querySelector("#heatmap-grid");
  const monthsRoot = container.querySelector("#heatmap-months");
  const dayLabelsRoot = container.querySelector("#heatmap-daylabels");
  if (!gridRoot) return;
  gridRoot.innerHTML = "";
  monthsRoot.innerHTML = "";

  const { week_start_weekday } = await getSettings();
  const weekStart = week_start_weekday ?? 0;
  if (dayLabelsRoot) {
    dayLabelsRoot.innerHTML = dayLabels(weekStart)
      .map((label) => `<span>${label}</span>`)
      .join("");
  }

  let householdUserId = null;
  if (state.scope === "me") {
    const me = await getMe();
    if (!me) return;
    householdUserId = me.id;
  }

  let days;
  try {
    const qs = householdUserId ? `?household_user_id=${householdUserId}` : "";
    days = await api.get(`${HB}/points/activity${qs}`);
  } catch {
    gridRoot.innerHTML = `<div class="empty-state">Couldn't load activity</div>`;
    return;
  }

  const max = Math.max(1, ...days.map((d) => d.points));
  const weeks = buildWeeks(days, weekStart);

  let lastMonth = null;
  weeks.forEach((week) => {
    const monthLabel = document.createElement("div");
    const firstReal = week.find((d) => d);
    if (firstReal) {
      const month = new Date(`${firstReal.date}T00:00:00`).getMonth();
      if (month !== lastMonth) {
        monthLabel.textContent = new Date(`${firstReal.date}T00:00:00`).toLocaleDateString(undefined, {
          month: "short",
        });
        lastMonth = month;
      }
    }
    monthsRoot.appendChild(monthLabel);

    week.forEach((day) => {
      const cell = document.createElement("div");
      cell.className = "heatmap-cell";
      if (day) {
        const bucket = heatBucket(day.points, max);
        if (bucket > 0) cell.classList.add(`heat-${bucket}`);
        cell.title = `${day.date}: ${day.points} pt${day.points === 1 ? "" : "s"}`;
      } else {
        cell.style.visibility = "hidden";
      }
      gridRoot.appendChild(cell);
    });
  });

  // Open already scrolled to the current day, rather than the oldest one.
  const scrollRoot = container.querySelector("#heatmap-scroll");
  if (scrollRoot) scrollRoot.scrollLeft = scrollRoot.scrollWidth;
}
