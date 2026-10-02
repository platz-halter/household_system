// Small helpers shared across the page modules — kept here (rather than
// duplicated per file, unlike storage/frontend's escapeHtml) because the
// weekday/date math needs to agree exactly everywhere it's used.

export function escapeHtml(str) {
  return String(str ?? "").replace(
    /[&<>"']/g,
    (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]
  );
}

export const escapeAttr = escapeHtml;

// Mirrors Task.weekdays on the backend: 0=Monday .. 6=Sunday.
export const WEEKDAY_LABELS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

export function todayWeekday() {
  return (new Date().getDay() + 6) % 7;
}

export function startOfWeekIso() {
  const now = new Date();
  const diff = (now.getDay() + 6) % 7; // days since Monday
  const monday = new Date(now.getFullYear(), now.getMonth(), now.getDate() - diff);
  return monday.toISOString();
}

export function startOfMonthIso() {
  const now = new Date();
  return new Date(now.getFullYear(), now.getMonth(), 1).toISOString();
}

/** {since, until} bounding the previous Monday-Sunday week — a closed,
 * final range (unlike "this week", which is still in progress). */
export function lastWeekRangeIso() {
  const thisMonday = new Date(startOfWeekIso());
  const lastMonday = new Date(thisMonday);
  lastMonday.setDate(lastMonday.getDate() - 7);
  return { since: lastMonday.toISOString(), until: thisMonday.toISOString() };
}

export function initials(name) {
  return (name || "?").trim().slice(0, 1).toUpperCase();
}

/** {label, tone} badge describing a due date relative to today, or null
 * if there's no due date. */
export function dueBadge(dueDateStr) {
  if (!dueDateStr) return null;
  const due = new Date(`${dueDateStr}T00:00:00`);
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const diffDays = Math.round((due - today) / 86400000);
  if (diffDays < 0) return { label: "Overdue", tone: "danger" };
  if (diffDays === 0) return { label: "Due today", tone: "warning" };
  if (diffDays === 1) return { label: "Due tomorrow", tone: "info" };
  return { label: `Due ${dueDateStr}`, tone: "neutral" };
}

export function timeAgo(isoString) {
  const diffMs = Date.now() - new Date(isoString).getTime();
  const mins = Math.round(diffMs / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.round(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.round(hours / 24);
  if (days < 7) return `${days}d ago`;
  return new Date(isoString).toLocaleDateString();
}
