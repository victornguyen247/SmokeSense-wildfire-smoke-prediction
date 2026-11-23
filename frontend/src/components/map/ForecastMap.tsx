import { useMemo } from "react";

import type {
  AqiCategoryInfo,
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
import { LocationPicker } from "./LocationPicker";
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
  /** WEB-04: the location the forecast card shows, and a map click that picks one. */
  selectedLocation: { lat: number; lon: number } | null;
  onPickLocation: (lat: number, lon: number) => void;
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
  selectedLocation,
  onPickLocation,
}: ForecastMapProps) {
  // /meta is refetched every few minutes as a new object. Keep the categories stable while
  // their content is the same, so the layers aren't removed and re-added (which would
  // close popups and change the layer order).
  const categoriesKey = JSON.stringify(meta?.aqi_categories ?? []);
  const categories = useMemo(() => JSON.parse(categoriesKey) as AqiCategoryInfo[], [categoriesKey]);

  if (!meta) return <MapView />;
  return (
    <MapView>
      {cells && (
        <ForecastGridLayer
          cells={cells}
          horizon={gridHorizon}
          categories={categories}
          lowConfidenceDistKm={meta.low_confidence_dist_km}
          visible={visible.forecast}
        />
      )}
      {/* The point layers mount together and fill in as their data arrives, so they
          stack in this order (fires on top) whatever loads first. The grid sits below
          the basemap labels. */}
      <SensorLayer
        sensors={sensors}
        categories={categories}
        categoryLabel={meta.aqi_category_label}
        visible={visible.sensors}
      />
      <MonitorLayer
        monitors={monitors}
        horizon={horizon}
        categories={categories}
        categoryLabel={meta.aqi_category_label}
        visible={visible.forecast}
      />
      <WindLayer wind={wind} visible={visible.wind} />
      <FireLayer fires={fires} visible={visible.fires} />
      <LocationPicker selected={selectedLocation} onPick={onPickLocation} />
    </MapView>
  );
}
