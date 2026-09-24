const STORAGE_KEY = "hs-theme";

// Add a new theme by (1) adding a [data-theme="id"] block to
// css/tokens.css with the same variable set as the dark theme there,
// and (2) adding one entry here. That's the whole process.
export const THEMES = [
  { id: "light", label: "Light" },
  { id: "dark", label: "Dark" },
];

export function getStoredTheme() {
  return localStorage.getItem(STORAGE_KEY) || "light";
}

export function applyTheme(id) {
  document.documentElement.setAttribute("data-theme", id);
  localStorage.setItem(STORAGE_KEY, id);
}
