import { getForecastGrid, getForecastMonitors, getGridCells } from "../api/forecast";
import type { Meta } from "../api/models";
import { useApiQuery } from "./useApiQuery";

/**
 * Everything the forecast map draws, for all of California. Waits for `/meta`: the
 * grid is fetched once per `grid_key`, and the forecasts once per forecast cycle
 * (`latest_issued_at`), so switching horizon never refetches.
 */
export function useForecastData(meta: Meta | undefined) {
  const issuedAt = meta?.latest_issued_at ?? null;
  const cells = useApiQuery(
    (signal) => getGridCells(undefined, signal),
    meta ? `grid-cells:${meta.grid_key}` : null,
  );
  const grid = useApiQuery(
    (signal) => getForecastGrid(undefined, signal),
    issuedAt ? `forecast-grid:${issuedAt}` : null,
  );
  const monitors = useApiQuery(
    (signal) => getForecastMonitors(undefined, signal),
    issuedAt ? `forecast-monitors:${issuedAt}` : null,
  );
  return { cells, grid, monitors };
}
