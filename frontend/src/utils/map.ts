import type { Map as MapLibreMap } from "maplibre-gl";

/**
 * The basemap's first label layer. Data layers are inserted below it, so place names
 * stay readable on top of the forecast colors. Undefined when the style has no labels.
 */
export function firstSymbolLayerId(map: MapLibreMap): string | undefined {
  // getLayersOrder() lists ids without copying the whole style, unlike getStyle().
  return map.getLayersOrder().find((id) => map.getLayer(id)?.type === "symbol");
}

/**
 * Remove layers (in order) and then sources a component added. Safe to call when the
 * map was already removed: <MapView> removes the map when it unmounts, which can happen
 * before a child layer's cleanup runs.
 */
export function removeFromMap(map: MapLibreMap, layerIds: string[], sourceIds: string[]): void {
  if (!map.style) return;
  for (const id of layerIds) if (map.getLayer(id)) map.removeLayer(id);
  for (const id of sourceIds) if (map.getSource(id)) map.removeSource(id);
}
