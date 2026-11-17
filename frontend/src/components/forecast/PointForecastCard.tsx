import type { ApiError } from "../../api/client";
import type { AqiCategoryInfo, HorizonHours, Meta, PointForecast } from "../../api/models";
import type { QueryState } from "../../hooks/useApiQuery";
import { categoryInfo, formatPm25, NO_DATA_COLOR } from "../../utils/aqi";
import { formatLocalDateTime, formatLocalHour } from "../../utils/formatTime";
import { ErrorMessage } from "../ui/ErrorMessage";
import { Spinner } from "../ui/Spinner";

// Above this, a ZIP's centroid can be 20+ km from a given house (docs/api.md, "/forecast/point").
const LARGE_ZIP_AREA_KM2 = 500;

type ForecastRow = PointForecast["cell"]["forecasts"][number] | NonNullable<PointForecast["nearest_monitor"]>["forecasts"][number];

type PointForecastCardProps = {
  /** "ZIP 95926", "your location" or a lat/lon, as it reads after "Forecast for". */
  label: string;
  forecast: QueryState<PointForecast> & { retry: () => void };
  meta: Meta;
  /** The horizon picked on the map; its row is highlighted. */
  horizon: HorizonHours;
  onClose: () => void;
};

/** Errors a person can act on, in plain words; anything else shows the API's message with a retry. */
function friendlyError(error: ApiError, label: string): string | null {
  const subject = label.charAt(0).toUpperCase() + label.slice(1);
  if (error.code === "out_of_scope") return `${subject} is outside California. SmokeSense only forecasts for California.`;
  if (error.code === "zip_not_found") return `We couldn't find ${label}. Check the number, or click the map instead.`;
  if (error.code === "invalid_query") return error.message;
  if (error.code === "forecast_unavailable") return "No forecast has been issued yet. Try again in a few minutes.";
  return null;
}

/** WEB-04: PM2.5 and AQI category per horizon for one location, with how well-supported it is. */
export function PointForecastCard({ label, forecast, meta, horizon, onClose }: PointForecastCardProps) {
  return (
    <section className="point-card" aria-labelledby="point-card-heading" aria-live="polite">
      <div className="point-card__header">
        <h2 id="point-card-heading" className="panel-section__heading">
          Forecast for {label}
        </h2>
        <button type="button" className="point-card__close" onClick={onClose} aria-label="Close the location forecast">
          ×
        </button>
      </div>

      {forecast.status === "loading" && <Spinner label="Loading the forecast…" />}
      {forecast.status === "error" &&
        (friendlyError(forecast.error, label) ? (
          <p className="point-card__notice">{friendlyError(forecast.error, label)}</p>
        ) : (
          <ErrorMessage title="Couldn't load this forecast" message={forecast.error.message} onRetry={forecast.retry} />
        ))}
      {forecast.status === "success" && <PointForecastBody data={forecast.data} meta={meta} horizon={horizon} />}

      <p className="point-card__disclaimer">
        Experimental model estimate, not an official warning. Follow AirNow.gov and your local air district.
      </p>
    </section>
  );
}

function PointForecastBody({ data, meta, horizon }: { data: PointForecast; meta: Meta; horizon: HorizonHours }) {
  const { cell, nearest_monitor: monitor, query } = data;
  const lowConfidence = cell.nearest_monitor_dist_km !== null && cell.nearest_monitor_dist_km > meta.low_confidence_dist_km;

  return (
    <>
      <p className="muted">
        Issued <time dateTime={data.issued_at}>{formatLocalDateTime(data.issued_at)}</time>
      </p>
      {query.zip_area_km2 !== null && query.zip_area_km2 > LARGE_ZIP_AREA_KM2 && (
        <p className="point-card__notice">
          ZIP {query.zip} is large ({Math.round(query.zip_area_km2).toLocaleString()} km²), so this forecast is for its
          center and may differ where you are. Click the map for a closer spot.
        </p>
      )}

      {cell.has_forecast ? (
        <>
          <ForecastTable rows={cell.forecasts} categories={meta.aqi_categories} label={meta.aqi_category_label} horizon={horizon} />
          <p className={lowConfidence ? "point-card__notice" : "muted point-card__support"}>
            {lowConfidence && "Lower confidence: "}
            Interpolated from monitors; the nearest one used is {cell.nearest_monitor_dist_km} km from this area.
          </p>
        </>
      ) : (
        <p className="point-card__notice">
          No forecast here: no monitor within {meta.max_interpolation_dist_km} km
          {cell.nearest_monitor_dist_km !== null && ` (the nearest is ${cell.nearest_monitor_dist_km} km away)`}.
        </p>
      )}

      {monitor && (
        <div className="point-card__monitor">
          <h3 className="panel-section__subheading">Nearest monitor</h3>
          <p>
            {monitor.name ?? `AirNow ${monitor.aqs_code}`}, {monitor.distance_km} km away
          </p>
          {!cell.has_forecast && (
            <ForecastTable rows={monitor.forecasts} categories={meta.aqi_categories} label={meta.aqi_category_label} horizon={horizon} />
          )}
          {monitor.forecasts.some((f) => f.source === "fallback") && (
            <p className="point-card__notice">Lower confidence: this monitor has no recent reading.</p>
          )}
        </div>
      )}
    </>
  );
}

function ForecastTable({
  rows,
  categories,
  label,
  horizon,
}: {
  rows: ForecastRow[];
  categories: AqiCategoryInfo[];
  label: string;
  horizon: HorizonHours;
}) {
  return (
    <table className="point-card__table">
      <thead>
        <tr>
          <th scope="col">Ahead</th>
          <th scope="col">Time</th>
          <th scope="col">PM2.5</th>
          <th scope="col">{label}</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((row) => {
          const info = categoryInfo(categories, row.aqi_category);
          return (
            <tr key={row.horizon_hours} className={row.horizon_hours === horizon ? "point-card__row--selected" : undefined}>
              <td>{row.horizon_hours} h</td>
              <td>
                <time dateTime={row.target_time}>{formatLocalHour(row.target_time)}</time>
              </td>
              <td>{formatPm25(row.pm25)}</td>
              <td>
                <span className="point-card__swatch" style={{ background: info?.color ?? NO_DATA_COLOR }} aria-hidden="true" />
                {info?.label ?? row.aqi_category}
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}
