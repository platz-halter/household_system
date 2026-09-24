import { getStoredTheme, applyTheme } from "./theme.js";
import { startRouter } from "./router.js";

// index.html's inline head script already applies the theme before first
// paint to avoid a flash; this just keeps the two in sync in case the
// stored value changes some other way.
applyTheme(getStoredTheme());

startRouter();
