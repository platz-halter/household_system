// Single source of truth for the frontend's displayed version (Settings
// page footer). Kept in lockstep with shared/src/shared/__init__.py's
// __version__ by hand — there's no build step to read one from the
// other, so bump both together on a real release.
export const APP_VERSION = "1.0.0";
