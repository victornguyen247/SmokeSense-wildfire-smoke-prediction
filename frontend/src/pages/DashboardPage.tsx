import { lazy, Suspense, useState } from "react";

import type { HorizonHours, Meta } from "../api/models";
import { AqiLegend } from "../components/forecast/AqiLegend";
import { Disclaimer } from "../components/forecast/Disclaimer";
import { ForecastStatus } from "../components/forecast/ForecastStatus";
import { HorizonControl } from "../components/forecast/HorizonControl";
import { ErrorMessage } from "../components/ui/ErrorMessage";
import { MockModeBadge } from "../components/ui/MockModeBadge";
import { Spinner } from "../components/ui/Spinner";
import { useForecastData } from "../hooks/useForecastData";
import { useMeta } from "../hooks/useMeta";
import { formatAgeMinutes } from "../utils/formatTime";

// MapLibre is most of the bundle; load it separately so the page and panel render first.
const ForecastMap = lazy(() => import("../components/map/ForecastMap"));

/** The map + forecast experience: map on the left, side panel on the right (below on phones). */
export function DashboardPage() {
  const meta = useMeta();
  const metaData = meta.status === "success" ? meta.data : undefined;
  const { cells, grid, monitors } = useForecastData(metaData);

  const [selectedHorizon, setSelectedHorizon] = useState<HorizonHours | null>(null);
  const horizon = selectedHorizon ?? metaData?.horizons[0] ?? 1;
  const gridHorizon = grid.data?.horizons.find((h) => h.horizon_hours === horizon);

  return (
    <div className="app">
      <header className="app-header">
        <h1 className="app-header__title">SmokeSense</h1>
        <p className="app-header__tagline">Wildfire smoke forecast for California</p>
        <MockModeBadge apiMockMode={metaData?.mock_mode} />
      </header>

      <main className="dashboard">
        <div className="dashboard__map">
          <Suspense fallback={<div className="dashboard__map-loading"><Spinner label="Loading map…" /></div>}>
            <ForecastMap
              meta={metaData}
              cells={cells.data}
              gridHorizon={gridHorizon}
              monitors={monitors.data}
              horizon={horizon}
            />
          </Suspense>
          {metaData?.forecast_stale && <StaleNotice meta={metaData} />}
          <p className="map-disclaimer">Experimental model estimate, not an official warning</p>
        </div>

        <aside className="dashboard__panel" aria-label="Forecast details">
          {meta.status === "loading" && <Spinner label="Loading forecast status…" />}
          {meta.status === "error" && (
            <ErrorMessage
              title="Couldn't load the forecast status"
              message={meta.error.message}
              onRetry={meta.retry}
            />
          )}
          {metaData && (
            <section className="panel-section" aria-labelledby="forecast-map-heading">
              <h2 id="forecast-map-heading" className="panel-section__heading">
                Smoke forecast
              </h2>
              {metaData.latest_issued_at === null ? (
                <p>No forecast has been issued yet.</p>
              ) : (
                <>
                  <HorizonControl
                    horizons={metaData.horizons}
                    value={horizon}
                    onChange={setSelectedHorizon}
                    targetTime={gridHorizon?.target_time}
                  />
                  {(cells.status === "loading" || grid.status === "loading") && (
                    <Spinner label="Loading the forecast map…" />
                  )}
                  {cells.status === "error" && (
                    <ErrorMessage title="Couldn't load the map grid" message={cells.error.message} onRetry={cells.retry} />
                  )}
                  {grid.status === "error" && (
                    <ErrorMessage title="Couldn't load the forecast" message={grid.error.message} onRetry={grid.retry} />
                  )}
                  {monitors.status === "error" && (
                    <ErrorMessage
                      title="Couldn't load the monitor forecasts"
                      message={monitors.error.message}
                      onRetry={monitors.retry}
                    />
                  )}
                </>
              )}
              <AqiLegend meta={metaData} />
            </section>
          )}
          {metaData && <ForecastStatus meta={metaData} />}
          <Disclaimer />
        </aside>
      </main>
    </div>
  );
}

/** Shown on the map while `/meta` says the newest forecast is older than it should be. */
function StaleNotice({ meta }: { meta: Meta }) {
  const age = meta.forecast_age_minutes === null ? "" : ` (issued ${formatAgeMinutes(meta.forecast_age_minutes)})`;
  return (
    <p className="map-notice" role="status">
      This forecast is out of date{age}. Newer data may be delayed.
    </p>
  );
}
