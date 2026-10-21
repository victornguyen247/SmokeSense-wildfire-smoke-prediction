import type { SourceFreshness } from "../api/models";

/** Display names for the ingestion sources reported by /meta. */
export const SOURCE_LABELS: Record<SourceFreshness["source"], string> = {
  airnow: "AirNow monitors",
  purpleair: "PurpleAir sensors",
  firms: "NASA FIRMS fires",
  nws_obs: "NWS weather",
};
