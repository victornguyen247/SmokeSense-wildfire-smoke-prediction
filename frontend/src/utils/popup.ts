import maplibregl, {
  type Map as MapLibreMap,
  type MapGeoJSONFeature,
  type MapLayerMouseEvent,
  type PointLike,
} from "maplibre-gl";

// One popup per map, shared by every layer: overlapping features (a monitor on a
// sensor) open one popup, the topmost layer's, since its handler was bound last.
const popups = new WeakMap<MapLibreMap, maplibregl.Popup>();

function sharedPopup(map: MapLibreMap): maplibregl.Popup {
  let popup = popups.get(map);
  if (!popup) {
    popup = new maplibregl.Popup({ closeButton: true, maxWidth: "260px" });
    popups.set(map, popup);
  }
  return popup;
}

// Layers that open a popup on click, so a plain map click (WEB-04: forecast here) can
// leave clicks on their features alone.
const popupLayers = new Set<string>();

/** Whether a click at `point` hits a feature that opens a popup. */
export function hasPopupFeatureAt(map: MapLibreMap, point: PointLike): boolean {
  const layers = [...popupLayers].filter((id) => map.getLayer(id));
  return layers.length > 0 && map.queryRenderedFeatures(point, { layers }).length > 0;
}

/** One line of a popup: plain text, styled by `className` (see `.map-popup` in index.css). */
export type PopupLine = { text: string; className?: "map-popup__title" | "map-popup__muted" | "map-popup__warning" };

/** Popup body, built from text nodes so names and values from the API can't inject HTML. */
export function popupContent(lines: PopupLine[]): HTMLElement {
  const root = document.createElement("div");
  root.className = "map-popup";
  for (const { text, className } of lines) {
    const p = document.createElement("p");
    p.textContent = text;
    if (className) p.className = className;
    root.append(p);
  }
  return root;
}

/**
 * Open a popup when a point in `layerId` is clicked, and show a pointer over it.
 * Returns the cleanup that removes the popup and the listeners.
 */
export function bindPointPopup(
  map: MapLibreMap,
  layerId: string,
  build: (feature: MapGeoJSONFeature) => PopupLine[],
): () => void {
  const popup = sharedPopup(map);
  const onClick = (event: MapLayerMouseEvent) => {
    const feature = event.features?.[0];
    if (!feature || feature.geometry.type !== "Point") return;
    popup
      .setLngLat(feature.geometry.coordinates as [number, number])
      .setDOMContent(popupContent(build(feature)))
      .addTo(map);
  };
  const onEnter = () => {
    map.getCanvas().style.cursor = "pointer";
  };
  const onLeave = () => {
    map.getCanvas().style.cursor = "";
  };
  map.on("click", layerId, onClick);
  map.on("mouseenter", layerId, onEnter);
  map.on("mouseleave", layerId, onLeave);
  popupLayers.add(layerId);
  return () => {
    popupLayers.delete(layerId);
    if (popup.isOpen()) popup.remove();
    map.off("click", layerId, onClick);
    map.off("mouseenter", layerId, onEnter);
    map.off("mouseleave", layerId, onLeave);
  };
}
