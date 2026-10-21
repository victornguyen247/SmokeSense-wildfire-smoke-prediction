import type { Meta } from "../../api/models";
import { SOURCE_LABELS } from "../../constants/sources";
import { formatAgeMinutes, formatLocalDateTime } from "../../utils/formatTime";

type ForecastStatusProps = {
  meta: Meta;
};

/** When the current forecast was issued, by which model, and how fresh each input is. */
export function ForecastStatus({ meta }: ForecastStatusProps) {
  return (
    <section className="panel-section" aria-labelledby="forecast-status-heading">
      <h2 id="forecast-status-heading" className="panel-section__heading">
        Forecast status
      </h2>

      {meta.latest_issued_at === null ? (
        <p>No forecast has been issued yet.</p>
      ) : (
        <p className="forecast-status__issued">
          Issued <time dateTime={meta.latest_issued_at}>{formatLocalDateTime(meta.latest_issued_at)}</time>
          {meta.forecast_age_minutes !== null && (
            <span className="muted"> · {formatAgeMinutes(meta.forecast_age_minutes)}</span>
          )}
          {meta.forecast_stale && <span className="badge badge--stale">Out of date</span>}
        </p>
      )}
      {meta.model_key && <p className="muted">Model {meta.model_key}</p>}

      <h3 className="panel-section__subheading">Data sources</h3>
      <ul className="source-list">
        {meta.sources.map((source) => (
          <li key={source.source} className="source-list__item">
            <span>{SOURCE_LABELS[source.source]}</span>
            <span className={source.stale ? "source-list__age source-list__age--stale" : "source-list__age"}>
              {source.age_minutes === null ? "no data yet" : formatAgeMinutes(source.age_minutes)}
              {source.stale && " · delayed"}
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
}
