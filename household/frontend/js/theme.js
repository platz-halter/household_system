import { t } from "./i18n.js";

const STORAGE_KEY = "hs-theme";

// Add a new theme by (1) adding a [data-theme="id"] block to
// css/tokens.css with the same variable set as the dark theme there,
// and (2) adding one entry here, plus its label key in both locale
// files. That's the whole process.
export function THEMES() {
  return [
    { id: "light", label: t("theme.light") },
    { id: "dark", label: t("theme.dark") },
  ];
}

export function getStoredTheme() {
  return localStorage.getItem(STORAGE_KEY) || "light";
}

export function applyTheme(id) {
  document.documentElement.setAttribute("data-theme", id);
  localStorage.setItem(STORAGE_KEY, id);
  syncThemeColorMeta();
}

// <meta name="theme-color"> is what Android actually paints the status
// bar/notch area with, independently of anything in this page's own
// layout — index.html's own topbar-safe-area fix only controls the WEB
// content underneath it. Left at its static index.html value (plain
// white) regardless of theme, it stayed a bright white strip even in
// dark mode, clashing with the app's own background right above it
// (reported as a "white gap" that didn't go away after the layout fix).
// Reads the CSS variable rather than hardcoding light/dark hex values
// here too, so this can't drift from tokens.css's own colors.
function syncThemeColorMeta() {
  const meta = document.querySelector('meta[name="theme-color"]');
  if (!meta) return;
  const bg = getComputedStyle(document.documentElement).getPropertyValue("--color-bg").trim();
  if (bg) meta.setAttribute("content", bg);
}
