import { getActiveFires } from "../api/fires";
import { getLatestPm25, getLatestWind } from "../api/observations";
import { useApiQuery } from "./useApiQuery";

/** What is happening now, for the WEB-03 layers: fires, sensor PM2.5 and station wind, statewide. */
export function useObservedData() {
  const fires = useApiQuery((signal) => getActiveFires(undefined, signal), "fires-active");
  const sensors = useApiQuery((signal) => getLatestPm25(undefined, signal), "observations-pm25-latest");
  const wind = useApiQuery((signal) => getLatestWind(undefined, signal), "observations-wind-latest");
  return { fires, sensors, wind };
}
