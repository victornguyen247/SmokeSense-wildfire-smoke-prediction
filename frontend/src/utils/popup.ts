import maplibregl, {
  type Map as MapLibreMap,
  type MapGeoJSONFeature,
  type MapLayerMouseEvent,
} from "maplibre-gl";

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
  const popup = new maplibregl.Popup({ closeButton: true, maxWidth: "260px" });
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
  return () => {
    popup.remove();
    map.off("click", layerId, onClick);
    map.off("mouseenter", layerId, onEnter);
    map.off("mouseleave", layerId, onLeave);
  };
}
