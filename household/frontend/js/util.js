// Small helpers shared across the page modules — kept here (rather than
// duplicated per file, unlike storage/frontend's escapeHtml) because the
// weekday/date math needs to agree exactly everywhere it's used.
import { t, getLocale } from "./i18n.js";

export function escapeHtml(str) {
  return String(str ?? "").replace(
    /[&<>"']/g,
    (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]
  );
}

export const escapeAttr = escapeHtml;

// Mirrors Task.weekdays on the backend: 0=Monday .. 6=Sunday. Built from
// t() rather than stored as a literal array, so it tracks the current
// language — anything that read these at module-load time under the old
// plain-array design would need this file re-evaluated on a language
// change anyway, which a full reload (see i18n.js's setLocale callers)
// already guarantees.
export function WEEKDAY_LABELS() {
  return ["weekday.mon", "weekday.tue", "weekday.wed", "weekday.thu", "weekday.fri", "weekday.sat", "weekday.sun"].map(
    (k) => t(k)
  );
}

export function WEEKDAY_NAMES() {
  return [
    "weekday.monday",
    "weekday.tuesday",
    "weekday.wednesday",
    "weekday.thursday",
    "weekday.friday",
    "weekday.saturday",
    "weekday.sunday",
  ].map((k) => t(k));
}

// Loading skeletons are meant for genuinely slow requests — showing one
// for a request that resolves in 50ms just makes it flash in and back
// out, which reads as a glitch rather than a loading state. Delaying
// when it's allowed to appear fixes that without adding any real delay
// to a fast response: call this right before the request starts, then
// call the returned function as soon as it settles (success or
// failure) — if that happens before DELAY_MS, the skeleton never
// renders at all; if the request is genuinely slow, it still shows up,
// just not for the first instant.
const SKELETON_DELAY_MS = 200;

export function showSkeletonAfterDelay(root, html, delayMs = SKELETON_DELAY_MS) {
  const timer = setTimeout(() => {
    root.innerHTML = html;
  }, delayMs);
  return () => clearTimeout(timer);
}

export function initials(name) {
  return (name || "?").trim().slice(0, 1).toUpperCase();
}

/** {label, tone} badge describing a due date relative to today, or null
 * if there's no due date.
 *
 * Both sides are anchored to UTC, not the viewer's local timezone. The
 * backend writes `due_date` from `datetime.now(UTC).date()` (see
 * crud._todo_due_date) — comparing against a LOCAL "today" meant that
 * for any viewer not in UTC, there's a stretch of every day where the
 * browser's calendar date has already rolled over past midnight but
 * UTC's hasn't (or vice versa), making a todo due "today" compute one
 * day off and show as "Overdue" the moment it was created. Comparing in
 * UTC on both sides keeps this agreeing with whatever day the backend
 * actually meant, regardless of the viewer's own clock.
 */
export function dueBadge(dueDateStr) {
  if (!dueDateStr) return null;
  const due = new Date(`${dueDateStr}T00:00:00Z`);
  const now = new Date();
  const today = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate()));
  const diffDays = Math.round((due - today) / 86400000);
  if (diffDays < 0) return { label: t("util.overdue"), tone: "danger" };
  if (diffDays === 0) return { label: t("util.due_today"), tone: "warning" };
  if (diffDays === 1) return { label: t("util.due_tomorrow"), tone: "info" };
  return { label: t("util.due_on", { date: dueDateStr }), tone: "neutral" };
}

// .fab/.fab-secondary are `position: fixed`, so on a narrow phone
// (below the page's max content width, where there's no side margin to
// absorb them) they sit over the same screen position regardless of
// scroll — which can land right on top of a list row's own right-aligned
// buttons while scrolling past it, making them briefly untappable.
// Reserving permanent layout space for this was tried first and
// backfired (see css/components.css's own note by .fab-scroll-hidden):
// the one flexible child in that row shrinks to make room, so a plain
// "Test" truncated to "T…" on every row, not just whichever one
// happened to be behind a FAB at a given moment. Hiding the FABs
// instead, only while the page is actively being scrolled, avoids that
// — nothing about row layout ever changes, and there's simply nothing
// floating there to overlap until scrolling settles. Installed once,
// globally, at app boot (main.js) rather than per-page: it re-queries
// whichever FABs are currently in the DOM on every scroll event, so it
// doesn't need to know (or care) which page is currently showing them,
// and doesn't need re-installing on every SPA navigation.
let scrollHideLastY = 0;
let scrollHideIdleTimer = null;

export function installScrollHideFab() {
  window.addEventListener(
    "scroll",
    () => {
      const fabs = document.querySelectorAll(".fab, .fab-secondary");
      if (fabs.length === 0) return;
      const y = window.scrollY;
      const scrollingDown = y > scrollHideLastY;
      scrollHideLastY = y;
      // A small threshold so a tiny scroll (overscroll bounce, a wheel
      // tick) doesn't flicker the FAB away and back for no reason.
      const hide = scrollingDown && y > 24;
      fabs.forEach((el) => el.classList.toggle("fab-scroll-hidden", hide));
      clearTimeout(scrollHideIdleTimer);
      // Always comes back once scrolling actually stops, regardless of
      // direction or where it stopped — it just shouldn't be visible
      // WHILE the list is in motion past it.
      scrollHideIdleTimer = setTimeout(() => {
        fabs.forEach((el) => el.classList.remove("fab-scroll-hidden"));
      }, 500);
    },
    { passive: true }
  );
}

export function timeAgo(isoString) {
  const diffMs = Date.now() - new Date(isoString).getTime();
  const mins = Math.round(diffMs / 60000);
  if (mins < 1) return t("util.just_now");
  if (mins < 60) return t("util.minutes_ago", { m: mins });
  const hours = Math.round(mins / 60);
  if (hours < 24) return t("util.hours_ago", { h: hours });
  const days = Math.round(hours / 24);
  if (days < 7) return t("util.days_ago", { d: days });
  return new Date(isoString).toLocaleDateString(getLocale());
}
