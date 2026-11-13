import type { ActiveAlert, AqiCategoryInfo } from "../../api/models";
import { categoryInfo, formatPm25 } from "../../utils/aqi";
import { formatLocalDateTime } from "../../utils/formatTime";

type AlertWarningProps = {
  /** `cell.active_alert` from `/forecast/point`; null or missing shows nothing. */
  alert: ActiveAlert | null | undefined;
  /** `/meta` `aqi_categories`, for the severity's label and color. */
  categories: AqiCategoryInfo[];
};

/**
 * WEB-05 part C: the in-app warning on the location card while the cell has an open alert
 * episode (docs/alerts.md, section 8). It is also the fallback if alert emails slip.
 * The cut-offs are applied by the API, so nothing here knows a threshold.
 */
export function AlertWarning({ alert, categories }: AlertWarningProps) {
  if (!alert) return null;
  const severity = categoryInfo(categories, alert.severity);
  const label = (severity?.label ?? alert.severity).toLowerCase();

  return (
    <div className="alert-warning" role="status" style={{ borderLeftColor: severity?.color }}>
      <p className="alert-warning__title">Model expects smoke {label}.</p>
      <p>
        Peak about {formatPm25(alert.peak_pm25_predicted)} around{" "}
        <time dateTime={alert.peak_target_time}>{formatLocalDateTime(alert.peak_target_time)}</time>.
      </p>
      <p className="alert-warning__note">Experimental model estimate, not an official warning.</p>
    </div>
  );
}
