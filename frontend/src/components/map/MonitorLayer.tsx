import { useEffect, useMemo } from "react";
import type { GeoJSONSource } from "maplibre-gl";

import type {
  AqiCategoryInfo,
  HorizonHours,
  MonitorForecastCollection,
} from "../../api/models";
import { useMap } from "../../context/MapContext";
import { categoryColorExpression, categoryInfo, formatPm25 } from "../../utils/aqi";
import { removeFromMap, setLayersVisible } from "../../utils/map";
import { bindPointPopup, type PopupLine } from "../../utils/popup";

const SOURCE_ID = "forecast-monitors";
const LAYER_ID = "forecast-monitors-circle";

type MonitorLayerProps = {
  /** Undefined until loaded: the layer is added empty, so it keeps its place in the stack. */
  monitors: MonitorForecastCollection | undefined;
  horizon: HorizonHours;
  categories: AqiCategoryInfo[];
  /** `/meta` `aqi_category_label`, shown in the popup. */
  categoryLabel: string;
  visible: boolean;
};

type MonitorPointProps = {
  name: string;
  aqs_code: string;
  aqi: string;
  /** Left out when the monitor has no forecast at this horizon. */
  pm25?: number;
  fallback: boolean;
};

type MonitorPoints = {
  type: "FeatureCollection";
  features: {
    type: "Feature";
    geometry: MonitorForecastCollection["features"][number]["geometry"];
    properties: MonitorPointProps;
  }[];
};

/**
 * Model forecasts at AirNow monitors, drawn on top of the grid and colored for the
 * selected horizon. A `fallback` forecast (the monitor had no recent reading) is a
 * hollow circle: lower confidence (docs/api.md, "method and source").
 */
export function MonitorLayer({ monitors, horizon, categories, categoryLabel, visible }: MonitorLayerProps) {
  const map = useMap();

  const points = useMemo<MonitorPoints>(
    () => ({
      type: "FeatureCollection",
      features: (monitors?.features ?? []).map((feature) => {
        const value = feature.properties.forecasts.find((f) => f.horizon_hours === horizon);
        return {
          type: "Feature",
          geometry: feature.geometry,
          properties: {
            name: feature.properties.name ?? `Monitor ${feature.properties.aqs_code}`,
            aqs_code: feature.properties.aqs_code,
            aqi: value?.aqi_category ?? "",
            ...(value && { pm25: value.pm25 }),
            fallback: value?.source === "fallback",
          },
        };
      }),
    }),
    [monitors, horizon],
  );

  useEffect(() => {
    if (!map) return;
    const color = categoryColorExpression(categories, ["get", "aqi"]);
    map.addSource(SOURCE_ID, { type: "geojson", data: { type: "FeatureCollection", features: [] } });
    map.addLayer({
      id: LAYER_ID,
      type: "circle",
      source: SOURCE_ID,
      paint: {
        "circle-radius": ["interpolate", ["linear"], ["zoom"], 5, 5, 10, 9],
        "circle-color": ["case", ["get", "fallback"], "#ffffff", color],
        "circle-stroke-color": ["case", ["get", "fallback"], color, "#ffffff"],
        "circle-stroke-width": ["case", ["get", "fallback"], 3, 1.5],
      },
    });

    const unbindPopup = bindPointPopup(map, LAYER_ID, (feature) =>
      monitorPopup(feature.properties as MonitorPointProps, categories, categoryLabel),
    );

    return () => {
      unbindPopup();
      removeFromMap(map, [LAYER_ID], [SOURCE_ID]);
    };
  }, [map, categories, categoryLabel]);

  useEffect(() => {
    (map?.getSource(SOURCE_ID) as GeoJSONSource | undefined)?.setData(points);
  }, [map, points, categories, categoryLabel]);

  useEffect(() => {
    if (map) setLayersVisible(map, [LAYER_ID], visible);
  }, [map, visible, categories, categoryLabel]);

  return null;
}

function monitorPopup(
  props: MonitorPointProps,
  categories: AqiCategoryInfo[],
  categoryLabel: string,
): PopupLine[] {
  const lines: PopupLine[] = [
    { text: props.name, className: "map-popup__title" },
    { text: `AirNow monitor ${props.aqs_code}`, className: "map-popup__muted" },
  ];
  // MapLibre drops null properties, so a missing value arrives as undefined, not null.
  if (typeof props.pm25 !== "number") {
    lines.push({ text: "No forecast at this horizon." });
  } else {
    const label = categoryInfo(categories, props.aqi as AqiCategoryInfo["key"])?.label ?? props.aqi;
    lines.push({ text: `Forecast PM2.5: ${formatPm25(props.pm25)}` }, { text: `${categoryLabel}: ${label}` });
  }
  if (props.fallback) {
    lines.push({ text: "Lower confidence: no recent reading at this monitor.", className: "map-popup__warning" });
  }
  return lines;
}
