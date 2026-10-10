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
}
