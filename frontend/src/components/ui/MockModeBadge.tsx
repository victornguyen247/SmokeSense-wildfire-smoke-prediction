import { USE_MOCKS } from "../../constants/env";

/** Makes it obvious that the map shows sample data, not live forecasts. */
export function MockModeBadge() {
  if (!USE_MOCKS) return null;
  return (
    <span className="badge badge--mock" title="VITE_USE_MOCKS=true: responses come from docs/api/fixtures">
      Demo data
    </span>
  );
}
