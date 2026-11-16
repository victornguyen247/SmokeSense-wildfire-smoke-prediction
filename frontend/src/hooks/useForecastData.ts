import { getForecastGrid, getForecastMonitors, getGridCells } from "../api/forecast";
import type { Meta } from "../api/models";
import { useApiQuery } from "./useApiQuery";

/**
 * Everything the forecast map draws, for all of California. Waits for `/meta`. The
 * forecasts are fetched once per forecast cycle (`latest_issued_at`), so switching
 * horizon never refetches, and a new cycle replaces the old one without blanking the
 * map. The grid is fetched for the forecast's own `grid_key`, so values and polygons
 * always come from the same grid, even right after the grid is regenerated.
 */
export function useForecastData(meta: Meta | undefined) {
  const issuedAt = meta?.latest_issued_at ?? null;
  const grid = useApiQuery(
    (signal) => getForecastGrid(undefined, signal),
    issuedAt ? `forecast-grid:${issuedAt}` : null,
    { keepPrevious: true },
  );
  const monitors = useApiQuery(
    (signal) => getForecastMonitors(undefined, signal),
    issuedAt ? `forecast-monitors:${issuedAt}` : null,
    { keepPrevious: true },
  );
  const gridKey = grid.data?.grid_key ?? meta?.grid_key;
  const cells = useApiQuery(
    (signal) => getGridCells(undefined, signal),
    gridKey ? `grid-cells:${gridKey}` : null,
  );
  return { cells, grid, monitors };
}
