# Frontend Architecture (React + Vite)

The frontend is a single React + TypeScript application built with Vite. It renders the interactive map, forecast cards, alerts, historical playback, and the City Air Quality History view. It talks to the backend **only** through the services layer.

---

## 1. Core principle

The frontend **displays** data and **captures** user intent. It does not decide correctness or safety — the backend does. Concretely:

- Risk thresholds, forecasts, and "is this unhealthy?" come from the backend. The UI colors and labels what it's given; it does not invent its own thresholds.
- Frontend validation exists for user experience (fast feedback). The backend is the authority on what's valid.

---

## 2. Folder structure

```
frontend/src/
  api/          typed client + request functions (the ONLY place that calls the backend)
  assets/       static images, icons
  components/   reusable UI
    ui/         generic building blocks (Button, Input, Spinner)
    map/        map layers and controls
    forecast/   forecast card, "why?" panel
    city-history/  charts for the City Air Quality History view
  constants/    static values used across the app
  context/      shared state (only when genuinely shared)
  hooks/        reusable React hooks
  pages/        route-level screens
  routes/       routing and route guards
  types/        shared TypeScript types (mirror backend schemas)
  utils/        helper functions
```

---

## 3. Folder responsibilities

### `pages/`
Route-level screens — full pages, not reusable fragments.

```
DashboardPage.tsx      the map + forecast experience
CityHistoryPage.tsx    the City Air Quality History view
```

A page composes components and hooks; it shouldn't hold reusable UI logic that another page might want. If two pages need the same piece, extract it into `components/`.

### `components/`
Reusable UI elements, grouped by domain:

- `ui/` — generic, app-agnostic (Button, Input, Spinner).
- `map/` — map layers and controls (fire markers, wind vectors, PM2.5 overlay, impact zones).
- `forecast/` — the forecast card and the "why?" explanation panel.
- `city-history/` — the trend line, seasonal chart, and unhealthy-days count.

A component becomes shared once it's used **more than twice**. Build it clearly in place first, confirm the repetition, then extract.

### `api/`
The **only** place that talks to the backend. Everything else calls functions from here.

```
api/
  client.ts          base fetch/axios setup: base URL, headers, error handling
  types.ts           request/response types (see "Type sync" below)
  predictions.ts     getForecast(location), ...
  cityHistory.ts     getCityHistory(city), ...
  alerts.ts          getAlerts(location), ...
```

Rules:

- Components and pages **must not** call `fetch` directly. They call a function from `api/`.
- Base URL and auth headers are configured **once** in `client.ts`, not repeated per call.
- Each api file is focused on one domain.

### `context/`
Shared state, only when it's genuinely shared across the tree — e.g. the selected location, or the current user if we add auth. Context is not a dumping ground; if data is used by one component, keep it in local state.

### `routes/`
Application routing and any route guards (for example, protecting an alerts-management screen if we add accounts).

### `hooks/`, `utils/`, `types/`, `constants/`
Reusable hooks, pure helper functions, shared types, and static values respectively. Keep them small and general.

---

## 4. Naming conventions

- **Components and pages:** `PascalCase` — `ForecastCard.tsx`, `CityHistoryPage.tsx`.
- **Hooks:** `camelCase` starting with `use` — `useForecast.ts`.
- **Helpers, api files, non-component files:** `camelCase` — `formatPm25.ts`, `cityHistory.ts`.
- **Types/interfaces:** `PascalCase` — `Forecast`, `CityHistoryPoint`.

---

## 5. Component design

Each component should have a **single responsibility** and stay small enough to read at a glance. When a component grows past that — juggling data fetching, formatting, and rendering several sections — break it up:

- Move data fetching into a hook (`useForecast`).
- Move formatting into `utils/`.
- Keep the component focused on rendering.

---

## 6. State management

- **Local state first.** If data is used in one component, `useState` there.
- **Lift state** only when multiple children need it.
- **Context** only when state is shared across distant parts of the tree.
- **Server state is not app state.** Data fetched from the backend (forecasts, history) belongs in the component/hook that needs it, refetched when inputs change — not copied into global context where it can go stale. If we later add a data-fetching library (React Query or similar), that becomes its home.

---

## 7. Type sync with the backend

The backend is FastAPI, which auto-generates an OpenAPI schema at `/openapi.json`. To avoid the frontend and backend drifting apart on request/response shapes — a classic mid-project bug — generate frontend types from that schema instead of hand-writing them.

Recommended setup (one person, early):

```bash
npm install -D openapi-typescript
# add to package.json scripts:
#   "gen:types": "openapi-typescript http://localhost:8000/openapi.json -o src/api/types.ts"
npm run gen:types
```

Re-run `npm run gen:types` after any backend schema change. Treat `src/api/types.ts` as generated — don't edit it by hand.

---

## 8. Code style

- Format with **Prettier**; lint with **ESLint**. Both run in CI (see [CONTRIBUTING.md](../CONTRIBUTING.md)).
- `console.log` is fine in development but removed before merging to `prod`.
- Prefer readable names and small focused functions over cleverness.

---

## 9. Design and UI

For visual design direction (palette, typography, map styling), keep choices deliberate and specific to an air-quality product — not generic dashboard defaults. Coordinate on a small shared set of design tokens (colors, spacing, type scale) so the dashboard and the City History view feel like one product. Air-quality color scales in particular should map to the official AQI categories the backend uses, so the map's colors mean the same thing the model does.
