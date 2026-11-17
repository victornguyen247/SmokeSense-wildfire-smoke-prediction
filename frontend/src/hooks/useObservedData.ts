import { getActiveFires } from "../api/fires";
import { getLatestPm25 } from "../api/observations";
import { useApiQuery } from "./useApiQuery";

/** What is happening now, for the WEB-03 layers: fire detections and sensor PM2.5, statewide. */
export function useObservedData() {
  const fires = useApiQuery((signal) => getActiveFires(undefined, signal), "fires-active");
  const sensors = useApiQuery((signal) => getLatestPm25(undefined, signal), "observations-pm25-latest");
  return { fires, sensors };
}
