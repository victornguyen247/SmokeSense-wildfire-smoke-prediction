import type { HorizonHours } from "../../api/models";
import { formatLocalDateTime } from "../../utils/formatTime";

type HorizonControlProps = {
  /** `/meta` `horizons`, in order. */
  horizons: HorizonHours[];
  value: HorizonHours;
  onChange: (horizon: HorizonHours) => void;
  /** `target_time` of the selected horizon (`issued_at + horizon`), when known. */
  targetTime?: string;
};

/**
 * Picks the forecast horizon. A radio group, so arrow keys move between hours and a
 * screen reader announces "3 hours ahead, 2 of 5".
 */
export function HorizonControl({ horizons, value, onChange, targetTime }: HorizonControlProps) {
  return (
    <fieldset className="horizon-control">
      <legend className="panel-section__subheading">Hours ahead</legend>
      <div className="horizon-control__options">
        {horizons.map((hours) => (
          <label key={hours} className="horizon-control__option">
            <input
              type="radio"
              name="forecast-horizon"
              value={hours}
              checked={hours === value}
              onChange={() => onChange(hours)}
            />
            <span aria-hidden="true">{hours} h</span>
            <span className="visually-hidden">{hours === 1 ? "1 hour ahead" : `${hours} hours ahead`}</span>
          </label>
        ))}
      </div>
      {targetTime && (
        <p className="horizon-control__target">
          Forecast for <time dateTime={targetTime}>{formatLocalDateTime(targetTime)}</time>
        </p>
      )}
    </fieldset>
  );
}
