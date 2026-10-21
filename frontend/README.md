# SmokeSense frontend

React + TypeScript + Vite. A California map (MapLibre) with a side panel, a typed API client generated from the PM-02 contract, and a mock mode that runs the whole app on the contract's fixtures with no backend.

Conventions (folders, naming, state) are in [docs/frontend.md](../docs/frontend.md); the API contract is in [docs/api.md](../docs/api.md).

## Run it

```bash
cd frontend
cp .env.example .env     # mock mode is on by default
npm install
npm run dev              # http://localhost:5173
```

Or with the whole stack: `make up` from the repo root.

## Settings (`.env`)

| Variable | Default | What it does |
|---|---|---|
| `VITE_USE_MOCKS` | `true` in `.env.example` | `true`: every API call is answered in the browser from `docs/api/fixtures` (a "Demo data" badge is shown). `false`: calls the real API. |
| `VITE_API_BASE_URL` | `http://localhost:8000` | Backend origin, e.g. local API-01 or staging. Paths already include `/api/v1`. |
| `VITE_MAP_STYLE_URL` | OpenFreeMap Positron | MapLibre basemap style. Free and keyless; OpenStreetMap attribution is shown on the map. |

Vite bakes these in when the dev server starts or the app is built, so after changing one, restart `npm run dev` or rebuild. Switching between mock mode, local API-01 and staging never needs a code change.

## Mock mode

[MSW](https://mswjs.io/) intercepts requests in the browser (`src/mocks/`). It loads only when `VITE_USE_MOCKS=true`, so production builds never download it.

To see the other UI states, add a parameter to the page URL:

- `?mock=slow`: every response waits 3 s (loading states)
- `?mock=error`: every response is a 500 `internal_error` (error states)

`/forecast/point` behaves like the real API: lat/lon outside California or a non-California ZIP returns `404 out_of_scope`, passing both or neither returns `400 invalid_query`, and a point near the Mendocino National Forest fixture returns the "no forecast" case.

## The API contract: `npm run gen:api`

`docs/api/openapi.yaml` is the source of truth. `scripts/sync-api.mjs` generates two committed files from it:

- `src/api/types.ts`: TypeScript types for every path and schema (openapi-typescript)
- `src/mocks/fixtures.ts`: every `docs/api/fixtures/*.json`, each checked against its response type, so `npm run build` fails if a fixture and the spec disagree

They are committed because the frontend Docker build only sees `frontend/`. Never edit them by hand:

```bash
npm run gen:api     # after the contract in docs/api/ changes; commit the result
npm run api:check   # CI runs this and fails if the generated files are out of date
```

## Calling the API

Components never call `fetch`. They call a function from `src/api/` (`getMeta`, `getGridCells`, `getForecastGrid`, `getForecastPoint`, `getForecastMonitors`, `getActiveFires`, `getLatestPm25`), usually through `useApiQuery`:

```tsx
const meta = useApiQuery((signal) => getMeta(signal), []);
if (meta.status === "loading") return <Spinner label="Loading…" />;
if (meta.status === "error") return <ErrorMessage title="…" message={meta.error.message} onRetry={meta.retry} />;
return <ForecastStatus meta={meta.data} />;
```

Every failure is an `ApiError` with the API's stable `code` (`out_of_scope`, `invalid_query`, …, or `network_error`) and a `message` that is safe to show.

## Map layers

`<MapView>` creates the map. Layers for WEB-02/03 go inside it as children and get the loaded map from `useMap()` (null until the basemap has loaded).

## Checks

```bash
npm run lint        # oxlint
npm run build       # type-check + production build
npm run api:check   # generated API files match docs/api/
```
