import { apiClient, bboxParam, unwrap } from "./client";
import type { Bbox, ObservationCollection } from "./models";

/** Latest PM2.5 reading per outdoor sensor (AirNow and corrected PurpleAir), at most 2 h old. */
export function getLatestPm25(bbox?: Bbox, signal?: AbortSignal): Promise<ObservationCollection> {
  return unwrap(
    apiClient.GET("/api/v1/observations/pm25/latest", { params: { query: bboxParam(bbox) }, signal }),
  );
}
