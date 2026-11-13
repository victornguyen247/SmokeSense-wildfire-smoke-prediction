import { useEffect } from "react";
import maplibregl, { type MapMouseEvent } from "maplibre-gl";

import { useMap } from "../../context/MapContext";
import { hasPopupFeatureAt } from "../../utils/popup";

const DOUBLE_CLICK_MS = 300;

type LocationPickerProps = {
  /** The location the forecast card is showing, marked with a pin. */
  selected: { lat: number; lon: number } | null;
  /** A click on the map anywhere except a feature that opens a popup. */
  onPick: (lat: number, lon: number) => void;
};

/** WEB-04's "click on the map": picks a location for the forecast card and pins it. */
export function LocationPicker({ selected, onPick }: LocationPickerProps) {
  const map = useMap();

  useEffect(() => {
    if (!map) return;
    // A double-click zooms; wait briefly so its two clicks don't also pick a location.
    let pending: ReturnType<typeof setTimeout> | undefined;
    const onClick = (event: MapMouseEvent) => {
      if (hasPopupFeatureAt(map, event.point)) return;
      const { lat, lng } = event.lngLat;
      clearTimeout(pending);
      pending = setTimeout(() => onPick(lat, lng), DOUBLE_CLICK_MS);
    };
    const onDoubleClick = () => clearTimeout(pending);
    map.on("click", onClick);
    map.on("dblclick", onDoubleClick);
    return () => {
      clearTimeout(pending);
      map.off("click", onClick);
      map.off("dblclick", onDoubleClick);
    };
  }, [map, onPick]);

  useEffect(() => {
    if (!map || !selected) return;
    const marker = new maplibregl.Marker({ color: "#1f2328" }).setLngLat([selected.lon, selected.lat]).addTo(map);
    return () => {
      marker.remove();
    };
  }, [map, selected]);

  return null;
}
