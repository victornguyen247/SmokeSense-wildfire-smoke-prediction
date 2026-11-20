import { useEffect } from "react";
import type { ExpressionSpecification, GeoJSONSource } from "maplibre-gl";

import type { AqiCategoryInfo, ObservationCollection } from "../../api/models";
import { SENSOR_ATTRIBUTION } from "../../constants/sources";
import { useMap } from "../../context/MapContext";
import { categoryColorExpression, categoryInfo, formatPm25 } from "../../utils/aqi";
import { formatLocalDateTime } from "../../utils/formatTime";
import { removeFromMap, setLayersVisible } from "../../utils/map";
import { bindPointPopup, type PopupLine } from "../../utils/popup";

const SOURCE_ID = "observations-pm25";
const LAYER_ID = "observations-pm25-square";
const ICON_ID = "sensor-square";

type SensorProps = ObservationCollection["features"][number]["properties"];

const PROVIDER_LABELS: Record<SensorProps["provider"], string> = {
  airnow: "AirNow (regulatory monitor)",
  purpleair: "PurpleAir (low-cost sensor, EPA-corrected)",
};

type SensorLayerProps = {
  /** Undefined until loaded: the layer is added empty, so it keeps its place in the stack. */
  sensors: ObservationCollection | undefined;
  categories: AqiCategoryInfo[];
  /** `/meta` `aqi_category_label`, shown in the popup. */
  categoryLabel: string;
  visible: boolean;
};

/**
 * The latest measured PM2.5 per outdoor sensor, colored by AQI category. Squares, so a
 * measurement is never confused with a forecast (circles). AirNow monitors are larger
 * with a dark ring; PurpleAir sensors are smaller with a white ring.
 */
export function SensorLayer({ sensors, categories, categoryLabel, visible }: SensorLayerProps) {
  const map = useMap();

  useEffect(() => {
    if (!map) return;
    map.addSource(SOURCE_ID, {
      type: "geojson",
      data: { type: "FeatureCollection", features: [] },
      attribution: SENSOR_ATTRIBUTION,
    });
    const isAirNow: ExpressionSpecification = ["==", ["get", "provider"], "airnow"];
    if (!map.hasImage(ICON_ID)) map.addImage(ICON_ID, squareSdf(), { sdf: true });
    map.addLayer({
      id: LAYER_ID,
      type: "symbol",
      source: SOURCE_ID,
      layout: {
        "icon-image": ICON_ID,
        "icon-size": ["interpolate", ["linear"], ["zoom"], 5, ["case", isAirNow, 0.45, 0.35], 10, ["case", isAirNow, 0.8, 0.6]],
        "icon-allow-overlap": true,
        "icon-ignore-placement": true,
      },
      paint: {
        "icon-color": categoryColorExpression(categories, ["get", "aqi_category"]),
        "icon-halo-color": ["case", isAirNow, "#1f2328", "#ffffff"],
        "icon-halo-width": ["case", isAirNow, 2, 1.5],
      },
    });
    const unbindPopup = bindPointPopup(map, LAYER_ID, (feature) =>
      sensorPopup(feature.properties as SensorProps, categories, categoryLabel),
    );
    return () => {
      unbindPopup();
      removeFromMap(map, [LAYER_ID], [SOURCE_ID]);
    };
  }, [map, categories, categoryLabel]);

  useEffect(() => {
    if (sensors) (map?.getSource(SOURCE_ID) as GeoJSONSource | undefined)?.setData(sensors);
  }, [map, sensors, categories, categoryLabel]);

  useEffect(() => {
    if (map) setLayersVisible(map, [LAYER_ID], visible);
  }, [map, visible, categories, categoryLabel]);

  return null;
}

/**
 * A square as a signed distance field, so MapLibre can color it per feature
 * (`icon-color`) and draw a ring (`icon-halo-*`). 0.75 alpha is the edge.
 */
function squareSdf(): { width: number; height: number; data: Uint8Array } {
  const size = 32;
  const half = 10;
  const data = new Uint8Array(size * size * 4);
  for (let y = 0; y < size; y++) {
    for (let x = 0; x < size; x++) {
      const dx = Math.abs(x + 0.5 - size / 2);
      const dy = Math.abs(y + 0.5 - size / 2);
      const inside = half - Math.max(dx, dy); // > 0 inside the square
      const alpha = Math.max(0, Math.min(255, 192 + inside * 24));
      data.set([255, 255, 255, alpha], (y * size + x) * 4);
    }
  }
  return { width: size, height: size, data };
}

function sensorPopup(props: SensorProps, categories: AqiCategoryInfo[], categoryLabel: string): PopupLine[] {
  const label = categoryInfo(categories, props.aqi_category)?.label ?? props.aqi_category;
  return [
    { text: props.name ?? `Sensor ${props.station_code}`, className: "map-popup__title" },
    { text: PROVIDER_LABELS[props.provider], className: "map-popup__muted" },
    { text: `Measured PM2.5: ${formatPm25(props.pm25)}` },
    { text: `${categoryLabel}: ${label}` },
    { text: `Hour starting ${formatLocalDateTime(props.valid_at)}` },
  ];
}
