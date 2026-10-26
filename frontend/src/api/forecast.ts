import { apiClient, bboxParam, unwrap } from "./client";
import type {
  Bbox,
  GridCellCollection,
  GridForecast,
  MonitorForecastCollection,
  PointForecast,
} from "./models";

/** Grid cell polygons. Static: refetch only when `/meta` `grid_key` changes. */
export function getGridCells(bbox?: Bbox, signal?: AbortSignal): Promise<GridCellCollection> {
  return unwrap(apiClient.GET("/api/v1/grid/cells", { params: { query: bboxParam(bbox) }, signal }));
}

/** Interpolated forecast per grid cell, for every horizon in one response. */
export function getForecastGrid(bbox?: Bbox, signal?: AbortSignal): Promise<GridForecast> {
  return unwrap(apiClient.GET("/api/v1/forecast/grid", { params: { query: bboxParam(bbox) }, signal }));
}

/** Model forecasts at AirNow monitors, every horizon. */
export function getForecastMonitors(
  bbox?: Bbox,
  signal?: AbortSignal,
): Promise<MonitorForecastCollection> {
  return unwrap(
    apiClient.GET("/api/v1/forecast/monitors", { params: { query: bboxParam(bbox) }, signal }),
  );
}

export type PointQuery = { lat: number; lon: number } | { zip: string };

/** Forecast for one location (lat/lon or ZIP), every horizon, plus its nearest monitor. */
export function getForecastPoint(query: PointQuery, signal?: AbortSignal): Promise<PointForecast> {
  return unwrap(apiClient.GET("/api/v1/forecast/point", { params: { query }, signal }));
}
