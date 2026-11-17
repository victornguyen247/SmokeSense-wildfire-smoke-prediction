import type {
  FireDetectionCollection,
  GridCellCollection,
  GridForecast,
  HorizonHours,
  Meta,
  MonitorForecastCollection,
  ObservationCollection,
  WindObservationCollection,
} from "../../api/models";
import { FireLayer } from "./FireLayer";
import { ForecastGridLayer } from "./ForecastGridLayer";
import type { LayerVisibility } from "./LayerControl";
import MapView from "./MapView";
import { MonitorLayer } from "./MonitorLayer";
import { SensorLayer } from "./SensorLayer";
import { WindLayer } from "./WindLayer";

type ForecastMapProps = {
  meta: Meta | undefined;
  cells: GridCellCollection | undefined;
  gridHorizon: GridForecast["horizons"][number] | undefined;
  monitors: MonitorForecastCollection | undefined;
  horizon: HorizonHours;
  fires: FireDetectionCollection | undefined;
  sensors: ObservationCollection | undefined;
  wind: WindObservationCollection | undefined;
  visible: LayerVisibility;
};

/**
 * The map with its data layers. One module, so everything that needs MapLibre is in
 * the lazy-loaded map chunk. Each layer appears once its data has loaded.
 */
export default function ForecastMap({
  meta,
  cells,
  gridHorizon,
  monitors,
  horizon,
  fires,
  sensors,
  wind,
  visible,
}: ForecastMapProps) {
  if (!meta) return <MapView />;
  return (
    <MapView>
      {cells && (
        <ForecastGridLayer
          cells={cells}
          horizon={gridHorizon}
          categories={meta.aqi_categories}
          lowConfidenceDistKm={meta.low_confidence_dist_km}
          visible={visible.forecast}
        />
      )}
      {/* The point layers mount together and fill in as their data arrives, so they
          stack in this order (fires on top) whatever loads first. The grid sits below
          the basemap labels. */}
      <SensorLayer
        sensors={sensors}
        categories={meta.aqi_categories}
        categoryLabel={meta.aqi_category_label}
        visible={visible.sensors}
      />
      <MonitorLayer
        monitors={monitors}
        horizon={horizon}
        categories={meta.aqi_categories}
        categoryLabel={meta.aqi_category_label}
        visible={visible.forecast}
      />
      <WindLayer wind={wind} visible={visible.wind} />
      <FireLayer fires={fires} visible={visible.fires} />
    </MapView>
  );
}
