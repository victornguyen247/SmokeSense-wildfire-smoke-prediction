/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Backend origin, e.g. http://localhost:8000. Paths already start with /api/v1. */
  readonly VITE_API_BASE_URL?: string;
  /** "true" serves docs/api fixtures from the browser (MSW) instead of calling the API. */
  readonly VITE_USE_MOCKS?: string;
  /** MapLibre style URL for the basemap. */
  readonly VITE_MAP_STYLE_URL?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
