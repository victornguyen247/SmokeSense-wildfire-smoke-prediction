# Frontend (React 19 + TypeScript + Vite + MapLibre)

Run from `frontend/`: `npm run dev` · `npm run lint` (**oxlint**, not ESLint/Prettier) · `npm run build` (`tsc -b && vite build`). CI runs lint + build. No test runner yet.

## Structure (`src/`)
`api/` the only place that calls the backend (typed `openapi-fetch` client) · `components/{ui,map,forecast}` · `features/{map,playback,city-history}` · `pages/` · `hooks/` · `context/` (only truly shared state) · `constants/` · `utils/` · `mocks/` (MSW).
Naming: components/pages `PascalCase.tsx`; hooks `useX.ts`; helpers/api files `camelCase.ts`.

## Rules
- Components never call `fetch`; they use `api/` functions or hooks. Base URL/headers are set once in `api/client.ts`.
- Display only: risk colors/labels/thresholds come from the backend (`/api/v1/meta`), never hardcoded. Always label forecasts "experimental model estimate, not an official warning".
- Server data lives in hooks/components and refetches on input change; it is not copied into global context.
- Local state first; extract a shared component only after repetition is real.
- Generated, never hand-edit or read: `src/api/types.ts`, `src/mocks/fixtures.ts`, `public/mockServiceWorker.js`. After `docs/api/openapi.yaml` changes run `npm run gen:api` (`npm run api:check` verifies). These scripts arrive with WEB-01 (branch `feat/web-01-map-shell-api-client`).
- API shapes: read `../docs/api/openapi.yaml`. Timestamps are UTC ISO-8601 `Z`.
- Remove `console.log` before merging to `prod`.
