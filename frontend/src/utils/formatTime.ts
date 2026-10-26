// The API sends every timestamp in UTC; the UI shows California local time
// (docs/api.md, "Time").

const CALIFORNIA_TIME_ZONE = "America/Los_Angeles";

const dateTimeFormat = new Intl.DateTimeFormat("en-US", {
  timeZone: CALIFORNIA_TIME_ZONE,
  month: "short",
  day: "numeric",
  hour: "numeric",
  minute: "2-digit",
  timeZoneName: "short",
});

/** "Jul 27, 11:00 AM PDT" for an ISO-8601 UTC timestamp. */
export function formatLocalDateTime(isoUtc: string): string {
  return dateTimeFormat.format(new Date(isoUtc));
}

/**
 * "40 min ago", "3 h ago", "2 days ago". Uses the age the API computed rather than the
 * browser clock, so it stays correct when the user's clock is wrong (and in mock mode,
 * where the fixtures are from 2024).
 */
export function formatAgeMinutes(minutes: number): string {
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${Math.round(minutes)} min ago`;
  const hours = minutes / 60;
  if (hours < 48) return `${Math.round(hours)} h ago`;
  return `${Math.round(hours / 24)} days ago`;
}
