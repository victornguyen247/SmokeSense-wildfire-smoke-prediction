import type { ApiError } from "../../api/client";

export type LayerKey = "forecast" | "fires" | "sensors";

export type LayerVisibility = Record<LayerKey, boolean>;

export type LayerOption = {
  key: LayerKey;
  label: string;
  /** Shown after the label, e.g. "30 detections". */
  detail?: string;
  /** Data credit for the layer. */
  attribution?: string;
  loading?: boolean;
  error?: ApiError;
  onRetry?: () => void;
};

type LayerControlProps = {
  options: LayerOption[];
  visible: LayerVisibility;
  onChange: (key: LayerKey, visible: boolean) => void;
};

/** One checkbox per map layer. Each layer toggles on its own. */
export function LayerControl({ options, visible, onChange }: LayerControlProps) {
  return (
    <fieldset className="layer-control">
      <legend className="panel-section__subheading">Map layers</legend>
      {options.map((option) => (
        <div key={option.key} className="layer-control__item">
          <label className="layer-control__label">
            <input
              type="checkbox"
              checked={visible[option.key]}
              onChange={(event) => onChange(option.key, event.target.checked)}
            />
            <span className={`layer-control__key layer-control__key--${option.key}`} aria-hidden="true" />
            <span>{option.label}</span>
            {option.detail && <span className="muted">{option.detail}</span>}
            {option.loading && <span className="muted">loading…</span>}
          </label>
          {option.error && (
            <p className="layer-control__error" role="alert">
              Couldn't load: {option.error.message}{" "}
              {option.onRetry && (
                <button type="button" className="button button--small" onClick={option.onRetry}>
                  Try again
                </button>
              )}
            </p>
          )}
          {option.attribution && <p className="layer-control__attribution">{option.attribution}</p>}
        </div>
      ))}
    </fieldset>
  );
}
