// Mock mode (VITE_USE_MOCKS=true): MSW answers every /api/v1 request in the browser
// with the PM-02 fixtures from docs/api/fixtures, so the app runs with no backend.
//
// Add one of these to the page URL to see the other UI states:
//   ?mock=slow    every response waits 3 s (loading states)
//   ?mock=error   every response is a 500 internal_error (error states)

import { delay, http, HttpResponse, type JsonBodyType } from "msw";

import type { ApiErrorBody } from "../api/models";
import * as fixtures from "./fixtures";

const scenario = new URLSearchParams(window.location.search).get("mock");

// Rough California extent, enough to exercise the out_of_scope error in mock mode.
const CA = { minLon: -124.5, minLat: 32.5, maxLon: -114.1, maxLat: 42.1 };

// BboxParam in docs/api/openapi.yaml.
const BBOX_PATTERN = /^-?[0-9]+(\.[0-9]+)?(,-?[0-9]+(\.[0-9]+)?){3}$/;

function errorBody(code: ApiErrorBody["code"], message: string): ApiErrorBody {
  return { code, message };
}

async function respond(body: JsonBodyType, status = 200) {
  await delay(scenario === "slow" ? 3000 : undefined);
  if (scenario === "error") {
    return HttpResponse.json(
      errorBody("internal_error", "Simulated server error (mock mode, ?mock=error)."),
      { status: 500 },
    );
  }
  return HttpResponse.json(body, { status });
}

// `*` matches any origin, so the handlers work whatever VITE_API_BASE_URL is.
const api = (path: string) => `*/api/v1${path}`;

/** A query value as a number, or NaN when it is missing, empty or not numeric. */
function toNumber(value: string | null): number {
  return value === null || value.trim() === "" ? Number.NaN : Number(value);
}

/**
 * Validate an optional `bbox` like the real API (docs/api.md, "Coordinates and bbox"):
 * malformed or min > max is 400 invalid_bbox, entirely outside California is 404
 * out_of_scope. Returns the error response, or null when the bbox is fine or absent.
 */
function bboxError(url: URL) {
  const raw = url.searchParams.get("bbox");
  if (raw === null) return null;
  if (!BBOX_PATTERN.test(raw)) {
    return respond(errorBody("invalid_bbox", "bbox must be minLon,minLat,maxLon,maxLat."), 400);
  }
  const [minLon, minLat, maxLon, maxLat] = raw.split(",").map(Number);
  const inRange = [minLon, maxLon].every((x) => x >= -180 && x <= 180) &&
    [minLat, maxLat].every((y) => y >= -90 && y <= 90);
  if (!inRange || minLon > maxLon || minLat > maxLat) {
    return respond(
      errorBody("invalid_bbox", "bbox must be minLon,minLat,maxLon,maxLat with min <= max."),
      400,
    );
  }
  if (maxLon < CA.minLon || minLon > CA.maxLon || maxLat < CA.minLat || minLat > CA.maxLat) {
    return respond(
      errorBody("out_of_scope", "bbox is outside California; SmokeSense only forecasts for California."),
      404,
    );
  }
  return null;
}

/** A handler for a bbox endpoint that returns `fixture` when the bbox is valid. */
const withBbox =
  (fixture: JsonBodyType) =>
  ({ request }: { request: Request }) =>
    bboxError(new URL(request.url)) ?? respond(fixture);

function pointForecast(url: URL) {
  const lat = url.searchParams.get("lat");
  const lon = url.searchParams.get("lon");
  const zip = url.searchParams.get("zip");

  const hasLatLon = lat !== null && lon !== null;
  if (zip !== null ? lat !== null || lon !== null : !hasLatLon) {
    return respond(fixtures.errorInvalidQuery, 400);
  }
  if (zip !== null) {
    if (!/^[0-9]{5}$/.test(zip)) {
      return respond(errorBody("invalid_query", "zip must be a 5-digit ZIP code."), 400);
    }
    // California ZIPs start with 900–961.
    const prefix = Number(zip.slice(0, 3));
    if (prefix < 900 || prefix > 961) {
      return respond(errorBody("out_of_scope", `ZIP ${zip} is outside California.`), 404);
    }
    return respond(fixtures.forecastPoint);
  }

  // An empty `lat=` must not become 0, which is a valid coordinate.
  const latN = toNumber(lat);
  const lonN = toNumber(lon);
  if (Number.isNaN(latN) || Number.isNaN(lonN)) {
    return respond(errorBody("invalid_query", "lat and lon must be numbers."), 400);
  }
  if (latN < -90 || latN > 90 || lonN < -180 || lonN > 180) {
    return respond(errorBody("invalid_query", "lat must be in [-90, 90] and lon in [-180, 180]."), 400);
  }
  if (lonN < CA.minLon || lonN > CA.maxLon || latN < CA.minLat || latN > CA.maxLat) {
    return respond(
      errorBody(
        "out_of_scope",
        `Point (${latN}, ${lonN}) is outside California; SmokeSense only forecasts for California.`,
      ),
      404,
    );
  }
  // Near the "no forecast" fixture's query point (Mendocino NF), return that case.
  const noForecast = fixtures.forecastPointNoForecast.query;
  if (Math.abs(latN - noForecast.lat) < 0.15 && Math.abs(lonN - noForecast.lon) < 0.15) {
    return respond(fixtures.forecastPointNoForecast);
  }
  return respond(fixtures.forecastPoint);
}

export const handlers = [
  http.get(api("/meta"), () => respond(fixtures.meta)),
  http.get(api("/health"), () => respond(fixtures.health)),
  http.get(api("/grid/cells"), withBbox(fixtures.gridCells)),
  http.get(api("/forecast/grid"), withBbox(fixtures.forecastGrid)),
  http.get(api("/forecast/monitors"), withBbox(fixtures.forecastMonitors)),
  http.get(api("/forecast/point"), ({ request }) => pointForecast(new URL(request.url))),
  http.get(api("/fires/active"), withBbox(fixtures.firesActive)),
  http.get(api("/observations/pm25/latest"), withBbox(fixtures.observationsPm25Latest)),
  // Anything else under /api/v1 gets the API's unknown-route error.
  http.all(api("/*"), ({ request }) =>
    respond(errorBody("not_found", `No mock for ${new URL(request.url).pathname}.`), 404),
  ),
];
