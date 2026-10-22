/** Required on every forecast view: model output is not an official warning (docs/ml.md §8). */
export function Disclaimer() {
  return (
    <p className="disclaimer">
      SmokeSense shows <strong>experimental model predictions</strong>, not official air quality
      warnings. For health guidance, follow{" "}
      <a href="https://www.airnow.gov/" target="_blank" rel="noreferrer">
        AirNow.gov
      </a>{" "}
      and your local air district.
    </p>
  );
}
