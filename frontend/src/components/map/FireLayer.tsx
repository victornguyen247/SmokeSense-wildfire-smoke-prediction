import { useEffect } from "react";
import type { ExpressionSpecification, GeoJSONSource } from "maplibre-gl";

import type { FireDetectionCollection } from "../../api/models";
import { FIRE_ATTRIBUTION } from "../../constants/sources";
import { useMap } from "../../context/MapContext";
import { formatLocalDateTime } from "../../utils/formatTime";
import { removeFromMap, setLayersVisible } from "../../utils/map";
import { bindPointPopup, type PopupLine } from "../../utils/popup";

const SOURCE_ID = "fires-active";
const LAYER_ID = "fires-active-circle";

// Near-black, not red: red is an AQI color, and a fire dot must stand out on a red cell.
const FIRE_COLOR = "#202124";

type FireProps = FireDetectionCollection["features"][number]["properties"];

const CONFIDENCE_LABELS: Record<FireProps["confidence"], string> = {
  low: "Low",
  nominal: "Nominal",
  high: "High",
};

type FireLayerProps = {
  /** Undefined until loaded: the layer is added empty, so it keeps its place in the stack. */
  fires: FireDetectionCollection | undefined;
  visible: boolean;
};

/**
 * Satellite fire detections from the last 72 h, one dot per ~375 m VIIRS pixel. Low
 * confidence detections are hollow, as docs/api.md ("/fires/active") requires.
 */
export function FireLayer({ fires, visible }: FireLayerProps) {
  const map = useMap();

  useEffect(() => {
    if (!map) return;
    map.addSource(SOURCE_ID, {
      type: "geojson",
      data: { type: "FeatureCollection", features: [] },
      attribution: FIRE_ATTRIBUTION,
    });
    const isLow: ExpressionSpecification = ["==", ["get", "confidence"], "low"];
    map.addLayer({
      id: LAYER_ID,
      type: "circle",
      source: SOURCE_ID,
      paint: {
        "circle-radius": ["interpolate", ["linear"], ["zoom"], 5, 2.5, 10, 6, 14, 9],
        "circle-color": ["case", isLow, "rgba(255, 255, 255, 0.7)", FIRE_COLOR],
        "circle-stroke-color": ["case", isLow, FIRE_COLOR, "#ffffff"],
        "circle-stroke-width": ["case", isLow, 1.5, 1],
      },
    });
    const unbindPopup = bindPointPopup(map, LAYER_ID, (feature) => firePopup(feature.properties as FireProps));
    return () => {
      unbindPopup();
      removeFromMap(map, [LAYER_ID], [SOURCE_ID]);
    };
  }, [map]);

  useEffect(() => {
    if (fires) (map?.getSource(SOURCE_ID) as GeoJSONSource | undefined)?.setData(fires);
  }, [map, fires]);

  useEffect(() => {
    if (map) setLayersVisible(map, [LAYER_ID], visible);
  }, [map, visible]);

  return null;
}

function firePopup(props: FireProps): PopupLine[] {
  const lines: PopupLine[] = [
    { text: "Fire detection", className: "map-popup__title" },
    { text: "NASA FIRMS, VIIRS SNPP satellite", className: "map-popup__muted" },
    { text: `Detected ${formatLocalDateTime(props.detected_at)}${daynightSuffix(props.daynight)}` },
    { text: `Confidence: ${CONFIDENCE_LABELS[props.confidence]}` },
  ];
  // MapLibre turns a GeoJSON null property into a missing one.
  if (typeof props.frp_mw === "number") lines.push({ text: `Fire radiative power: ${props.frp_mw} MW` });
  if (props.confidence === "low") {
    lines.push({ text: "Low confidence: may not be a fire.", className: "map-popup__warning" });
  }
  return lines;
}

function daynightSuffix(daynight: FireProps["daynight"]): string {
  if (daynight === "D") return " (day pass)";
  if (daynight === "N") return " (night pass)";
  return "";
}
