// Minimal stroke-style icon set (matches the black & white aesthetic —
// icons are just currentColor strokes, so they follow the active theme
// automatically). Each is a <svg> string meant for innerHTML insertion.
// Shared ones (settings, close, plus, ...) are kept visually identical to
// storage/frontend/js/icons.js.

export const icons = {
  home: `<svg class="icon" viewBox="0 0 24 24"><path d="m3 11 9-8 9 8"/><path d="M5 10v10h14V10"/><path d="M9 20v-6h6v6"/></svg>`,
  board: `<svg class="icon" viewBox="0 0 24 24"><rect x="4" y="4" width="16" height="17" rx="2"/><path d="M9 3h6v4H9zM8 11h8M8 15h5"/></svg>`,
  chart: `<svg class="icon" viewBox="0 0 24 24"><path d="M4 20V10M10 20V4M16 20v-7M22 20H2"/></svg>`,
  tag: `<svg class="icon" viewBox="0 0 24 24"><path d="M20 10 13 3H4v9l7 7 9-9Z"/><circle cx="8.5" cy="7.5" r="1.2"/></svg>`,
  settings: `<svg class="icon" viewBox="0 0 24 24"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .34 1.87l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.7 1.7 0 0 0-1.87-.34 1.7 1.7 0 0 0-1 1.55V21a2 2 0 1 1-4 0v-.09a1.7 1.7 0 0 0-1-1.55 1.7 1.7 0 0 0-1.87.34l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06A1.7 1.7 0 0 0 4.6 15a1.7 1.7 0 0 0-1.55-1H3a2 2 0 1 1 0-4h.09A1.7 1.7 0 0 0 4.6 9a1.7 1.7 0 0 0-.34-1.87l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06A1.7 1.7 0 0 0 9 4.6a1.7 1.7 0 0 0 1-1.55V3a2 2 0 1 1 4 0v.09a1.7 1.7 0 0 0 1 1.55 1.7 1.7 0 0 0 1.87-.34l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06A1.7 1.7 0 0 0 19.4 9a1.7 1.7 0 0 0 1.55 1H21a2 2 0 1 1 0 4h-.09a1.7 1.7 0 0 0-1.51 1Z"/></svg>`,
  search: `<svg class="icon" viewBox="0 0 24 24"><circle cx="11" cy="11" r="7"/><path d="m21 21-4.3-4.3"/></svg>`,
  filter: `<svg class="icon" viewBox="0 0 24 24"><path d="M4 5h16M7 12h10M10 19h4"/></svg>`,
  plus: `<svg class="icon" viewBox="0 0 24 24"><path d="M12 5v14M5 12h14"/></svg>`,
  close: `<svg class="icon" viewBox="0 0 24 24"><path d="m6 6 12 12M18 6 6 18"/></svg>`,
  chevronLeft: `<svg class="icon" viewBox="0 0 24 24"><path d="m15 6-6 6 6 6"/></svg>`,
  chevronRight: `<svg class="icon" viewBox="0 0 24 24"><path d="m9 6 6 6-6 6"/></svg>`,
  trash: `<svg class="icon" viewBox="0 0 24 24"><path d="M4 7h16M9 7V4h6v3m-8 0 1 13h8l1-13"/></svg>`,
  logout: `<svg class="icon" viewBox="0 0 24 24"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4M16 17l5-5-5-5M21 12H9"/></svg>`,
  check: `<svg class="icon" viewBox="0 0 24 24"><path d="M20 6 9 17l-5-5"/></svg>`,
  checklist: `<svg class="icon" viewBox="0 0 24 24"><path d="m3 7 2 2 4-4M3 15l2 2 4-4M11 7h10M11 15h10"/></svg>`,
  coffee: `<svg class="icon" viewBox="0 0 24 24"><path d="M3 9h14v6a4 4 0 0 1-4 4H7a4 4 0 0 1-4-4V9Z"/><path d="M17 10h1.5a2.5 2.5 0 0 1 0 5H17"/><path d="M6 2c0 1-1 1-1 2s1 1 1 2M10 2c0 1-1 1-1 2s1 1 1 2"/></svg>`,
  star: `<svg class="icon" viewBox="0 0 24 24"><path d="m12 3 2.7 5.6 6.1.9-4.4 4.3 1 6.1L12 17l-5.4 2.9 1-6.1L3.2 9.5l6.1-.9Z"/></svg>`,
  calendar: `<svg class="icon" viewBox="0 0 24 24"><rect x="3" y="5" width="18" height="16" rx="2"/><path d="M16 3v4M8 3v4M3 10h18"/></svg>`,
  users: `<svg class="icon" viewBox="0 0 24 24"><circle cx="9" cy="8" r="3"/><path d="M3 20c0-3.3 2.7-6 6-6s6 2.7 6 6"/><circle cx="17" cy="9" r="2.5"/><path d="M21 20c0-2.6-1.9-4.8-4.5-5.4"/></svg>`,
  edit: `<svg class="icon" viewBox="0 0 24 24"><path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4Z"/></svg>`,
  box: `<svg class="icon" viewBox="0 0 24 24"><path d="M21 8 12 3 3 8l9 5 9-5Z"/><path d="M3 8v8l9 5 9-5V8M12 13v8"/></svg>`,
  camera: `<svg class="icon" viewBox="0 0 24 24"><path d="M4 7h3l2-3h6l2 3h3a1 1 0 0 1 1 1v11a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V8a1 1 0 0 1 1-1Z"/><circle cx="12" cy="13" r="3.5"/></svg>`,
  scale: `<svg class="icon" viewBox="0 0 24 24"><path d="M12 3v18M7 21h10M5 7l-3 7a3.5 3.5 0 0 0 6 0ZM19 7l-3 7a3.5 3.5 0 0 0 6 0ZM5 7h14M12 3l-3 4h6Z"/></svg>`,
  handRaised: `<svg class="icon" viewBox="0 0 24 24"><path d="M9 11V5a1.5 1.5 0 0 1 3 0v5M12 10V4a1.5 1.5 0 0 1 3 0v6M15 10V6a1.5 1.5 0 0 1 3 0v8a6 6 0 0 1-6 6h-1a6 6 0 0 1-5.2-3l-2.4-4.2a1.4 1.4 0 0 1 2.3-1.6L8 17"/></svg>`,
  swap: `<svg class="icon" viewBox="0 0 24 24"><path d="m17 3 4 4-4 4"/><path d="M3 7h18"/><path d="m7 21-4-4 4-4"/><path d="M21 17H3"/></svg>`,
  send: `<svg class="icon" viewBox="0 0 24 24"><path d="m3 11 18-8-8 18-2-8-8-2Z"/></svg>`,
  bell: `<svg class="icon" viewBox="0 0 24 24"><path d="M6 10a6 6 0 0 1 12 0c0 3.2 1 5 2 6H4c1-1 2-2.8 2-6Z"/><path d="M9.5 19a2.5 2.5 0 0 0 5 0"/></svg>`,
};
