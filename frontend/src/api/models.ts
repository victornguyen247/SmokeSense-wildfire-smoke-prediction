// Short names for the generated schema types, so components don't need to spell out
// components["schemas"][...]. Add an alias here when a new schema is first used.

import type { components } from "./types";

type Schemas = components["schemas"];

export type ApiErrorBody = Schemas["Error"];
export type Meta = Schemas["Meta"];
export type SourceFreshness = Schemas["SourceFreshness"];
export type AqiCategory = Schemas["AqiCategory"];
export type AqiCategoryInfo = Schemas["AqiCategoryInfo"];
export type HorizonHours = Schemas["HorizonHours"];
export type GridCellCollection = Schemas["GridCellCollection"];
export type GridForecast = Schemas["GridForecast"];
export type PointForecast = Schemas["PointForecast"];
export type MonitorForecastCollection = Schemas["MonitorForecastCollection"];
export type FireDetectionCollection = Schemas["FireDetectionCollection"];
export type ObservationCollection = Schemas["ObservationCollection"];
export type Health = Schemas["Health"];

/** `minLon,minLat,maxLon,maxLat` (WGS84, GeoJSON order), as the API's `bbox` parameter expects. */
export type Bbox = [minLon: number, minLat: number, maxLon: number, maxLat: number];
