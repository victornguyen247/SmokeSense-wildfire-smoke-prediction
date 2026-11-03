import { useEffect, useMemo } from "react";
import maplibregl, { type GeoJSONSource, type MapLayerMouseEvent } from "maplibre-gl";

import type {
  AqiCategoryInfo,
  HorizonHours,
  MonitorForecastCollection,
} from "../../api/models";
import { useMap } from "../../context/MapContext";
import { categoryColorExpression, categoryInfo, formatPm25 } from "../../utils/aqi";
import { removeFromMap } from "../../utils/map";

const SOURCE_ID = "forecast-monitors";
const LAYER_ID = "forecast-monitors-circle";

type MonitorLayerProps = {
  monitors: MonitorForecastCollection;
  horizon: HorizonHours;
  categories: AqiCategoryInfo[];
  /** `/meta` `aqi_category_label`, shown in the popup. */
  categoryLabel: string;
};

type MonitorPointProps = {
  name: string;
  aqs_code: string;
  aqi: string;
  pm25: number | null;
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
export function MonitorLayer({ monitors, horizon, categories, categoryLabel }: MonitorLayerProps) {
  const map = useMap();

  const points = useMemo<MonitorPoints>(
    () => ({
      type: "FeatureCollection",
      features: monitors.features.map((feature) => {
        const value = feature.properties.forecasts.find((f) => f.horizon_hours === horizon);
        return {
          type: "Feature",
          geometry: feature.geometry,
          properties: {
            name: feature.properties.name ?? `Monitor ${feature.properties.aqs_code}`,
            aqs_code: feature.properties.aqs_code,
            aqi: value?.aqi_category ?? "",
            pm25: value?.pm25 ?? null,
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

    const popup = new maplibregl.Popup({ closeButton: true, maxWidth: "260px" });
    const onClick = (event: MapLayerMouseEvent) => {
      const feature = event.features?.[0];
      if (!feature || feature.geometry.type !== "Point") return;
      const props = feature.properties as MonitorPointProps;
      popup
        .setLngLat(feature.geometry.coordinates as [number, number])
        .setDOMContent(monitorPopup(props, categories, categoryLabel))
        .addTo(map);
    };
    const onEnter = () => {
      map.getCanvas().style.cursor = "pointer";
    };
    const onLeave = () => {
      map.getCanvas().style.cursor = "";
    };
    map.on("click", LAYER_ID, onClick);
    map.on("mouseenter", LAYER_ID, onEnter);
    map.on("mouseleave", LAYER_ID, onLeave);

    return () => {
      popup.remove();
      map.off("click", LAYER_ID, onClick);
      map.off("mouseenter", LAYER_ID, onEnter);
      map.off("mouseleave", LAYER_ID, onLeave);
      removeFromMap(map, [LAYER_ID], [SOURCE_ID]);
    };
  }, [map, categories, categoryLabel]);

  useEffect(() => {
    (map?.getSource(SOURCE_ID) as GeoJSONSource | undefined)?.setData(points);
  }, [map, points, categories, categoryLabel]);

  return null;
}

/** Popup body, built with text nodes: monitor names come from the API. */
function monitorPopup(
  props: MonitorPointProps,
  categories: AqiCategoryInfo[],
  categoryLabel: string,
): HTMLElement {
  const root = document.createElement("div");
  root.className = "map-popup";
  const line = (text: string, className?: string) => {
    const p = document.createElement("p");
    p.textContent = text;
    if (className) p.className = className;
    root.append(p);
  };

  line(props.name, "map-popup__title");
  line(`AirNow monitor ${props.aqs_code}`, "map-popup__muted");
  if (props.pm25 === null) {
    line("No forecast at this horizon.");
  } else {
    const label = categoryInfo(categories, props.aqi as AqiCategoryInfo["key"])?.label ?? props.aqi;
    line(`Forecast PM2.5: ${formatPm25(props.pm25)}`);
    line(`${categoryLabel}: ${label}`);
  }
  if (props.fallback) {
    line("Lower confidence: no recent reading at this monitor.", "map-popup__warning");
  }
  return root;
}
