import { useEffect, useRef, useState, type ReactNode } from "react";
import maplibregl, { type Map as MapLibreMap } from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";

import { MAP_STYLE_URL } from "../../constants/env";
import { CALIFORNIA_BOUNDS, MAX_BOUNDS } from "../../constants/map";
import { MapContext } from "../../context/MapContext";

const NO_WEBGL = "Your browser can't display the map (WebGL is unavailable).";

let webglSupport: boolean | undefined;

/** Whether the browser can create a WebGL context. Probed once per page load. */
function supportsWebGL(): boolean {
  if (webglSupport === undefined) {
    try {
      const canvas = document.createElement("canvas");
      const gl = canvas.getContext("webgl2") ?? canvas.getContext("webgl");
      webglSupport = gl !== null;
      // Free the probe's context right away; browsers cap how many can be open.
      gl?.getExtension("WEBGL_lose_context")?.loseContext();
    } catch {
      webglSupport = false;
    }
  }
  return webglSupport;
}

type MapViewProps = {
  /** Map layers. They read the map with useMap() once it has loaded. */
  children?: ReactNode;
};

/** California-centred MapLibre map. Layers are added as children. */
export default function MapView({ children }: MapViewProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [map, setMap] = useState<MapLibreMap | null>(null);
  const [problem, setProblem] = useState<string | null>(() => (supportsWebGL() ? null : NO_WEBGL));

  useEffect(() => {
    const container = containerRef.current;
    if (!container || !supportsWebGL()) return;

    const instance = new maplibregl.Map({
      container,
      style: MAP_STYLE_URL,
      bounds: CALIFORNIA_BOUNDS,
      fitBoundsOptions: { padding: 24 },
      maxBounds: MAX_BOUNDS,
      attributionControl: { compact: true },
      dragRotate: false,
      pitchWithRotate: false,
    });

    instance.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-left");
    instance.touchZoomRotate.disableRotation();

    // Sprites, glyphs and tiles are only requested after the style document has loaded,
    // so an error before "style.load" means the style itself failed. Later errors are
    // single resources, which MapLibre retries or renders without.
    let styleLoaded = false;
    // Events from a map that was already removed (e.g. its aborted style request)
    // must not change the state of the map that replaced it.
    let disposed = false;
    instance.on("style.load", () => {
      styleLoaded = true;
    });
    instance.on("load", () => {
      if (disposed) return;
      setProblem(null);
      setMap(instance);
    });
    instance.on("error", () => {
      if (!disposed && !styleLoaded) {
        setProblem("The basemap couldn't load. Check your connection and reload the page.");
      }
    });

    return () => {
      disposed = true;
      setMap(null);
      instance.remove();
    };
  }, []);

  return (
    <div className="map-view">
      <div ref={containerRef} className="map-view__canvas" aria-label="Map of California" role="region" />
      {problem && (
        <p className="map-view__notice" role="alert">
          {problem}
        </p>
      )}
      <MapContext.Provider value={map}>{children}</MapContext.Provider>
    </div>
  );
}
