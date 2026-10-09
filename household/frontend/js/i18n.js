// Frontend translation core — English and German, matching the backend's
// household_service/i18n.py (notifications/reports). Deliberately a
// separate design axis from that module: this one drives what the VIEWER
// sees in their own browser, seeded from and kept in sync with their own
// HouseholdUser.preferred_language, while the backend module renders
// server-generated text (notification bodies in the recipient's language,
// PDF reports in the household's shared default).
//
// Boot order this relies on: en.js/de.js are static ES-module imports, not
// fetched — so by the time ANY other module's own top-level code runs
// (including one that calls t() at import time, which none currently do,
// but the guarantee is what matters), this module's own top-level code
// already has a locale resolved and `document.documentElement`'s `lang`
// attribute set. ES modules guarantee a dependency's top-level code runs
// before the importer's — this file has no control-flow of its own to
// delay that.
import { en } from "./locales/en.js";
import { de } from "./locales/de.js";
import { CONFIG } from "./config.js";
import { api } from "./api.js";

const LOCALES = { en, de };
const STORAGE_KEY = "hs-lang";
// sessionStorage, not localStorage — this is a one-time "don't reload
// again for this exact value this tab session" guard (see
// reconcileLocale below), not a persisted preference.
const RECONCILE_GUARD_KEY = "hs-lang-reconciled";

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
// if localStorage couldn't be written (private browsing, blocked storage)
// — callers that reload based on a successful change must check this, so
// a write failure can't cause a reload loop that keeps re-detecting the
// old value.
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
 * miss shows up on screen as the key, same "fail loud" reasoning as the
 * backend's own t() raising KeyError for a typo).
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
// more "attr:key" pairs, semicolon-separated — e.g.
// "aria-label:nav.settings;title:nav.settings") node under `root`. Static
// chrome (index.html's topbar/bottom-nav) only needs this once at boot —
// there's no in-place re-render system for a language change (see
// setLocale's callers: they all reload instead).
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

// Reconciles the cached locale against the account's real
// HouseholdUser.preferred_language (the backend's own source of truth —
// see settings.js's language switcher and PATCH /me/language). The
// server value always wins: this is one account-wide preference, not a
// per-device one, so a mismatch only ever means this device's cache is
// stale (a fresh browser's navigator.language guess, or a language
// changed from a different device/session).
//
// Reloads at most once per session per mismatching value (sessionStorage
// guard) — if something were ever wrong server-side and kept returning a
// value this device can't settle on, that must not become a reload loop.
export async function reconcileLocale(serverLanguage) {
  if (!serverLanguage || !LOCALES[serverLanguage]) return;
  if (serverLanguage === currentLocale) return;

  let guard;
  try {
    guard = sessionStorage.getItem(RECONCILE_GUARD_KEY);
  } catch {
    guard = null;
  }
  if (guard === serverLanguage) return;

  const persisted = setLocale(serverLanguage);
  if (!persisted) return; // couldn't cache it — reloading would just re-detect the old value

  try {
    sessionStorage.setItem(RECONCILE_GUARD_KEY, serverLanguage);
  } catch {
    // Best-effort guard only — losing it just means a possible one-time
    // extra reload, not a loop (setLocale's own cache now agrees).
  }
  window.location.reload();
}

/**
 * Fetches the signed-in user's own preferred_language from the backend
 * and reconciles against it. Deliberately not awaited by most callers
 * (same reasoning as auth.js's warmGroupRoleMap — an unreachable backend
 * must not delay anything) except login.js's local-login path, which has
 * no second boot() to pick this up later otherwise.
 */
export async function syncLocaleFromServer() {
  try {
    const me = await api.get(`${CONFIG.HOUSEHOLD_BASE}/me`, { silent: true });
    await reconcileLocale(me.preferred_language);
  } catch {
    // Not logged in yet, or the backend is unreachable — keep whatever's
    // cached; the next successful boot/login tries again.
  }
}
