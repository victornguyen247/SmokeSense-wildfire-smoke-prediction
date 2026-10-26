/** Required on every forecast view (CLAUDE.md, frontend rules; docs/ml.md §8). */
export function Disclaimer() {
  return (
    <p className="disclaimer">
      SmokeSense forecasts are an <strong>experimental model estimate, not an official warning</strong>.
      For health guidance, follow{" "}
      <a href="https://www.airnow.gov/" target="_blank" rel="noreferrer">
        AirNow.gov
      </a>{" "}
      and your local air district.
    </p>
  );
}
