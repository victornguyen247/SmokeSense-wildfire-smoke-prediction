import { useEffect } from "react";
import type { ExpressionSpecification, GeoJSONSource } from "maplibre-gl";

import type { WindObservationCollection } from "../../api/models";
import { WIND_ATTRIBUTION } from "../../constants/sources";
import { useMap } from "../../context/MapContext";
import { formatLocalDateTime } from "../../utils/formatTime";
import { removeFromMap, setLayersVisible } from "../../utils/map";
import { bindPointPopup, type PopupLine } from "../../utils/popup";
import { sdfIcon } from "../../utils/sdfIcon";

const SOURCE_ID = "observations-wind";
const ARROW_LAYER_ID = "observations-wind-arrow";
const CALM_LAYER_ID = "observations-wind-calm";
const ICON_ID = "wind-arrow";
const CALM_ICON_ID = "wind-calm";

const WIND_COLOR = "#1f2328";
const MS_TO_MPH = 2.23694;
const COMPASS = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE", "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"];

type WindProps = WindObservationCollection["features"][number]["properties"];

type WindLayerProps = {
  /** Undefined until loaded: the layer is added empty, so it keeps its place in the stack. */
  wind: WindObservationCollection | undefined;
  visible: boolean;
};

// An arrow pointing up (north), in a 32 px icon.
const ARROW: [number, number][] = [[16, 2], [26, 14], [19.5, 14], [19.5, 30], [12.5, 30], [12.5, 14], [6, 14]];

function insidePolygon(x: number, y: number, polygon: [number, number][]): boolean {
  let inside = false;
  for (let i = 0, j = polygon.length - 1; i < polygon.length; j = i++) {
    const [xi, yi] = polygon[i];
    const [xj, yj] = polygon[j];
    if (yi > y !== yj > y && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) inside = !inside;
  }
  return inside;
}

// Calm: a bullseye, so it isn't mistaken for a hollow (low-confidence) fire.
function insideBullseye(x: number, y: number): boolean {
  const r = Math.hypot(x - 16, y - 16);
  return r <= 4 || (r >= 8 && r <= 12);
}

const hasDirection: ExpressionSpecification = ["!=", ["get", "wind_dir_deg"], null];

/**
 * Measured wind at NWS stations: an arrow pointing the way the wind blows, sized by
 * speed, or a bullseye when calm. The API sends the direction the wind blows from
 * (docs/api.md, "/observations/wind/latest"), so arrows are turned 180°.
 */
export function WindLayer({ wind, visible }: WindLayerProps) {
  const map = useMap();

  useEffect(() => {
    if (!map) return;
    map.addSource(SOURCE_ID, {
      type: "geojson",
      data: { type: "FeatureCollection", features: [] },
      attribution: WIND_ATTRIBUTION,
    });
    if (!map.hasImage(ICON_ID)) {
      map.addImage(ICON_ID, sdfIcon(32, (x, y) => insidePolygon(x, y, ARROW)), { sdf: true });
    }
    if (!map.hasImage(CALM_ICON_ID)) map.addImage(CALM_ICON_ID, sdfIcon(32, insideBullseye), { sdf: true });
    map.addLayer({
      id: ARROW_LAYER_ID,
      type: "symbol",
      source: SOURCE_ID,
      filter: hasDirection,
      layout: {
        "icon-image": ICON_ID,
        "icon-rotate": ["+", ["get", "wind_dir_deg"], 180],
        "icon-rotation-alignment": "map",
        "icon-size": ["interpolate", ["linear"], ["get", "wind_speed_ms"], 0, 0.45, 10, 1.1],
        "icon-allow-overlap": true,
        "icon-ignore-placement": true,
      },
      paint: {
        "icon-color": WIND_COLOR,
        "icon-halo-color": "#ffffff",
        "icon-halo-width": 1.5,
      },
    });
    map.addLayer({
      id: CALM_LAYER_ID,
      type: "symbol",
      source: SOURCE_ID,
      filter: ["!", hasDirection],
      layout: {
        "icon-image": CALM_ICON_ID,
        "icon-size": 0.55,
        "icon-allow-overlap": true,
        "icon-ignore-placement": true,
      },
      paint: { "icon-color": WIND_COLOR, "icon-halo-color": "#ffffff", "icon-halo-width": 1.5 },
    });
    const unbindArrow = bindPointPopup(map, ARROW_LAYER_ID, (f) => windPopup(f.properties as WindProps));
    const unbindCalm = bindPointPopup(map, CALM_LAYER_ID, (f) => windPopup(f.properties as WindProps));
    return () => {
      unbindArrow();
      unbindCalm();
      removeFromMap(map, [ARROW_LAYER_ID, CALM_LAYER_ID], [SOURCE_ID]);
    };
  }, [map]);

  useEffect(() => {
    if (wind) (map?.getSource(SOURCE_ID) as GeoJSONSource | undefined)?.setData(wind);
  }, [map, wind]);

  useEffect(() => {
    if (map) setLayersVisible(map, [ARROW_LAYER_ID, CALM_LAYER_ID], visible);
  }, [map, visible]);

  return null;
}

function windPopup(props: WindProps): PopupLine[] {
  const speed = `${props.wind_speed_ms.toFixed(1)} m/s (${Math.round(props.wind_speed_ms * MS_TO_MPH)} mph)`;
  // MapLibre turns a GeoJSON null property into a missing one.
  const direction =
    typeof props.wind_dir_deg === "number"
      ? `from the ${COMPASS[Math.round(props.wind_dir_deg / 22.5) % 16]} (${Math.round(props.wind_dir_deg)}°)`
      : "calm or variable";
  return [
    { text: `Wind at ${props.station_id}`, className: "map-popup__title" },
    { text: "NWS weather station, measured", className: "map-popup__muted" },
    { text: `${speed}, ${direction}` },
    { text: `Observed ${formatLocalDateTime(props.valid_at)}` },
  ];
}
