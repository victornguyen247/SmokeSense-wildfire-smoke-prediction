import type { LngLatBoundsLike } from "maplibre-gl";

/** California's extent, [west, south] to [east, north]. The map opens fitted to it. */
export const CALIFORNIA_BOUNDS: LngLatBoundsLike = [
  [-124.48, 32.53],
  [-114.13, 42.01],
];

/** How far the user can pan: California plus a margin, so the state stays in view. */
export const MAX_BOUNDS: LngLatBoundsLike = [
  [-131, 29],
  [-107, 45.5],
];

/** Dashed outline of a lower-confidence forecast cell, on the map and in the legend. */
export const LOW_CONFIDENCE_OUTLINE = "#3c4043";
