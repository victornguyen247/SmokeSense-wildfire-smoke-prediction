import type { Map as MapLibreMap, MapLayerMouseEvent } from "maplibre-gl";
import { describe, expect, it, vi } from "vitest";

import { bindPointPopup } from "./popup";

// A stand-in for MapLibre's popup with only what bindPointPopup uses; `popups` lists
// every one created, so a test can see whether the map's shared popup is open.
const popups = vi.hoisted(() => [] as { isOpen: () => boolean }[]);
vi.mock("maplibre-gl", () => {
  class Popup {
    private open = false;
    constructor() {
      popups.push(this);
    }
    setLngLat() {
      return this;
    }
    setDOMContent() {
      return this;
    }
    addTo() {
      this.open = true;
      return this;
    }
    isOpen() {
      return this.open;
    }
    remove() {
      this.open = false;
      return this;
    }
  }
  return { default: { Popup } };
});

type Handler = (event: MapLayerMouseEvent) => void;

/** A map that records click handlers per layer; `click(layer)` clicks a point in it. */
function fakeMap() {
  const clicks = new Map<string, Handler>();
  const map = {
    on: (type: string, layer: string, handler: Handler) => {
      if (type === "click") clicks.set(layer, handler);
    },
    off: () => {},
    getCanvas: () => ({ style: {} }),
  } as unknown as MapLibreMap;
  const click = (layer: string) =>
    clicks.get(layer)!({
      features: [{ geometry: { type: "Point", coordinates: [-121.8, 39.7] }, properties: {} }],
    } as unknown as MapLayerMouseEvent);
  return { map, click };
}

/** Whether the popup most recently created (the new map's shared one) is open. */
const popupOpen = () => popups[popups.length - 1].isOpen();

describe("bindPointPopup", () => {
  it("leaves another layer's open popup alone when a layer is unbound", () => {
    const { map, click } = fakeMap();
    const unbindFires = bindPointPopup(map, "fires", () => [{ text: "Fire" }]);
    const unbindMonitors = bindPointPopup(map, "monitors", () => [{ text: "Monitor" }]);

    click("fires");
    unbindMonitors(); // e.g. the monitor layer re-binding after a /meta refresh
    expect(popupOpen()).toBe(true);

    unbindFires();
    expect(popupOpen()).toBe(false);
  });

  it("closes its own popup when unbound", () => {
    const { map, click } = fakeMap();
    const unbind = bindPointPopup(map, "sensors", () => [{ text: "Sensor" }]);
    click("sensors");
    expect(popupOpen()).toBe(true);
    unbind();
    expect(popupOpen()).toBe(false);
  });
});
