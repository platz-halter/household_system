// Frontend translation core — English and German, same design as
// household/frontend/js/i18n.js, but intentionally simpler: storage has
// no per-service user table at all (see CLAUDE.md's "Storage has no
// admin/user distinction at all"), so there's nowhere server-side to
// persist a language preference, and nothing to reconcile a cached
// value against. The language choice lives ENTIRELY client-side, in
// localStorage — same storage model this app already uses for the
// theme (see theme.js) — which is also exactly what "local language
// selection" means here: a per-browser/per-device choice, not an
// account-wide one.
//
// Boot order this relies on: en.js/de.js are static ES-module imports,
// not fetched — so by the time ANY other module's own top-level code
// runs, this module's own top-level code already has a locale resolved
// and `document.documentElement`'s `lang` attribute set.
import { en } from "./locales/en.js";
import { de } from "./locales/de.js";

const LOCALES = { en, de };
const STORAGE_KEY = "hs-lang";

function detectInitialLocale() {
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored && LOCALES[stored]) return stored;
  } catch {
    // Private browsing / blocked storage — fall through to navigator.language.
  }
  const nav = (navigator.language || "en").slice(0, 2).toLowerCase();
  return LOCALES[nav] ? nav : "en";
}

let currentLocale = detectInitialLocale();
document.documentElement.setAttribute("lang", currentLocale);

export function getLocale() {
  return currentLocale;
}

export function supportedLocales() {
  return Object.keys(LOCALES);
}

// Persists the choice and updates <html lang> immediately. Returns false
// if localStorage couldn't be written (private browsing, blocked
// storage) — the Settings page checks this before reloading, same
// reasoning as household's own setLocale: a write failure must not
// cause a reload loop that keeps re-detecting the old value.
export function setLocale(locale) {
  if (!LOCALES[locale]) return false;
  currentLocale = locale;
  document.documentElement.setAttribute("lang", locale);
  try {
    localStorage.setItem(STORAGE_KEY, locale);
    return true;
  } catch {
    return false;
  }
}

function pluralForm(count) {
  try {
    return new Intl.PluralRules(currentLocale).select(count);
  } catch {
    return count === 1 ? "one" : "other";
  }
}

function lookup(locale, key) {
  return LOCALES[locale] && LOCALES[locale][key];
}

/**
 * Translates `key`, substituting `{param}` placeholders from `params`.
 * Falls back de -> en -> the raw key itself (never silently blank — a
 * miss shows up on screen as the key, so it can't go unnoticed).
 *
 * A value may be a plain string, or a {one, other, ...} plural-form
 * object (per Intl.PluralRules categories) selected via `params.count`.
 */
export function t(key, params = {}) {
  let entry = lookup(currentLocale, key);
  if (entry === undefined) entry = lookup("en", key);
  if (entry === undefined) return key;

  let template = entry;
  if (typeof entry === "object") {
    const form = pluralForm(params.count);
    template = entry[form] ?? entry.other ?? Object.values(entry)[0];
  }
  return template.replace(/\{(\w+)\}/g, (match, name) =>
    params[name] !== undefined ? String(params[name]) : match
  );
}

// Applies every [data-i18n] (textContent) and [data-i18n-attr] (one or
// more "attr:key" pairs, semicolon-separated) node under `root`. Static
// chrome (index.html's topbar/bottom-nav) only needs this once at boot
// — there's no in-place re-render system for a language change, so an
// explicit change (the Settings switcher) just reloads instead.
export function applyStaticTranslations(root = document) {
  root.querySelectorAll("[data-i18n]").forEach((el) => {
    el.textContent = t(el.getAttribute("data-i18n"));
  });
  root.querySelectorAll("[data-i18n-attr]").forEach((el) => {
    el.getAttribute("data-i18n-attr")
      .split(";")
      .forEach((pair) => {
        const [attr, key] = pair.split(":").map((s) => s.trim());
        if (attr && key) el.setAttribute(attr, t(key));
      });
  });
}
