import { apiClient, bboxParam, unwrap } from "./client";
import type { Bbox, FireDetectionCollection } from "./models";

/** VIIRS SNPP fire detections from the last 72 hours. */
export function getActiveFires(bbox?: Bbox, signal?: AbortSignal): Promise<FireDetectionCollection> {
  return unwrap(apiClient.GET("/api/v1/fires/active", { params: { query: bboxParam(bbox) }, signal }));
}
