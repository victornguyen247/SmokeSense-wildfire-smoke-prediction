import type {
  GridCellCollection,
  GridForecast,
  HorizonHours,
  Meta,
  MonitorForecastCollection,
} from "../../api/models";
import { ForecastGridLayer } from "./ForecastGridLayer";
import MapView from "./MapView";
import { MonitorLayer } from "./MonitorLayer";

type ForecastMapProps = {
  meta: Meta | undefined;
  cells: GridCellCollection | undefined;
  gridHorizon: GridForecast["horizons"][number] | undefined;
  monitors: MonitorForecastCollection | undefined;
  horizon: HorizonHours;
};

/**
 * The map with its data layers. One module, so everything that needs MapLibre is in
 * the lazy-loaded map chunk. Each layer appears once its data has loaded.
 */
export default function ForecastMap({ meta, cells, gridHorizon, monitors, horizon }: ForecastMapProps) {
  return (
    <MapView>
      {meta && cells && (
        <ForecastGridLayer
          cells={cells}
          horizon={gridHorizon}
          categories={meta.aqi_categories}
          lowConfidenceDistKm={meta.low_confidence_dist_km}
        />
      )}
      {meta && monitors && (
        <MonitorLayer
          monitors={monitors}
          horizon={horizon}
          categories={meta.aqi_categories}
          categoryLabel={meta.aqi_category_label}
        />
      )}
    </MapView>
  );
}
