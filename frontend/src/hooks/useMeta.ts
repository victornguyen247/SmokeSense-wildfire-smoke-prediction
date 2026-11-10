import { useEffect, useState } from "react";

import { getMeta } from "../api/meta";
import { useApiQuery } from "./useApiQuery";

// A new forecast cycle arrives hourly; checking every 5 minutes shows it, and the stale
// flags, without a reload.
const REFRESH_MS = 5 * 60_000;

/** `/meta`: forecast cycle, freshness, thresholds, AQI legend and the current grid key. */
export function useMeta() {
  const [refresh, setRefresh] = useState(0);
  useEffect(() => {
    const timer = setInterval(() => setRefresh((n) => n + 1), REFRESH_MS);
    return () => clearInterval(timer);
  }, []);
  // A failed refresh keeps the last /meta on screen; its stale flags show if it gets old.
  return useApiQuery((signal) => getMeta(signal), `meta#${refresh}`, { keepPrevious: refresh > 0 });
}
