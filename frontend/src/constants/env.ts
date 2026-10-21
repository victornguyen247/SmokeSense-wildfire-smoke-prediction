// The only place that reads build-time settings. Vite inlines VITE_* values when the
// app is built, so switching between mock mode, local API-01 and staging is a .env
// change plus a rebuild (or a dev-server restart), never a code change.

const DEFAULT_API_BASE_URL = "http://localhost:8000";

// Free, keyless vector basemap with OpenStreetMap data (attribution is in the style).
const DEFAULT_MAP_STYLE_URL = "https://tiles.openfreemap.org/styles/positron";

export const API_BASE_URL =
  (import.meta.env.VITE_API_BASE_URL ?? "").replace(/\/+$/, "") || DEFAULT_API_BASE_URL;

export const USE_MOCKS = import.meta.env.VITE_USE_MOCKS === "true";

export const MAP_STYLE_URL = import.meta.env.VITE_MAP_STYLE_URL || DEFAULT_MAP_STYLE_URL;
