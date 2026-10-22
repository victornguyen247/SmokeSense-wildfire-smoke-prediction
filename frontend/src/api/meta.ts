import { apiClient, unwrap } from "./client";
import type { Health, Meta } from "./models";

/** Active model, latest forecast cycle, freshness, thresholds and the AQI legend. */
export function getMeta(signal?: AbortSignal): Promise<Meta> {
  return unwrap(apiClient.GET("/api/v1/meta", { signal }));
}

export function getHealth(signal?: AbortSignal): Promise<Health> {
  return unwrap(apiClient.GET("/api/v1/health", { signal }));
}
