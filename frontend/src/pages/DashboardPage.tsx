import { lazy, Suspense } from "react";

import { Disclaimer } from "../components/forecast/Disclaimer";
import { ForecastStatus } from "../components/forecast/ForecastStatus";
import { ErrorMessage } from "../components/ui/ErrorMessage";
import { MockModeBadge } from "../components/ui/MockModeBadge";
import { Spinner } from "../components/ui/Spinner";
import { useMeta } from "../hooks/useMeta";

// MapLibre is most of the bundle; load it separately so the page and panel render first.
const MapView = lazy(() => import("../components/map/MapView"));

/** The map + forecast experience: map on the left, side panel on the right (below on phones). */
export function DashboardPage() {
  const meta = useMeta();

  return (
    <div className="app">
      <header className="app-header">
        <h1 className="app-header__title">SmokeSense</h1>
        <p className="app-header__tagline">Wildfire smoke forecast for California</p>
        <MockModeBadge />
      </header>

      <main className="dashboard">
        <div className="dashboard__map">
          <Suspense fallback={<div className="dashboard__map-loading"><Spinner label="Loading map…" /></div>}>
            <MapView />
          </Suspense>
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
          {meta.status === "success" && <ForecastStatus meta={meta.data} />}
          <Disclaimer />
        </aside>
      </main>
    </div>
  );
}
