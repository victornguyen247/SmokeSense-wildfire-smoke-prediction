import { useState, type FormEvent } from "react";

import type { PointQuery } from "../../api/forecast";

type LocationSearchProps = {
  onSearch: (query: PointQuery, label: string) => void;
};

const ZIP_PATTERN = /^[0-9]{5}$/;

/** Why the browser gave no location, in words a person can act on. */
function geolocationMessage(error: GeolocationPositionError): string {
  if (error.code === error.PERMISSION_DENIED) {
    return "Location access is blocked. Allow it in your browser's settings, or enter a ZIP code or click the map instead.";
  }
  if (error.code === error.TIMEOUT) {
    return "Finding your location took too long. Try again, or enter a ZIP code instead.";
  }
  return "Your location isn't available right now. Enter a ZIP code or click the map instead.";
}

/**
 * The three ways to ask for a forecast (WEB-04): a ZIP code, "Use my location", or a
 * click on the map (handled by the map; this only says it's possible).
 */
export function LocationSearch({ onSearch }: LocationSearchProps) {
  const [zip, setZip] = useState("");
  const [zipError, setZipError] = useState<string | null>(null);
  const [locating, setLocating] = useState(false);
  const [locationError, setLocationError] = useState<string | null>(null);

  const submitZip = (event: FormEvent) => {
    event.preventDefault();
    const value = zip.trim();
    // Format only: whether the ZIP is in California is the API's call (out_of_scope).
    if (!ZIP_PATTERN.test(value)) {
      setZipError("Enter a 5-digit ZIP code, e.g. 95926.");
      return;
    }
    setZipError(null);
    onSearch({ zip: value }, `ZIP ${value}`);
  };

  const useMyLocation = () => {
    setLocationError(null);
    if (!("geolocation" in navigator)) {
      setLocationError("This browser can't share your location. Enter a ZIP code or click the map instead.");
      return;
    }
    setLocating(true);
    navigator.geolocation.getCurrentPosition(
      (position) => {
        setLocating(false);
        onSearch({ lat: position.coords.latitude, lon: position.coords.longitude }, "your location");
      },
      (error) => {
        setLocating(false);
        setLocationError(geolocationMessage(error));
      },
      { enableHighAccuracy: false, timeout: 10_000, maximumAge: 5 * 60_000 },
    );
  };

  return (
    <div className="location-search">
      <form className="location-search__zip" onSubmit={submitZip} noValidate>
        <label htmlFor="zip-input" className="visually-hidden">
          ZIP code
        </label>
        <input
          id="zip-input"
          className="location-search__input"
          inputMode="numeric"
          autoComplete="postal-code"
          maxLength={5}
          placeholder="ZIP code"
          value={zip}
          onChange={(event) => setZip(event.target.value.replace(/[^0-9]/g, ""))}
          aria-invalid={zipError !== null}
          aria-describedby={zipError ? "zip-error" : undefined}
        />
        <button type="submit" className="button">
          Get forecast
        </button>
      </form>
      {zipError && (
        <p id="zip-error" className="location-search__error" role="alert">
          {zipError}
        </p>
      )}
      <button type="button" className="button location-search__locate" onClick={useMyLocation} disabled={locating}>
        {locating ? "Finding your location…" : "Use my location"}
      </button>
      {locationError && (
        <p className="location-search__error" role="alert">
          {locationError}
        </p>
      )}
      <p className="muted location-search__hint">Or click anywhere on the map.</p>
    </div>
  );
}
