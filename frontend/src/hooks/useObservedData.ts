import { getActiveFires } from "../api/fires";
import type { Meta } from "../api/models";
import { getLatestPm25, getLatestWind } from "../api/observations";
import { useApiQuery } from "./useApiQuery";

/**
 * What is happening now, for the WEB-03 layers: fires, sensor PM2.5 and station wind,
 * statewide. They refetch whenever `/meta` refreshes (every 5 minutes, useMeta), since
 * FIRMS ingests every 30 min and AirNow and NWS hourly, and keep the last data while the
 * next request loads or if it fails.
 */
export function useObservedData(meta: Meta | undefined) {
  const at = meta?.generated_at;
  const options = { keepPrevious: true };
  const fires = useApiQuery((signal) => getActiveFires(undefined, signal), at ? `fires-active:${at}` : null, options);
  const sensors = useApiQuery(
    (signal) => getLatestPm25(undefined, signal),
    at ? `observations-pm25-latest:${at}` : null,
    options,
  );
  const wind = useApiQuery(
    (signal) => getLatestWind(undefined, signal),
    at ? `observations-wind-latest:${at}` : null,
    options,
  );
  return { fires, sensors, wind };
}
