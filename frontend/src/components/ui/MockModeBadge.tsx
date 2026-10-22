import { USE_MOCKS } from "../../constants/env";

type MockModeBadgeProps = {
  /** `/meta` `mock_mode`: the API itself is serving fixtures (API-01 MOCK_MODE). */
  apiMockMode?: boolean;
};

/**
 * Makes it obvious that the app shows sample data, not live forecasts. Shown when the
 * frontend mocks the API (VITE_USE_MOCKS) or the API reports it is in mock mode.
 */
export function MockModeBadge({ apiMockMode = false }: MockModeBadgeProps) {
  if (!USE_MOCKS && !apiMockMode) return null;
  const title = USE_MOCKS
    ? "Frontend mock mode (VITE_USE_MOCKS=true): responses come from docs/api/fixtures."
    : "The API is in mock mode: it is serving sample data, not live forecasts.";
  return (
    <span className="badge badge--mock" title={title}>
      Demo data
    </span>
  );
}
