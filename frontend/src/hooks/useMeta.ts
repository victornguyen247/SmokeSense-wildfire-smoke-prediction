import { getMeta } from "../api/meta";
import { useApiQuery } from "./useApiQuery";

/** `/meta`: forecast cycle, freshness, thresholds, AQI legend and the current grid key. */
export function useMeta() {
  return useApiQuery((signal) => getMeta(signal), []);
}
