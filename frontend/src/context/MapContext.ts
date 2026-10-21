import { createContext, useContext } from "react";
import type { Map as MapLibreMap } from "maplibre-gl";

/**
 * The MapLibre map, for layers rendered inside <MapView> (forecast grid, monitors,
 * fires, sensors). Null until the map and its style have loaded.
 */
export const MapContext = createContext<MapLibreMap | null>(null);

/** The loaded map, or null while it is still loading. Use inside <MapView>. */
export function useMap(): MapLibreMap | null {
  return useContext(MapContext);
}
