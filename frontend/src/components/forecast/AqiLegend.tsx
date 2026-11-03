import type { Meta } from "../../api/models";
import { formatRange, NO_DATA_COLOR } from "../../utils/aqi";

type AqiLegendProps = {
  meta: Meta;
};

/**
 * The map legend, from `/meta`: every category's label and PM2.5 range next to its
 * swatch, so it never relies on color alone, plus the no-data and lower-confidence keys.
 */
export function AqiLegend({ meta }: AqiLegendProps) {
  return (
    <div className="aqi-legend">
      <h3 className="panel-section__subheading">{meta.aqi_category_label}</h3>
      <ul className="aqi-legend__list">
        {meta.aqi_categories.map((category) => (
          <li key={category.key} className="aqi-legend__item">
            <span className="aqi-legend__swatch" style={{ background: category.color }} aria-hidden="true" />
            <span className="aqi-legend__label">{category.label}</span>
            <span className="aqi-legend__range">{formatRange(category)}</span>
          </li>
        ))}
        <li className="aqi-legend__item">
          <span
            className="aqi-legend__swatch aqi-legend__swatch--faded"
            style={{ background: NO_DATA_COLOR }}
            aria-hidden="true"
          />
          <span className="aqi-legend__label">No forecast</span>
          <span className="aqi-legend__range">no monitor within {meta.max_interpolation_dist_km} km</span>
        </li>
        <li className="aqi-legend__item">
          <span className="aqi-legend__swatch aqi-legend__swatch--low-confidence" aria-hidden="true" />
          <span className="aqi-legend__label">Lower confidence</span>
          <span className="aqi-legend__range">over {meta.low_confidence_dist_km} km from a monitor</span>
        </li>
        <li className="aqi-legend__item">
          <span className="aqi-legend__swatch aqi-legend__swatch--monitor" aria-hidden="true" />
          <span className="aqi-legend__label">Monitor forecast</span>
          <span className="aqi-legend__range">hollow: lower confidence</span>
        </li>
      </ul>
    </div>
  );
}
